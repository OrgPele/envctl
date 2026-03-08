from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import Final
from typing import Callable

from envctl_engine.state.models import PortPlan


class PortPlanner:
    def __init__(
        self,
        backend_base: int = 8000,
        frontend_base: int = 9000,
        spacing: int = 20,
        db_base: int = 5432,
        redis_base: int = 6379,
        n8n_base: int = 5678,
        lock_dir: str | None = None,
        session_id: str | None = None,
        stale_lock_seconds: int = 3600,
        availability_checker: Callable[[int], bool] | None = None,
        pid_checker: Callable[[int], bool] | None = None,
        time_provider: Callable[[], float] | None = None,
        event_handler: Callable[[str, dict[str, object]], None] | None = None,
        availability_mode: str = "auto",
        preferred_port_strategy: str = "project_slot",
        scope_key: str | None = None,
    ) -> None:
        self.backend_base = backend_base
        self.frontend_base = frontend_base
        self.spacing = spacing
        self.db_base = db_base
        self.redis_base = redis_base
        self.n8n_base = n8n_base
        self.lock_dir = Path(lock_dir or "/tmp/envctl-python-locks")
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id or f"session-{uuid.uuid4().hex[:8]}"
        self.session_pid = os.getpid()
        self.stale_lock_seconds = max(stale_lock_seconds, 0)
        self.availability_checker = availability_checker
        self.pid_checker = pid_checker
        self.time_provider = time_provider or time.time
        self.event_handler = event_handler
        self.availability_mode = availability_mode.strip().lower() or "auto"
        strategy = preferred_port_strategy.strip().lower()
        if strategy not in {"project_slot", "legacy_spacing"}:
            strategy = "project_slot"
        self.preferred_port_strategy = strategy
        self.scope_key = str(scope_key or "global").strip() or "global"
        self.max_port: Final[int] = 65000

    def plan_project(self, project: str, index: int = 0, requested: dict[str, int] | None = None, sources: dict[str, str] | None = None, retries: dict[str, int] | None = None) -> dict[str, PortPlan]:
        requested = requested or {}
        sources = sources or {}
        retries = retries or {}
        backend_requested = requested.get("backend", self._preferred_port(project, "backend", self.backend_base, index=index))
        frontend_requested = requested.get("frontend", self._preferred_port(project, "frontend", self.frontend_base, index=index))
        return {
            "backend": PortPlan(project=project, requested=backend_requested, assigned=backend_requested, final=backend_requested, source=sources.get("backend", "env"), retries=retries.get("backend", 0)),
            "frontend": PortPlan(project=project, requested=frontend_requested, assigned=frontend_requested, final=frontend_requested, source=sources.get("frontend", "env"), retries=retries.get("frontend", 0)),
        }

    def plan_project_stack(
        self,
        project: str,
        index: int = 0,
        requested: dict[str, int] | None = None,
        sources: dict[str, str] | None = None,
        retries: dict[str, int] | None = None,
    ) -> dict[str, PortPlan]:
        requested = requested or {}
        sources = sources or {}
        retries = retries or {}
        plans = self.plan_project(project, index=index, requested=requested, sources=sources, retries=retries)
        db_requested = requested.get("db", self._preferred_port(project, "db", self.db_base, index=index))
        redis_requested = requested.get("redis", self._preferred_port(project, "redis", self.redis_base, index=index))
        n8n_requested = requested.get("n8n", self._preferred_port(project, "n8n", self.n8n_base, index=index))
        plans.update(
            {
                "db": PortPlan(
                    project=project,
                    requested=db_requested,
                    assigned=db_requested,
                    final=db_requested,
                    source=sources.get("db", "planner"),
                    retries=retries.get("db", 0),
                ),
                "redis": PortPlan(
                    project=project,
                    requested=redis_requested,
                    assigned=redis_requested,
                    final=redis_requested,
                    source=sources.get("redis", "planner"),
                    retries=retries.get("redis", 0),
                ),
                "n8n": PortPlan(
                    project=project,
                    requested=n8n_requested,
                    assigned=n8n_requested,
                    final=n8n_requested,
                    source=sources.get("n8n", "planner"),
                    retries=retries.get("n8n", 0),
                ),
            }
        )
        return plans

    def reserve_next(self, start_port: int, owner: str) -> int:
        if start_port <= 0:
            raise ValueError("start_port must be positive")
        port = start_port
        while port <= self.max_port:
            if self._reserve_port(port, owner):
                return port
            port += 1
        raise RuntimeError(f"no free port found from {start_port} to {self.max_port}")

    def update_final_port(self, plan: PortPlan, final_port: int, source: str = "retry") -> PortPlan:
        plan.final = final_port
        plan.assigned = final_port
        plan.source = source
        plan.retries += 1
        return plan

    def attach_existing_port(self, plan: PortPlan, existing_port: int) -> PortPlan:
        plan.assigned = existing_port
        plan.final = existing_port
        plan.source = "existing_container"
        return plan

    def release(self, port: int, owner: str | None = None) -> None:
        lock_path = self._lock_path(port)
        if not lock_path.exists():
            return
        if owner is None:
            lock_path.unlink(missing_ok=True)
            self._emit("port.lock.release", port=port, owner=None, session=self.session_id)
            return
        try:
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            lock_path.unlink(missing_ok=True)
            self._emit("port.lock.release", port=port, owner=owner, session=self.session_id)
            return
        if payload.get("owner") == owner:
            lock_path.unlink(missing_ok=True)
            self._emit("port.lock.release", port=port, owner=owner, session=self.session_id)

    def release_session(self) -> None:
        for lock_path in self.lock_dir.glob("*.lock"):
            try:
                payload = json.loads(lock_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                lock_path.unlink(missing_ok=True)
                self._emit("port.lock.release", port=self._port_from_lock_path(lock_path), owner=None, session=self.session_id)
                continue
            if payload.get("session") == self.session_id:
                lock_path.unlink(missing_ok=True)
                self._emit(
                    "port.lock.release",
                    port=self._port_from_lock_path(lock_path),
                    owner=payload.get("owner"),
                    session=self.session_id,
                )

    def release_all(self) -> None:
        for lock_path in self.lock_dir.glob("*.lock"):
            owner = None
            try:
                payload = json.loads(lock_path.read_text(encoding="utf-8"))
                owner = payload.get("owner")
            except (OSError, json.JSONDecodeError):
                owner = None
            lock_path.unlink(missing_ok=True)
            self._emit(
                "port.lock.release",
                port=self._port_from_lock_path(lock_path),
                owner=owner,
                session=self.session_id,
            )

    def _lock_path(self, port: int) -> Path:
        return self.lock_dir / f"{port}.lock"

    def _preferred_port(self, project: str, service_name: str, base: int, *, index: int) -> int:
        if self.preferred_port_strategy == "legacy_spacing":
            if service_name in {"backend", "frontend"}:
                return base + (index * self.spacing)
            return base + index
        slot = self._project_slot(project)
        return base + slot

    def _project_slot(self, project: str) -> int:
        normalized = self._normalize_project_identity(project)
        if normalized in {"", "main"}:
            return 0
        span = self._project_slot_span()
        digest = hashlib.sha1(f"{self.scope_key}:{normalized}".encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % span

    def _project_slot_span(self) -> int:
        bases = sorted(
            {
                int(port)
                for port in (
                    self.db_base,
                    self.n8n_base,
                    self.redis_base,
                    self.backend_base,
                    self.frontend_base,
                )
                if int(port) > 0
            }
        )
        if len(bases) > 1:
            gaps = [upper - lower for lower, upper in zip(bases, bases[1:]) if upper > lower]
            if gaps:
                return max(1, min(gaps))
        return max(int(self.spacing), 1)

    @staticmethod
    def _normalize_project_identity(project: str) -> str:
        normalized = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(project).strip())
        normalized = "-".join(part for part in normalized.split("-") if part)
        return normalized

    def _reserve_port(self, port: int, owner: str) -> bool:
        lock_path = self._lock_path(port)
        if lock_path.exists() and self._lock_is_stale(lock_path):
            stale_owner = None
            stale_session = None
            stale_pid = None
            try:
                stale_payload = json.loads(lock_path.read_text(encoding="utf-8"))
                if isinstance(stale_payload, dict):
                    stale_owner = stale_payload.get("owner")
                    stale_session = stale_payload.get("session")
                    stale_pid = stale_payload.get("pid")
            except (OSError, json.JSONDecodeError):
                stale_owner = None
                stale_session = None
                stale_pid = None
            lock_path.unlink(missing_ok=True)
            self._emit(
                "port.lock.reclaim",
                port=port,
                owner=owner,
                session=self.session_id,
                reclaimed_owner=stale_owner,
                reclaimed_session=stale_session,
                reclaimed_pid=stale_pid,
            )
        if lock_path.exists():
            return False

        if not self._is_port_available(port):
            return False

        payload = {
            "owner": owner,
            "session": self.session_id,
            "pid": self.session_pid,
            "created_at": self.time_provider(),
        }
        try:
            fd = lock_path.open("x", encoding="utf-8")
        except FileExistsError:
            return False
        with fd:
            fd.write(json.dumps(payload, sort_keys=True))
        self._emit("port.lock.acquire", port=port, owner=owner, session=self.session_id)
        return True

    def _lock_is_stale(self, lock_path: Path) -> bool:
        try:
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True

        pid = payload.get("pid")
        if isinstance(pid, int) and pid > 0:
            if self._pid_is_running(pid):
                return False
            return True

        created_at_raw = payload.get("created_at")
        if created_at_raw is None:
            return False
        created_at = self._parse_created_at(created_at_raw)
        if created_at is None:
            return True
        return (self.time_provider() - created_at) > self.stale_lock_seconds

    def _pid_is_running(self, pid: int) -> bool:
        if self.pid_checker is not None:
            return self.pid_checker(pid)
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _parse_created_at(self, value: object) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if not isinstance(value, str):
            return None
        try:
            return float(value)
        except ValueError:
            pass
        iso = value
        if iso.endswith("Z"):
            iso = iso[:-1] + "+00:00"
        try:
            from datetime import datetime

            return datetime.fromisoformat(iso).timestamp()
        except ValueError:
            return None

    def _is_port_available(self, port: int) -> bool:
        if port <= 0:
            return False
        if self.availability_checker is not None:
            return self.availability_checker(port)
        mode = self.availability_mode
        if mode == "lock_only":
            return True
        if mode == "listener_query":
            return self._is_port_available_via_listener_query(port)
        if mode == "socket_bind":
            return self._is_port_available_via_socket_bind(port, allow_permission_fallback=False)
        if mode == "auto":
            return self._is_port_available_via_socket_bind(port, allow_permission_fallback=True)
        return self._is_port_available_via_socket_bind(port, allow_permission_fallback=True)

    def _is_port_available_via_socket_bind(self, port: int, *, allow_permission_fallback: bool = True) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except PermissionError:
                if allow_permission_fallback:
                    return self._is_port_available_via_listener_query(port)
                return False
            except OSError:
                return False
        return True

    def _is_port_available_via_listener_query(self, port: int) -> bool:
        lsof_bin = shutil.which("lsof")
        if lsof_bin is None:
            # In heavily sandboxed environments listener probes may be unavailable; prefer lock ownership.
            return True
        completed = subprocess.run(
            [lsof_bin, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode == 0:
            return not bool(completed.stdout.strip())
        # lsof returns non-zero when no matches exist.
        return True

    def _emit(self, event_name: str, **payload: object) -> None:
        if self.event_handler is None:
            return
        self.event_handler(event_name, payload)

    @staticmethod
    def _port_from_lock_path(lock_path: Path) -> int | None:
        stem = lock_path.stem
        try:
            return int(stem)
        except ValueError:
            return None
