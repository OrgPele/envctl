from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import shutil
import socket
import subprocess
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final
from typing import Callable

from envctl_engine.state.models import PortPlan
from envctl_engine.state.persistence import advisory_file_lock, fsync_directory


_CORE_SERVICE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "backend",
        "frontend",
        "db",
        "redis",
        "n8n",
        "supabase_api",
    }
)

_PORT_GUARD_SHARDS: Final[int] = 64
# ``flock`` behavior for separate descriptors in one process differs across
# platforms. A bounded in-process stripe set makes the contract explicit while
# the on-disk guard shards serialize independent processes.
_PORT_THREAD_GUARDS: Final[tuple[threading.RLock, ...]] = tuple(threading.RLock() for _ in range(_PORT_GUARD_SHARDS))


class PortPlanner:
    def __init__(
        self,
        backend_base: int = 8000,
        frontend_base: int = 9000,
        spacing: int = 20,
        db_base: int = 5432,
        redis_base: int = 6379,
        n8n_base: int = 5678,
        supabase_api_base: int = 54321,
        additional_service_bases: dict[str, int] | None = None,
        lock_dir: str | None = None,
        session_id: str | None = None,
        stale_lock_seconds: int = 3600,
        corrupt_lock_grace_seconds: float = 1.0,
        availability_checker: Callable[[int], bool] | None = None,
        pid_checker: Callable[[int], bool] | None = None,
        time_provider: Callable[[], float] | None = None,
        event_handler: Callable[[str, dict[str, object]], None] | None = None,
        availability_mode: str = "auto",
        preferred_port_strategy: str = "project_slot",
        scope_key: str | None = None,
        dynamic_main_dependency_ports: bool = False,
    ) -> None:
        self.backend_base = backend_base
        self.frontend_base = frontend_base
        self.spacing = spacing
        self.db_base = db_base
        self.redis_base = redis_base
        self.n8n_base = n8n_base
        self.supabase_api_base = supabase_api_base
        self.additional_service_bases = self._normalized_additional_service_bases(additional_service_bases or {})
        self.lock_dir = Path(lock_dir or "/tmp/envctl-python-locks")
        self._ensure_real_directory(self.lock_dir)
        self.session_id = session_id or f"session-{uuid.uuid4().hex[:8]}"
        self.session_pid = os.getpid()
        self.stale_lock_seconds = max(stale_lock_seconds, 0)
        self.corrupt_lock_grace_seconds = max(float(corrupt_lock_grace_seconds), 0.0)
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
        self.dynamic_main_dependency_ports = bool(dynamic_main_dependency_ports)
        self.max_port: Final[int] = 65000
        self._guard_dir = self.lock_dir / ".port-guards"
        self._thread_guard_namespace = str(self.lock_dir.resolve(strict=False))

    def plan_project(
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
        backend_requested = self._requested_port(
            project,
            "backend",
            self.backend_base,
            index=index,
            requested=requested,
        )
        frontend_requested = self._requested_port(
            project,
            "frontend",
            self.frontend_base,
            index=index,
            requested=requested,
        )
        return {
            "backend": self._plan(
                project=project,
                service_name="backend",
                requested_port=backend_requested,
                sources=sources,
                retries=retries,
                default_source="env",
            ),
            "frontend": self._plan(
                project=project,
                service_name="frontend",
                requested_port=frontend_requested,
                sources=sources,
                retries=retries,
                default_source="env",
            ),
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
        for service_name, base_port in (
            ("db", self.db_base),
            ("redis", self.redis_base),
            ("n8n", self.n8n_base),
            ("supabase_api", self.supabase_api_base),
        ):
            requested_port = self._requested_dependency_port(
                project,
                service_name,
                base_port,
                index=index,
                requested=requested,
            )
            plans[service_name] = self._plan(
                project=project,
                service_name=service_name,
                requested_port=requested_port,
                sources=sources,
                retries=retries,
                default_source="planner",
            )
        for service_name, base_port in self.additional_service_bases.items():
            requested_port = self._requested_port(
                project,
                service_name,
                base_port,
                index=index,
                requested=requested,
            )
            plans[service_name] = self._plan(
                project=project,
                service_name=service_name,
                requested_port=requested_port,
                sources=sources,
                retries=retries,
                default_source="planner",
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
        with self._port_guard(port):
            payload = self._read_lock_payload(lock_path)
            if payload is None or payload.get("session") != self.session_id:
                return
            if owner is not None and payload.get("owner") != owner:
                return
            lock_path.unlink(missing_ok=True)
            self._emit("port.lock.release", port=port, owner=owner, session=self.session_id)

    def release_owned(self, port: int, owner: str, *, expected_session: str) -> bool:
        """Release an exact logical owner from one persisted planner session."""

        normalized_session = expected_session.strip() if isinstance(expected_session, str) else ""
        if not normalized_session:
            return False

        lock_path = self._lock_path(port)
        with self._port_guard(port):
            payload = self._read_lock_payload(lock_path)
            if payload is None or payload.get("owner") != owner or payload.get("session") != normalized_session:
                return False
            lock_path.unlink(missing_ok=True)
            self._emit("port.lock.release", port=port, owner=owner, session=normalized_session)
            return True

    def reap_stale(self, port: int, owner: str | None = None) -> bool:
        """Remove one proven-stale reservation without touching a live foreign session."""

        lock_path = self._lock_path(port)
        with self._port_guard(port):
            if not lock_path.exists() or not self._lock_is_stale(lock_path):
                return False
            payload = self._read_lock_payload(lock_path)
            if owner is not None and payload is not None and payload.get("owner") != owner:
                return False
            lock_path.unlink(missing_ok=True)
            self._emit_reclaim(port=port, owner=owner, payload=payload)
            return True

    def reap_stale_locks(self) -> int:
        """Reap every proven-stale numeric reservation in this repository scope."""

        reaped = 0
        for lock_path in tuple(self.lock_dir.glob("*.lock")):
            port = self._port_from_lock_path(lock_path)
            if port is not None and self.reap_stale(port):
                reaped += 1
        return reaped

    def release_session(self) -> None:
        for lock_path in self.lock_dir.glob("*.lock"):
            port = self._port_from_lock_path(lock_path)
            if port is None:
                continue
            with self._port_guard(port):
                payload = self._read_lock_payload(lock_path)
                if payload is None or payload.get("session") != self.session_id:
                    continue
                lock_path.unlink(missing_ok=True)
                self._emit("port.lock.release", port=port, owner=payload.get("owner"), session=self.session_id)

    def release_all(self) -> None:
        for lock_path in self.lock_dir.glob("*.lock"):
            port = self._port_from_lock_path(lock_path)
            if port is None:
                lock_path.unlink(missing_ok=True)
                continue
            with self._port_guard(port):
                payload = self._read_lock_payload(lock_path)
                lock_path.unlink(missing_ok=True)
                self._emit(
                    "port.lock.release",
                    port=port,
                    owner=payload.get("owner") if payload is not None else None,
                    session=self.session_id,
                )

    def _lock_path(self, port: int) -> Path:
        return self.lock_dir / f"{port}.lock"

    @staticmethod
    def _normalized_additional_service_bases(raw_bases: dict[str, int]) -> dict[str, int]:
        bases: dict[str, int] = {}
        for raw_name, raw_port in raw_bases.items():
            service_name = str(raw_name).strip().lower()
            base_port = int(raw_port)
            if not service_name or service_name in _CORE_SERVICE_NAMES or base_port <= 0:
                continue
            bases[service_name] = base_port
        return bases

    def _plan(
        self,
        *,
        project: str,
        service_name: str,
        requested_port: int,
        sources: dict[str, str],
        retries: dict[str, int],
        default_source: str,
    ) -> PortPlan:
        return PortPlan(
            project=project,
            requested=requested_port,
            assigned=requested_port,
            final=requested_port,
            source=sources.get(service_name, default_source),
            retries=retries.get(service_name, 0),
        )

    def _requested_port(
        self,
        project: str,
        service_name: str,
        base: int,
        *,
        index: int,
        requested: dict[str, int],
    ) -> int:
        return requested.get(service_name, self._preferred_port(project, service_name, base, index=index))

    def _requested_dependency_port(
        self,
        project: str,
        service_name: str,
        base: int,
        *,
        index: int,
        requested: dict[str, int],
    ) -> int:
        return requested.get(
            service_name,
            self._preferred_dependency_port(project, service_name, base, index=index),
        )

    def _preferred_port(self, project: str, service_name: str, base: int, *, index: int) -> int:
        if self.preferred_port_strategy == "legacy_spacing":
            if service_name in {"backend", "frontend"}:
                return base + (index * self.spacing)
            return base + index
        slot = self._project_slot(project)
        return base + slot

    def _preferred_dependency_port(self, project: str, service_name: str, base: int, *, index: int) -> int:
        if self._dynamic_main_dependency_ports_enabled(project):
            return base + self._main_dependency_session_slot()
        return self._preferred_port(project, service_name, base, index=index)

    def _project_slot(self, project: str) -> int:
        normalized = self._normalize_project_identity(project)
        if normalized in {"", "main"}:
            return 0
        span = self._project_slot_span()
        digest = hashlib.sha1(f"{self.scope_key}:{normalized}".encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % span

    def _dynamic_main_dependency_ports_enabled(self, project: str) -> bool:
        if not self.dynamic_main_dependency_ports:
            return False
        normalized = self._normalize_project_identity(project)
        return normalized in {"", "main"}

    def _main_dependency_session_slot(self) -> int:
        span = self._project_slot_span()
        if span <= 1:
            return 0
        digest = hashlib.sha1(f"{self.scope_key}:{self.session_id}:main-dependencies".encode("utf-8")).hexdigest()
        slot = int(digest[:8], 16) % span
        # Keep envctl-managed Main dependencies off the well-known base ports
        # while still staying inside the configured service port bands.
        return slot or 1

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
        with self._port_guard(port):
            availability_confirmed = False
            if lock_path.exists():
                if not self._lock_is_stale(lock_path):
                    return False
                stale_payload = self._read_lock_payload(lock_path)
                if stale_payload is None or stale_payload.get("owner") != owner:
                    # A targeted startup may reclaim a dead allocator session
                    # only for the same logical project/service. A dead or
                    # corrupt foreign lock is still durable ownership evidence
                    # and requires an explicit all-scope cleanup operation.
                    return False
                # The allocator process recorded in an otherwise stale lock
                # can exit while its launched service is still listening. Do
                # not erase that last ownership record merely because the
                # allocator PID is gone.
                if not self._is_port_available(port):
                    return False
                availability_confirmed = True
                lock_path.unlink(missing_ok=True)
                self._emit_reclaim(port=port, owner=owner, payload=stale_payload)

            if not availability_confirmed and not self._is_port_available(port):
                return False

            payload = {
                "owner": owner,
                "session": self.session_id,
                "pid": self.session_pid,
                "created_at": self.time_provider(),
            }
            if not self._publish_lock(lock_path, payload, port=port):
                return False
            self._emit("port.lock.acquire", port=port, owner=owner, session=self.session_id)
            return True

    def _lock_is_stale(self, lock_path: Path) -> bool:
        payload = self._read_lock_payload(lock_path)
        if payload is None:
            return self._corrupt_lock_is_stale(lock_path)

        pid = payload.get("pid")
        if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0:
            if self._pid_is_running(pid):
                return False
            return True

        created_at_raw = payload.get("created_at")
        if created_at_raw is None:
            return self._corrupt_lock_is_stale(lock_path)
        created_at = self._parse_created_at(created_at_raw)
        if created_at is None:
            return self._corrupt_lock_is_stale(lock_path)
        return (self.time_provider() - created_at) > self.stale_lock_seconds

    def _pid_is_running(self, pid: int) -> bool:
        if self.pid_checker is not None:
            try:
                return bool(self.pid_checker(pid))
            except Exception:  # noqa: BLE001 - an inconclusive probe must preserve a foreign lock
                return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError as exc:
            return exc.errno != errno.ESRCH
        return True

    def _corrupt_lock_is_stale(self, lock_path: Path) -> bool:
        try:
            modified_at = lock_path.stat().st_mtime
        except FileNotFoundError:
            return True
        except OSError:
            return False
        return (self.time_provider() - modified_at) >= self.corrupt_lock_grace_seconds

    @staticmethod
    def _read_lock_payload(lock_path: Path) -> dict[str, object] | None:
        try:
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _publish_lock(self, lock_path: Path, payload: dict[str, object], *, port: int) -> bool:
        """Publish a complete payload without ever exposing an empty lock path."""

        self._ensure_real_directory(self._guard_dir)
        pending_path = self._guard_dir / f"{self._guard_shard(port):02x}.pending"
        pending_path.unlink(missing_ok=True)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(pending_path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as pending_file:
                pending_file.write(json.dumps(payload, sort_keys=True))
                pending_file.flush()
                os.fsync(pending_file.fileno())
            try:
                os.link(pending_path, lock_path)
            except FileExistsError:
                return False
            fsync_directory(self.lock_dir)
            return True
        finally:
            pending_path.unlink(missing_ok=True)

    def _emit_reclaim(self, *, port: int, owner: str | None, payload: dict[str, object] | None) -> None:
        payload = payload or {}
        self._emit(
            "port.lock.reclaim",
            port=port,
            owner=owner,
            session=self.session_id,
            reclaimed_owner=payload.get("owner"),
            reclaimed_session=payload.get("session"),
            reclaimed_pid=payload.get("pid"),
        )

    @contextmanager
    def _port_guard(self, port: int) -> Iterator[None]:
        shard = self._guard_shard(port)
        self._ensure_real_directory(self._guard_dir)
        guard_path = self._guard_dir / f"{shard:02x}.guard"
        thread_key = f"{self._thread_guard_namespace}:{shard}".encode("utf-8")
        thread_index = int(hashlib.sha1(thread_key).hexdigest()[:8], 16) % len(_PORT_THREAD_GUARDS)
        with _PORT_THREAD_GUARDS[thread_index]:
            with advisory_file_lock(guard_path, exclusive=True):
                yield

    @staticmethod
    def _guard_shard(port: int) -> int:
        return int(port) % _PORT_GUARD_SHARDS

    @staticmethod
    def _ensure_real_directory(path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            pass
        if path.is_symlink() or not path.is_dir():
            raise OSError(f"Port reservation directory is not a real directory: {path}")

    def _parse_created_at(self, value: object) -> float | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parsed = float(value)
            return parsed if math.isfinite(parsed) else None
        if not isinstance(value, str):
            return None
        try:
            parsed = float(value)
            return parsed if math.isfinite(parsed) else None
        except ValueError:
            pass
        iso = value
        if iso.endswith("Z"):
            iso = iso[:-1] + "+00:00"
        try:
            from datetime import datetime

            parsed = datetime.fromisoformat(iso).timestamp()
            return parsed if math.isfinite(parsed) else None
        except (OverflowError, ValueError):
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
            host_available = self._is_port_available_via_listener_query(port)
            return host_available and self._is_port_available_via_docker_publish_filter(port)
        if mode == "socket_bind":
            host_available = self._is_port_available_via_socket_bind(port, allow_permission_fallback=False)
            return host_available and self._is_port_available_via_docker_publish_filter(port)
        if mode == "auto":
            host_available = self._is_port_available_via_socket_bind(port, allow_permission_fallback=True)
            return host_available and self._is_port_available_via_docker_publish_filter(port)
        host_available = self._is_port_available_via_socket_bind(port, allow_permission_fallback=True)
        return host_available and self._is_port_available_via_docker_publish_filter(port)

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

    def _is_port_available_via_docker_publish_filter(self, port: int) -> bool:
        docker_bin = shutil.which("docker")
        if docker_bin is None:
            return True
        timeout_raw = os.environ.get("ENVCTL_PORT_AVAILABILITY_DOCKER_TIMEOUT_SECONDS")
        try:
            timeout_seconds = max(0.2, float(timeout_raw)) if timeout_raw is not None else 2.0
        except ValueError:
            timeout_seconds = 2.0
        try:
            completed = subprocess.run(
                [
                    docker_bin,
                    "ps",
                    "-a",
                    "--filter",
                    f"publish={port}",
                    "--format",
                    "{{.ID}}",
                ],
                text=True,
                capture_output=True,
                check=False,
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired):
            return True
        if completed.returncode != 0:
            return True
        return not bool(completed.stdout.strip())

    def _emit(self, event_name: str, **payload: object) -> None:
        if self.event_handler is None:
            return
        try:
            self.event_handler(event_name, payload)
        except Exception:  # noqa: BLE001 - telemetry must never change lock ownership
            return

    @staticmethod
    def _port_from_lock_path(lock_path: Path) -> int | None:
        stem = lock_path.stem
        try:
            return int(stem)
        except ValueError:
            return None
