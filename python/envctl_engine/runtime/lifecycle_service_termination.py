from __future__ import annotations

import concurrent.futures
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from envctl_engine.shared.process_termination import (
    pid_is_running,
    terminate_pid,
    wait_for_pid_exit,
)
from envctl_engine.shared.services import service_project_name
from envctl_engine.runtime.lifecycle_requirement_ports import release_port_reservation


def terminate_started_services(runtime: Any, services: dict[str, object]) -> set[str]:
    """Terminate startup-owned services and report every unconfirmed exit."""

    failed: set[str] = set()
    for name, service in services.items():
        try:
            terminated = runtime._terminate_service_record(
                service,
                aggressive=False,
                verify_ownership=False,
            )
        except Exception as exc:  # noqa: BLE001
            _emit_cleanup_error(runtime, service=name, error=exc)
            terminated = False
        if not terminated:
            failed.add(name)
        else:
            _release_service_ports(runtime, name=name, service=service)
    return failed


def terminate_services_from_state(
    runtime: Any,
    state: object,
    *,
    selected_services: set[str] | None,
    aggressive: bool,
    verify_ownership: bool,
) -> set[str]:
    work_items: list[tuple[str, object]] = []
    for name, service in getattr(state, "services", {}).items():
        if selected_services is not None and name not in selected_services:
            continue
        work_items.append((name, service))

    def terminate_one(item: tuple[str, object]) -> tuple[str, object, bool, int | None]:
        name, service = item
        try:
            terminated = runtime._terminate_service_record(
                service,
                aggressive=aggressive,
                verify_ownership=verify_ownership,
            )
        except Exception as exc:  # noqa: BLE001
            _emit_cleanup_error(runtime, service=name, error=exc)
            terminated = False
        return name, service, terminated, service_port(service)

    if len(work_items) <= 1:
        results = [terminate_one(item) for item in work_items]
    else:
        worker_count = min(len(work_items), 8)
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
            results = list(pool.map(terminate_one, work_items))

    for name, service, terminated, _port in results:
        if terminated:
            _release_service_ports(runtime, name=name, service=service)
    return {name for name, _service, terminated, _port in results if not terminated}


def _release_service_ports(runtime: Any, *, name: str, service: object) -> None:
    port_planner = getattr(runtime, "port_planner", None)
    if port_planner is None:
        return
    project = str(service_project_name(service)).strip()
    if not project:
        project_resolver = getattr(runtime, "_project_name_from_service", None)
        if callable(project_resolver):
            project = str(project_resolver(name) or "").strip()
    service_type = str(getattr(service, "type", "") or "").strip().lower()
    owners: tuple[str, ...] = ()
    if project:
        owner_candidates = [f"{project}:services"]
        if service_type:
            owner_candidates = [
                f"{project}:{service_type}",
                f"{project}:services:{service_type}-launch",
                *owner_candidates,
            ]
        owners = tuple(owner_candidates)

    raw_expected_session = getattr(service, "port_lock_session", None)
    expected_session = raw_expected_session.strip() if isinstance(raw_expected_session, str) else None
    for port in service_ports(service):
        release_port_reservation(
            port_planner,
            port,
            owner_candidates=owners,
            expected_session=expected_session,
        )


def service_ports(service: object) -> tuple[int, ...]:
    """Return every distinct port reservation represented by a service record."""

    ports: list[int] = []
    for attribute in ("requested_port", "actual_port"):
        value = getattr(service, attribute, None)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0 and value not in ports:
            ports.append(value)
    return tuple(ports)


