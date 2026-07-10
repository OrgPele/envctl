from __future__ import annotations

from collections.abc import Callable, Sequence
import concurrent.futures
from pathlib import Path
import re

from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.ui.path_links import render_paths_in_terminal_text


LOG_ISSUE_RE = re.compile(
    r"\b("
    r"no module named|"
    r"error(?:s|_[a-z_]+)?|"
    r"failed|failure|"
    r"exception|traceback|"
    r"validationerror|attributeerror|modulenotfounderror|importerror|runtimeerror|"
    r"critical|fatal|"
    r"warn(?:ing)?|deprecated"
    r")\b",
    re.IGNORECASE,
)
LOG_ISSUE_SCAN_MAX_BYTES = 512 * 1024
DEFAULT_LOG_ISSUE_LIMIT = 20


class StateActionLogSupport:
    def __init__(self, *, normalize_log_line: Callable[[str, bool], str]) -> None:
        self._normalize_log_line = normalize_log_line

    def errors_payload(
        self,
        *,
        state: RunState,
        failed_services: Sequence[ServiceRecord],
        requirement_issues: list[dict[str, object]],
        recent_failures: list[str],
        log_issues: list[dict[str, object]],
        selected_services: set[str] | None,
    ) -> dict[str, object]:
        return {
            "run_id": state.run_id,
            "mode": state.mode,
            "selected_services": sorted(selected_services) if isinstance(selected_services, set) else None,
            "failed_services": self.parallel_service_map(list(failed_services), self.failed_service_payload),
            "requirement_issues": requirement_issues,
            "recent_failures": list(recent_failures),
            "log_issues": log_issues,
            "ok": not failed_services and not requirement_issues and not recent_failures and not log_issues,
        }

    def logs_payload(
        self,
        *,
        state: RunState,
        tail: int,
        follow: bool,
        duration_seconds: float | None,
        no_color: bool,
    ) -> dict[str, object]:
        snapshots = self.parallel_service_map(
            list(state.services.values()),
            lambda service: self.log_snapshot(service, tail=tail, no_color=no_color),
        )
        return {
            "run_id": state.run_id,
            "mode": state.mode,
            "tail": tail,
            "follow_requested": follow,
            "duration_seconds": duration_seconds,
            "streaming": False,
            "services": snapshots,
        }

    def clear_logs_payload(
        self,
        *,
        state: RunState,
        cleared: int,
        missing: int,
        unavailable: int,
        failed: int,
    ) -> dict[str, object]:
        snapshots = self.parallel_service_map(
            list(state.services.values()),
            self.clear_log_snapshot,
        )
        return {
            "run_id": state.run_id,
            "mode": state.mode,
            "summary": {
                "cleared": cleared,
                "missing": missing,
                "unavailable": unavailable,
                "failed": failed,
            },
            "services": snapshots,
            "ok": failed == 0,
        }

    def service_log_issues(self, state: RunState, *, max_matches: int) -> list[dict[str, object]]:
        if max_matches <= 0:
            return []
        snapshots = self.parallel_service_map(
            list(state.services.values()),
            lambda service: self.service_log_issue_snapshot(service, max_matches=max_matches),
        )
        return [snapshot for snapshot in snapshots if snapshot.get("lines")]

    def service_log_issue_snapshot(self, service: ServiceRecord, *, max_matches: int) -> dict[str, object]:
        log_path_raw = str(service.log_path or "").strip()
        payload: dict[str, object] = {
            "service": service.name,
            "status": service.status or "unknown",
            "log_path": log_path_raw or None,
            "lines": [],
        }
        if not log_path_raw:
            return payload
        log_path = Path(log_path_raw)
        if not log_path.is_file():
            return payload
        lines = self.read_recent_log_lines(log_path, max_bytes=LOG_ISSUE_SCAN_MAX_BYTES)
        matches = [line for line in lines if self.log_line_has_issue(line)]
        payload["lines"] = matches[-max_matches:]
        return payload

    @staticmethod
    def read_recent_log_lines(log_path: Path, *, max_bytes: int) -> list[str]:
        try:
            size = log_path.stat().st_size
            with log_path.open("rb") as handle:
                if size > max_bytes:
                    handle.seek(size - max_bytes)
                    handle.readline()
                data = handle.read(max_bytes)
        except OSError:
            return []
        return data.decode("utf-8", errors="replace").splitlines()

    @staticmethod
    def log_line_has_issue(line: str) -> bool:
        plain = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", line)
        return LOG_ISSUE_RE.search(plain) is not None

    def log_snapshot(self, service: object, *, tail: int, no_color: bool) -> dict[str, object]:
        log_path_raw = str(getattr(service, "log_path", "") or "").strip()
        payload: dict[str, object] = {
            "name": str(getattr(service, "name", "")),
            "status": str(getattr(service, "status", "") or "unknown"),
            "log_path": log_path_raw or None,
            "exists": False,
            "tail_lines": [],
        }
        if not log_path_raw:
            payload["reason"] = "unavailable"
            return payload
        log_path = Path(log_path_raw)
        if not log_path.is_file():
            payload["reason"] = "missing"
            return payload
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        payload["exists"] = True
        payload["size_bytes"] = log_path.stat().st_size
        payload["tail_lines"] = [self._normalize_log_line(line, no_color) for line in lines[-tail:]]
        return payload

    def clear_log_snapshot(self, service: object) -> dict[str, object]:
        log_path_raw = str(getattr(service, "log_path", "") or "").strip()
        payload: dict[str, object] = {
            "name": str(getattr(service, "name", "")),
            "log_path": log_path_raw or None,
            "status": "unknown",
        }
        if not log_path_raw:
            payload["status"] = "unavailable"
            return payload
        log_path = Path(log_path_raw)
        if not log_path.is_file():
            payload["status"] = "missing"
            return payload
        payload["status"] = "cleared"
        return payload

    @staticmethod
    def failed_service_payload(service: object) -> dict[str, object]:
        return {
            "name": str(getattr(service, "name", "")),
            "status": str(getattr(service, "status", "") or "unknown"),
            "log_path": str(getattr(service, "log_path", "") or "") or None,
        }

    @staticmethod
    def clear_service_logs(
        state: RunState,
        *,
        quiet: bool = False,
        env: dict[str, str] | None = None,
        interactive_tty: bool | None = None,
    ) -> tuple[int, int, int, int]:
        def clear_one(service: ServiceRecord) -> tuple[int, int, int, int, str | None]:
            raw_path = str(getattr(service, "log_path", "") or "").strip()
            if not raw_path:
                return 0, 0, 1, 0, (None if quiet else f"{service.name}: log=n/a")
            log_path = Path(raw_path)
            if not log_path.is_file():
                line = f"{service.name}: log missing at {log_path}"
                return 0, 1, 0, 0, (
                    None
                    if quiet
                    else render_paths_in_terminal_text(
                        line,
                        paths=[log_path],
                        env=env,
                        interactive_tty=interactive_tty,
                    )
                )
            try:
                with log_path.open("w", encoding="utf-8"):
                    pass
                if str(getattr(service, "runtime_kind", "process") or "process").lower() == "docker":
                    Path(f"{log_path}.docker-since").touch()
                line = f"{service.name}: log cleared at {log_path}"
                return 1, 0, 0, 0, (
                    None
                    if quiet
                    else render_paths_in_terminal_text(
                        line,
                        paths=[log_path],
                        env=env,
                        interactive_tty=interactive_tty,
                    )
                )
            except OSError as exc:
                line = f"{service.name}: failed to clear log at {log_path} ({exc})"
                return 0, 0, 0, 1, (
                    None
                    if quiet
                    else render_paths_in_terminal_text(
                        line,
                        paths=[log_path],
                        env=env,
                        interactive_tty=interactive_tty,
                    )
                )

        cleared = 0
        missing = 0
        unavailable = 0
        failed = 0
        services = list(state.services.values())
        worker_count = min(max(len(services), 1), 8)
        if worker_count <= 1:
            results = [clear_one(service) for service in services]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
                results = list(pool.map(clear_one, services))
        for cleared_one, missing_one, unavailable_one, failed_one, line in results:
            cleared += cleared_one
            missing += missing_one
            unavailable += unavailable_one
            failed += failed_one
            if line:
                print(line)
        return cleared, missing, unavailable, failed

    @staticmethod
    def parallel_service_map(
        services: Sequence[ServiceRecord], fn: Callable[[ServiceRecord], dict[str, object]]
    ) -> list[dict[str, object]]:
        if len(services) <= 1:
            return [fn(service) for service in services]
        worker_count = min(len(services), 8)
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
            return list(pool.map(fn, services))

    def _errors_payload(
        self,
        *,
        state: RunState,
        failed_services: Sequence[ServiceRecord],
        requirement_issues: list[dict[str, object]],
        recent_failures: list[str],
        log_issues: list[dict[str, object]],
        selected_services: set[str] | None,
    ) -> dict[str, object]:
        return self.errors_payload(
            state=state,
            failed_services=failed_services,
            requirement_issues=requirement_issues,
            recent_failures=recent_failures,
            log_issues=log_issues,
            selected_services=selected_services,
        )

    def _logs_payload(
        self,
        *,
        state: RunState,
        tail: int,
        follow: bool,
        duration_seconds: float | None,
        no_color: bool,
    ) -> dict[str, object]:
        return self.logs_payload(
            state=state,
            tail=tail,
            follow=follow,
            duration_seconds=duration_seconds,
            no_color=no_color,
        )

    def _clear_logs_payload(
        self,
        *,
        state: RunState,
        cleared: int,
        missing: int,
        unavailable: int,
        failed: int,
    ) -> dict[str, object]:
        return self.clear_logs_payload(
            state=state,
            cleared=cleared,
            missing=missing,
            unavailable=unavailable,
            failed=failed,
        )

    def _service_log_issues(self, state: RunState, *, max_matches: int) -> list[dict[str, object]]:
        return self.service_log_issues(state, max_matches=max_matches)

    def _service_log_issue_snapshot(self, service: ServiceRecord, *, max_matches: int) -> dict[str, object]:
        return self.service_log_issue_snapshot(service, max_matches=max_matches)

    @staticmethod
    def _read_recent_log_lines(log_path: Path, *, max_bytes: int) -> list[str]:
        return StateActionLogSupport.read_recent_log_lines(log_path, max_bytes=max_bytes)

    @staticmethod
    def _log_line_has_issue(line: str) -> bool:
        return StateActionLogSupport.log_line_has_issue(line)

    def _log_snapshot(self, service: object, *, tail: int, no_color: bool) -> dict[str, object]:
        return self.log_snapshot(service, tail=tail, no_color=no_color)

    def _clear_log_snapshot(self, service: object) -> dict[str, object]:
        return self.clear_log_snapshot(service)

    @staticmethod
    def _failed_service_payload(service: object) -> dict[str, object]:
        return StateActionLogSupport.failed_service_payload(service)

    @staticmethod
    def _clear_service_logs(
        state: RunState,
        *,
        quiet: bool = False,
        env: dict[str, str] | None = None,
        interactive_tty: bool | None = None,
    ) -> tuple[int, int, int, int]:
        return StateActionLogSupport.clear_service_logs(
            state,
            quiet=quiet,
            env=env,
            interactive_tty=interactive_tty,
        )

    @staticmethod
    def _parallel_service_map(
        services: Sequence[ServiceRecord],
        fn: Callable[[ServiceRecord], dict[str, object]],
    ) -> list[dict[str, object]]:
        return StateActionLogSupport.parallel_service_map(services, fn)
