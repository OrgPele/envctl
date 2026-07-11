from __future__ import annotations

import time
import urllib.error
import urllib.request
from typing import Any

from envctl_engine.runtime.service_truth_diagnostics import tail_log_startup_progress_line


HTTP_READINESS_PATHS = ("/api/v1/health", "/health", "/readyz", "/healthz", "/")


def wait_for_service_listener(
    runtime: Any,
    pid: int,
    port: int,
    *,
    service_name: str,
    debug_listener_group: str = "",
    debug_pid_wait_group: str = "",
    timeout: float | None = None,
) -> bool:
    listener_timeout = runtime._service_listener_timeout() if timeout is None else max(float(timeout), 0.0)
    if debug_listener_group in {"", "pid_wait"}:
        try:
            if bool(
                runtime.process_runner.wait_for_pid_port(
                    pid,
                    port,
                    timeout=listener_timeout,
                    debug_pid_wait_group=debug_pid_wait_group,
                )
            ):
                return True
        except Exception:  # noqa: BLE001
            pass
    # A generic port probe is only a safe fallback while the process envctl
    # launched is still alive. Once that PID has exited, waiting on the port can
    # hide the real startup error for minutes and can adopt an unrelated process
    # that happens to bind the same port later.
    if _launch_pid_definitively_exited(runtime, pid):
        return False
    if (
        debug_listener_group in {"", "port_fallback"}
        and service_truth_fallback_enabled(runtime)
        and bool(runtime.process_runner.wait_for_port(port, timeout=listener_timeout))
    ):
        runtime._emit(
            "service.bind.port_fallback",
            service=service_name,
            pid=pid,
            port=port,
            reason_code="startup_pid_port_probe_failed_port_probe_recovered",
        )
        return True
    return False


def _launch_pid_definitively_exited(runtime: Any, pid: int) -> bool:
    checker = getattr(runtime.process_runner, "is_pid_running", None)
    if not callable(checker):
        return False
    try:
        return not bool(checker(pid))
    except Exception:  # noqa: BLE001
        return False


def process_tree_probe_supported(runtime: Any) -> bool:
    try:
        return bool(runtime.process_runner.supports_process_tree_probe())
    except Exception:  # noqa: BLE001
        return False


def service_truth_fallback_enabled(runtime: Any) -> bool:
    if runtime.config.runtime_truth_mode == "strict":
        return False
    if runtime.config.runtime_truth_mode == "best_effort":
        return True
    return (not runtime._listener_probe_supported) or (not process_tree_probe_supported(runtime))


def service_startup_progress_timeout(runtime: Any) -> float:
    resolver = getattr(runtime, "_service_startup_progress_timeout", None)
    if not callable(resolver):
        return 0.0
    try:
        raw = resolver()
        if isinstance(raw, int | float | str):
            return max(float(raw), 0.0)
        return 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def emit_service_startup_progress_once(
    runtime: Any,
    *,
    service_name: str,
    pid: int,
    port: int,
    progress_line: str,
    emitted_progress_lines: set[str],
) -> None:
    if progress_line in emitted_progress_lines:
        return
    emitted_progress_lines.add(progress_line)
    runtime._emit(
        "service.startup.progress",
        service=service_name,
        pid=pid,
        port=port,
        log=progress_line,
    )


def emit_service_startup_progress_timeout(
    runtime: Any,
    *,
    service_name: str,
    pid: int,
    port: int,
    progress_line: str,
) -> None:
    runtime._emit(
        "service.startup.progress.timeout",
        service=service_name,
        pid=pid,
        port=port,
        log=progress_line,
    )


def emit_service_startup_progress_listener_accepted(
    runtime: Any,
    *,
    service_name: str,
    pid: int,
    port: int,
    progress_line: str,
) -> None:
    runtime._emit(
        "service.startup.progress.listener_accepted",
        service=service_name,
        pid=pid,
        port=port,
        log=progress_line,
    )