def terminate_service_record(runtime: Any, service: object, *, aggressive: bool, verify_ownership: bool) -> bool:
    recorded_pids = _recorded_service_pids(service)
    if not recorded_pids and str(getattr(service, "status", "") or "") == "termination_failed":
        return False
    protected_pids = {os.getpid(), os.getppid()}
    protected = [pid for pid in recorded_pids if pid in protected_pids]
    if protected:
        runtime._emit(
            "cleanup.skip",
            service=getattr(service, "name", "unknown"),
            pid=protected[0],
            reason="self_or_parent",
        )
        return False
    live_pids = [pid for pid in recorded_pids if _pid_is_running(runtime, pid)]
    port = service_port(service)
    listener_probe = _live_listener_pids_for_port(runtime, port) if port is not None else _ListenerProbe()
    if not live_pids:
        return not listener_probe.failed and not listener_probe.pids
    if verify_ownership:
        if port is None:
            if not all(_non_listener_service_matches_recorded_cwd(runtime, service, pid=pid) for pid in live_pids):
                runtime._emit(
                    "cleanup.skip",
                    service=getattr(service, "name", "unknown"),
                    pid=live_pids[0],
                    reason="missing_port_for_ownership",
                )
                return False
            termination_pids = live_pids
        else:
            owners = [pid for pid in live_pids if _pid_owns_port(runtime, pid=pid, port=port)]
            if not owners:
                runtime._emit(
                    "cleanup.skip",
                    service=getattr(service, "name", "unknown"),
                    pid=live_pids[0],
                    port=port,
                    reason="ownership_mismatch",
                )
                return False
            primary_pid = getattr(service, "pid", None)
            termination_pids = list(owners)
            if isinstance(primary_pid, int) and primary_pid in live_pids and primary_pid not in termination_pids:
                termination_pids.insert(0, primary_pid)
    else:
        termination_pids = live_pids

    failed = False
    for pid in termination_pids:
        if not _pid_is_running(runtime, pid):
            continue
        if not terminate_pid(
            pid,
            process_runner=runtime.process_runner,
            term_timeout=0.5 if aggressive else 2.0,
            kill_timeout=1.0,
        ):
            failed = True
    if failed:
        return False
    if port is not None:
        listener_probe = _live_listener_pids_for_port(runtime, port)
        if listener_probe.failed or listener_probe.pids:
            return False
    return True


def service_port(service: object) -> int | None:
    actual = getattr(service, "actual_port", None)
    if isinstance(actual, int) and actual > 0:
        return actual
    requested = getattr(service, "requested_port", None)
    if isinstance(requested, int) and requested > 0:
        return requested
    return None


def _emit_cleanup_error(runtime: Any, *, service: str, error: BaseException) -> None:
    emit = getattr(runtime, "_emit", None)
    if callable(emit):
        emit("cleanup.error", service=service, error=str(error))


def _pid_owns_port(runtime: Any, *, pid: int, port: int) -> bool:
    try:
        return bool(runtime.process_runner.pid_owns_port(pid, port))
    except Exception:  # noqa: BLE001
        return False


def _recorded_service_pids(service: object) -> list[int]:
    candidates = [getattr(service, "pid", None), *(getattr(service, "listener_pids", None) or [])]
    return list(
        dict.fromkeys(pid for pid in candidates if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0)
    )


@dataclass(frozen=True, slots=True)
class _ListenerProbe:
    available: bool = False
    failed: bool = False
    pids: frozenset[int] = frozenset()


def _live_listener_pids_for_port(runtime: Any, port: int) -> _ListenerProbe:
    listener_reader = getattr(runtime, "_listener_pids_for_port", None)
    if not callable(listener_reader):
        return _ListenerProbe()
    try:
        listeners = listener_reader(port)
    except Exception:  # noqa: BLE001
        return _ListenerProbe(available=True, failed=True)
    if listeners is None or isinstance(listeners, (str, bytes, Mapping)):
        return _ListenerProbe(available=True, failed=True)
    try:
        listener_items = iter(listeners)
    except TypeError:
        return _ListenerProbe(available=True, failed=True)
    return _ListenerProbe(
        available=True,
        pids=frozenset(
            pid
            for pid in listener_items
            if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0 and _pid_is_running(runtime, pid)
        ),
    )


def _non_listener_service_matches_recorded_cwd(runtime: Any, service: object, *, pid: int) -> bool:
    if bool(getattr(service, "listener_expected", True)):
        return False
    recorded_cwd = str(getattr(service, "cwd", "") or "").strip()
    if not recorded_cwd:
        return False
    cwd_reader = getattr(runtime.process_runner, "process_cwd", None)
    if not callable(cwd_reader):
        return False
    try:
        actual_cwd = str(cwd_reader(pid) or "").strip()
    except Exception:  # noqa: BLE001
        return False
    if not actual_cwd:
        return False
    try:
        return Path(actual_cwd).resolve(strict=False) == Path(recorded_cwd).resolve(strict=False)
    except OSError:
        return actual_cwd == recorded_cwd


def _wait_for_pid_exit(
    runtime: Any,
    pid: int,
    *,
    timeout: float,
    initial_identity: str | None,
) -> bool:
    return wait_for_pid_exit(
        runtime.process_runner,
        pid,
        timeout=timeout,
        initial_identity=initial_identity,
    )


def _pid_is_running(runtime: Any, pid: int) -> bool:
    return pid_is_running(runtime.process_runner, pid)
