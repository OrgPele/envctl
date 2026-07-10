from __future__ import annotations

import concurrent.futures
import os
import signal
from typing import Any


def terminate_started_services(runtime: Any, services: dict[str, object]) -> None:
    for service in services.values():
        runtime._terminate_service_record(service, aggressive=False, verify_ownership=False)


def terminate_services_from_state(
    runtime: Any,
    state: object,
    *,
    selected_services: set[str] | None,
    aggressive: bool,
    verify_ownership: bool,
) -> None:
    work_items: list[tuple[str, object]] = []
    for name, service in getattr(state, "services", {}).items():
        if selected_services is not None and name not in selected_services:
            continue
        work_items.append((name, service))

    def terminate_one(item: tuple[str, object]) -> tuple[str, bool, int | None]:
        name, service = item
        terminated = runtime._terminate_service_record(
            service, aggressive=aggressive, verify_ownership=verify_ownership
        )
        return name, terminated, service_port(service)

    if len(work_items) <= 1:
        results = [terminate_one(item) for item in work_items]
    else:
        worker_count = min(len(work_items), 8)
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
            results = list(pool.map(terminate_one, work_items))

    for _name, terminated, port in results:
        if terminated and port is not None:
            runtime.port_planner.release(port)


def terminate_service_record(runtime: Any, service: object, *, aggressive: bool, verify_ownership: bool) -> bool:
    if str(getattr(service, "runtime_kind", "process") or "process").lower() == "docker":
        from envctl_engine.runtime.docker_service_runtime import DockerServiceRuntime

        container = str(
            getattr(service, "container_id", "") or getattr(service, "container_name", "") or ""
        ).strip()
        stopped = DockerServiceRuntime(runtime, runtime.process_runner).stop(container)
        pid = getattr(service, "pid", None)
        if isinstance(pid, int) and pid > 0:
            try:
                runtime.process_runner.terminate_process_group(
                    pid,
                    term_timeout=0.5 if aggressive else 2.0,
                    kill_timeout=1.0,
                )
            except Exception:  # noqa: BLE001
                pass
        runtime._emit(
            "service.container.stop",
            service=getattr(service, "name", "unknown"),
            container_name=getattr(service, "container_name", None),
            stopped=stopped,
        )
        return stopped
    pid = getattr(service, "pid", None)
    if not isinstance(pid, int) or pid <= 0:
        return True
    if pid in {os.getpid(), os.getppid()}:
        runtime._emit("cleanup.skip", service=getattr(service, "name", "unknown"), pid=pid, reason="self_or_parent")
        return False
    port = service_port(service)
    if verify_ownership:
        if port is None:
            runtime._emit(
                "cleanup.skip",
                service=getattr(service, "name", "unknown"),
                pid=pid,
                reason="missing_port_for_ownership",
            )
            return False
        is_owner = _service_pid_or_listener_owns_port(runtime, service, pid=pid, port=port)
        if not is_owner:
            runtime._emit("cleanup.skip", service=getattr(service, "name", "unknown"), pid=pid, port=port)
            return False

    try:
        terminate_group = getattr(runtime.process_runner, "terminate_process_group", None)
        if callable(terminate_group):
            return bool(terminate_group(pid, term_timeout=0.5 if aggressive else 2.0, kill_timeout=1.0))
    except Exception:  # noqa: BLE001
        pass
    try:
        return bool(runtime.process_runner.terminate(pid, term_timeout=0.5 if aggressive else 2.0, kill_timeout=1.0))
    except Exception:  # noqa: BLE001
        pass
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return True
    return True


def service_port(service: object) -> int | None:
    actual = getattr(service, "actual_port", None)
    if isinstance(actual, int) and actual > 0:
        return actual
    requested = getattr(service, "requested_port", None)
    if isinstance(requested, int) and requested > 0:
        return requested
    return None


def _service_pid_or_listener_owns_port(runtime: Any, service: object, *, pid: int, port: int) -> bool:
    try:
        if bool(runtime.process_runner.pid_owns_port(pid, port)):
            return True
    except Exception:  # noqa: BLE001
        pass
    listener_pids = getattr(service, "listener_pids", None)
    if not isinstance(listener_pids, list):
        return False
    for listener_pid in listener_pids:
        if not isinstance(listener_pid, int) or listener_pid <= 0:
            continue
        try:
            if bool(runtime.process_runner.pid_owns_port(listener_pid, port)):
                return True
        except Exception:  # noqa: BLE001
            continue
    return False
