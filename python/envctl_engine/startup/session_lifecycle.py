from __future__ import annotations

from collections.abc import Callable
import time
from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.protocols import StartupRuntime
from envctl_engine.startup.session import StartupSession
from envctl_engine.ui.debug_snapshot import snapshot_enabled


def create_startup_session(runtime: StartupRuntime, route: Route) -> StartupSession:
    runtime_mode = runtime._effective_start_mode(route)
    session = StartupSession(
        requested_route=route,
        effective_route=route,
        requested_command=route.command,
        runtime_mode=runtime_mode,
        run_id=None,
        startup_event_index=len(runtime.events),
        debug_plan_snapshot=snapshot_enabled(dict(runtime.env)),
    )
    runtime._reset_project_startup_warnings()
    return session


def ensure_run_id(runtime: StartupRuntime, session: StartupSession) -> None:
    if session.run_id is None:
        session.run_id = runtime._new_run_id()


def resolved_run_id(session: StartupSession) -> str:
    if session.run_id is None:
        raise RuntimeError("run_id must be resolved before use")
    return session.run_id


def announce_session_identifiers(
    runtime: StartupRuntime,
    session: StartupSession,
    *,
    headless_plan_output_only: Callable[[StartupSession], bool],
    print_fn: Callable[[str], None] = print,
) -> None:
    if session.identifiers_announced:
        return
    ensure_run_id(runtime, session)
    if not headless_plan_output_only(session):
        print_fn(f"run_id: {resolved_run_id(session)}")
        print_fn(f"session_id: {runtime._current_session_id() or 'unknown'}")
    session.identifiers_announced = True


def emit_startup_phase(
    runtime: StartupRuntime,
    session: StartupSession,
    phase: str,
    started_at: float,
    **extra: object,
) -> None:
    runtime._emit(
        "startup.phase",
        command=session.requested_command,
        mode=session.runtime_mode,
        phase=phase,
        duration_ms=round((time.monotonic() - started_at) * 1000.0, 2),
        **extra,
    )


def validate_startup_route_contract(
    runtime: StartupRuntime,
    session: StartupSession,
    *,
    emit_phase: Callable[..., None],
    print_fn: Callable[[str], None] = print,
) -> int | None:
    hook_contract_issue = runtime._startup_hook_contract_issue()
    if hook_contract_issue:
        print_fn(hook_contract_issue)
        return 1
    try:
        runtime._validate_mode_toggles(session.runtime_mode, route=session.effective_route)
    except RuntimeError as exc:
        print_fn(str(exc))
        return 1

    budget_started = time.monotonic()
    if not runtime._enforce_runtime_readiness_contract(scope=session.requested_command):
        emit_phase(session, "runtime_readiness_gate", budget_started, status="blocked")
        print_fn("Startup blocked: strict runtime readiness gate is incomplete.")
        return 1
    emit_phase(session, "runtime_readiness_gate", budget_started, status="ok")
    return None
