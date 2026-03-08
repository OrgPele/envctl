from __future__ import annotations

from pathlib import Path
from typing import Any

from envctl_engine.shared.process_probe import ShellProbeBackend


def command_result_error_text(*, result: object) -> str:
    stderr = str(getattr(result, "stderr", "") or "").strip()
    stdout = str(getattr(result, "stdout", "") or "").strip()
    if stderr:
        return stderr.splitlines()[-1]
    if stdout:
        return stdout.splitlines()[-1]
    return f"exit:{getattr(result, 'returncode', 'unknown')}"


def service_listener_failure_detail(runtime: Any, *, log_path: str | None, pid: int | None) -> str | None:
    parts: list[str] = []
    if isinstance(pid, int) and pid > 0:
        try:
            if not bool(runtime.process_runner.is_pid_running(pid)):
                parts.append(f"process {pid} exited")
        except Exception:  # noqa: BLE001
            pass
    if isinstance(log_path, str) and log_path.strip():
        parts.append(f"log_path: {log_path}")
    log_hint = tail_log_error_line(log_path)
    if log_hint:
        parts.append(f"log: {log_hint}")
    if not parts:
        return None
    return "; ".join(parts)


def tail_log_error_line(log_path: str | None, *, max_chars: int = 240) -> str | None:
    if not log_path:
        return None
    path = Path(log_path)
    if not path.is_file():
        return None
    try:
        lines = [line.strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    except OSError:
        return None
    if not lines:
        return None

    priority_tokens = (
        "ModuleNotFoundError",
        "ImportError",
        "Traceback",
        "ERROR",
        "Error",
        "Exception",
        "No module named",
    )
    selected = lines[-1]
    for line in reversed(lines):
        if any(token in line for token in priority_tokens):
            selected = line
            break
    if len(selected) > max_chars:
        return selected[: max_chars - 3] + "..."
    return selected


def wait_for_service_listener(
    runtime: Any,
    pid: int,
    port: int,
    *,
    service_name: str,
    debug_listener_group: str = "",
    debug_pid_wait_group: str = "",
) -> bool:
    timeout = runtime._service_listener_timeout()
    if debug_listener_group in {"", "pid_wait"}:
        try:
            if bool(
                runtime.process_runner.wait_for_pid_port(
                    pid,
                    port,
                    timeout=timeout,
                    debug_pid_wait_group=debug_pid_wait_group,
                )
            ):
                return True
        except Exception:  # noqa: BLE001
            pass
    if debug_listener_group in {"", "port_fallback"} and service_truth_fallback_enabled(runtime) and bool(
        runtime.process_runner.wait_for_port(port, timeout=timeout)
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


def detect_service_actual_port(
    runtime: Any,
    *,
    pid: int | None,
    requested_port: int,
    service_name: str,
    debug_listener_group: str = "",
    debug_pid_wait_group: str = "",
) -> int | None:
    if not isinstance(pid, int) or pid <= 0 or requested_port <= 0:
        return None
    if wait_for_service_listener(
        runtime,
        pid,
        requested_port,
        service_name=service_name,
        debug_listener_group=debug_listener_group,
        debug_pid_wait_group=debug_pid_wait_group,
    ):
        return requested_port
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


def service_truth_status(runtime: Any, service: object) -> str:
    backend = getattr(runtime.process_probe, "backend", None)
    if isinstance(backend, ShellProbeBackend):
        backend.process_runner = runtime.process_runner
    probe = runtime.process_probe
    debug_truth_group = str(getattr(runtime, "_debug_dashboard_truth_group", "") or "").strip().lower()
    if debug_truth_group not in {"", "pid_wait", "port_fallback", "truth_discovery"}:
        debug_truth_group = ""
    if not debug_truth_group:
        debug_truth_group = str(getattr(runtime, "_debug_poststart_truth_group", "") or "").strip().lower()
        if debug_truth_group not in {"", "pid_wait", "port_fallback", "truth_discovery"}:
            debug_truth_group = ""
    setattr(probe, "_debug_poststart_truth_group", debug_truth_group)
    status = probe.service_truth_status(
        service=service,
        listener_truth_enforced=runtime._listener_truth_enforced(),
        service_truth_timeout=runtime._service_truth_timeout(),
        within_startup_grace=runtime._service_within_startup_grace,
        truth_discovery=runtime._service_truth_discovery,
        clear_listener_pids=runtime._clear_service_listener_pids,
        refresh_listener_pids=runtime._refresh_service_listener_pids,
        emit=runtime._emit,
        fallback_enabled=runtime._service_truth_fallback_enabled(),
        rebind_stale=runtime._rebind_stale_service_pid,
    )
    runtime._emit(
        "service.truth.check",
        service=str(getattr(service, "name", getattr(service, "type", "service"))),
        status=status,
        reason_code=f"truth_status_{status}",
    )
    return status


def rebind_stale_service_pid(runtime: Any, service: object, *, previous_pid: int | None) -> bool:
    if runtime.config.runtime_truth_mode == "strict":
        return False
    if not runtime._listener_truth_enforced():
        return False

    port = runtime._service_port(service)
    if not isinstance(port, int) or port <= 0:
        return False

    timeout = runtime._service_truth_timeout()
    try:
        if not bool(runtime.process_runner.wait_for_port(port, timeout=timeout)):
            return False
    except Exception:  # noqa: BLE001
        return False

    listener_pids = listener_pids_for_port(runtime, port)
    next_pid = listener_pids[0] if listener_pids else None
    if isinstance(next_pid, int) and next_pid > 0 and hasattr(service, "pid"):
        setattr(service, "pid", next_pid)
    if hasattr(service, "listener_pids"):
        setattr(service, "listener_pids", listener_pids or None)

    runtime._emit(
        "service.rebind.pid",
        service=str(getattr(service, "name", getattr(service, "type", "service"))),
        previous_pid=previous_pid,
        rebound_pid=next_pid,
        port=port,
    )
    return True


def listener_pids_for_port(runtime: Any, port: int) -> list[int]:
    if port <= 0:
        return []
    try:
        resolved = runtime.process_runner.listener_pids_for_port(port)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(resolved, list):
        return []
    return sorted({int(value) for value in resolved if isinstance(value, int) and value > 0})


def service_truth_discovery(runtime: Any, service: object, port: int) -> int | None:
    pid = getattr(service, "pid", None)
    if not isinstance(pid, int) or pid <= 0:
        return None
    max_delta = runtime._service_rebound_max_delta()
    try:
        discovered = runtime.process_runner.find_pid_listener_port(pid, port, max_delta=max_delta)
    except Exception:  # noqa: BLE001
        discovered = None
    if not isinstance(discovered, int) or discovered <= 0:
        return None
    if getattr(service, "actual_port", None) != discovered and hasattr(service, "actual_port"):
        setattr(service, "actual_port", discovered)
    return discovered


def refresh_service_listener_pids(runtime: Any, service: object, *, port: int) -> None:
    pid = getattr(service, "pid", None)
    if not isinstance(pid, int) or pid <= 0:
        clear_service_listener_pids(service)
        return
    try:
        listener_pids = runtime.process_runner.process_tree_listener_pids(pid, port=port)
    except TypeError:
        try:
            listener_pids = runtime.process_runner.process_tree_listener_pids(pid, port)  # pyright: ignore[reportCallIssue]
        except Exception:  # noqa: BLE001
            listener_pids = []
    except Exception:  # noqa: BLE001
        listener_pids = []
    if not isinstance(listener_pids, list):
        clear_service_listener_pids(service)
        return
    normalized = sorted({int(value) for value in listener_pids if isinstance(value, int) and value > 0})
    if hasattr(service, "listener_pids"):
        setattr(service, "listener_pids", normalized or None)


def clear_service_listener_pids(service: object) -> None:
    if hasattr(service, "listener_pids"):
        setattr(service, "listener_pids", None)


def assert_project_services_post_start_truth(
    runtime: Any,
    *,
    context: Any,
    services: dict[str, object] | Any,
) -> None:
    if not runtime._listener_truth_enforced():
        return
    for service in services.values():
        status = service_truth_status(runtime, service)
        if hasattr(service, "status"):
            setattr(service, "status", status)
        if status in {"running", "simulated"}:
            continue

        service_name = str(getattr(service, "type", "service") or "service")
        pid = getattr(service, "pid", None)
        log_path = getattr(service, "log_path", None)
        detail = service_listener_failure_detail(
            runtime,
            log_path=log_path if isinstance(log_path, str) else None,
            pid=pid if isinstance(pid, int) else None,
        )
        port = runtime._service_port(service)
        runtime._emit(
            "service.failure",
            project=context.name,
            service=service_name,
            failure_class="post_start_truth_check",
            status=status,
            port=port,
            detail=detail,
        )
        port_label = str(port) if isinstance(port, int) and port > 0 else "n/a"
        suffix = f" ({detail})" if detail else ""
        raise RuntimeError(
            f"{service_name} became {status} after startup for {context.name} on port {port_label}{suffix}"
        )
