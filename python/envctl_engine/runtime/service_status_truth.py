from __future__ import annotations

from typing import Any

from envctl_engine.shared.process_probe import ShellProbeBackend


def service_truth_status(runtime: Any, service: object) -> str:
    backend = getattr(runtime.process_probe, "backend", None)
    if isinstance(backend, ShellProbeBackend):
        backend.process_runner = runtime.process_runner
    probe = runtime.process_probe
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
        service=service_display_name(service),
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
        service=service_display_name(service),
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


def service_display_name(service: object) -> str:
    return str(getattr(service, "name", getattr(service, "type", "service")))