def emit_service_startup_progress_http_ready(
    runtime: Any,
    *,
    service_name: str,
    pid: int,
    port: int,
    progress_line: str,
    health_path: str,
) -> None:
    runtime._emit(
        "service.startup.progress.http_ready",
        service=service_name,
        pid=pid,
        port=port,
        log=progress_line,
        health_path=health_path,
    )


def service_http_ready(port: int, *, host: str = "127.0.0.1", timeout: float = 0.2) -> str | None:
    if port <= 0:
        return None
    for path in HTTP_READINESS_PATHS:
        url = f"http://{host}:{port}{path}"
        request = urllib.request.Request(url, headers={"User-Agent": "envctl-readiness-probe"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - local readiness probe.
                status = int(getattr(response, "status", response.getcode()))
        except urllib.error.HTTPError as exc:
            status = int(getattr(exc, "code", 0) or 0)
        except (OSError, TimeoutError, ValueError, urllib.error.URLError):
            continue
        if 200 <= status < 400:
            return path
    return None


def detect_service_actual_port(
    runtime: Any,
    *,
    pid: int | None,
    requested_port: int,
    service_name: str,
    debug_listener_group: str = "",
    debug_pid_wait_group: str = "",
    log_path: str | None = None,
) -> int | None:
    if not isinstance(pid, int) or pid <= 0 or requested_port <= 0:
        return None
    progress_deadline = time.monotonic() + service_startup_progress_timeout(runtime)
    emitted_progress_lines: set[str] = set()
    while True:
        if wait_for_service_listener(
            runtime,
            pid,
            requested_port,
            service_name=service_name,
            debug_listener_group=debug_listener_group,
            debug_pid_wait_group=debug_pid_wait_group,
        ):
            progress_line = tail_log_startup_progress_line(log_path)
            if not progress_line:
                return requested_port
            health_path = service_http_ready(requested_port)
            if health_path is not None:
                emit_service_startup_progress_http_ready(
                    runtime,
                    service_name=service_name,
                    pid=pid,
                    port=requested_port,
                    progress_line=progress_line,
                    health_path=health_path,
                )
                return requested_port
            if time.monotonic() >= progress_deadline:
                emit_service_startup_progress_listener_accepted(
                    runtime,
                    service_name=service_name,
                    pid=pid,
                    port=requested_port,
                    progress_line=progress_line,
                )
                return requested_port
            emit_service_startup_progress_once(
                runtime,
                service_name=service_name,
                pid=pid,
                port=requested_port,
                progress_line=progress_line,
                emitted_progress_lines=emitted_progress_lines,
            )
            time.sleep(min(max(runtime._service_listener_timeout(), 0.05), 1.0))
            continue
        progress_line = tail_log_startup_progress_line(log_path)
        if not progress_line or time.monotonic() >= progress_deadline:
            if progress_line:
                emit_service_startup_progress_timeout(
                    runtime,
                    service_name=service_name,
                    pid=pid,
                    port=requested_port,
                    progress_line=progress_line,
                )
                return None
            break
        emit_service_startup_progress_once(
            runtime,
            service_name=service_name,
            pid=pid,
            port=requested_port,
            progress_line=progress_line,
            emitted_progress_lines=emitted_progress_lines,
        )
        time.sleep(min(max(runtime._service_listener_timeout(), 0.05), 1.0))
    if debug_listener_group not in {"", "rebound_discovery"}:
        return None
    max_delta = runtime._service_rebound_max_delta()
    try:
        discovered = runtime.process_runner.find_pid_listener_port(pid, requested_port, max_delta=max_delta)
    except Exception:  # noqa: BLE001
        discovered = None
    if isinstance(discovered, int) and discovered > 0:
        runtime._emit(
            "service.bind.actual.discovered",
            service=service_name,
            pid=pid,
            requested_port=requested_port,
            discovered_port=discovered,
        )
        return discovered
    return None
