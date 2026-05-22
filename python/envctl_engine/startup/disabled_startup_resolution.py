from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.session import StartupSession


def resolve_disabled_startup_mode(
    *,
    runtime: Any,
    session: StartupSession,
    route_is_implicit_start: Callable[[Route], bool],
    ensure_run_id: Callable[[StartupSession], None],
    announce_session_identifiers: Callable[[StartupSession], None],
    resolved_run_id: Callable[[StartupSession], str],
    build_planning_dashboard_state: Callable[..., Any],
    configured_service_types_for_mode: Callable[[str], set[str]],
    emit_phase: Callable[..., None],
    validate_plan_agent_handoff: Callable[..., None],
    print_plan_dry_run_preview: Callable[[StartupSession], None],
    headless_plan_output_only: Callable[[StartupSession], bool],
    print_headless_plan_session_summary: Callable[[StartupSession], None],
    maybe_attach_plan_agent_terminal: Callable[[StartupSession], int | None],
    print_fn: Callable[[str], None] = print,
) -> int | None:
    route = session.effective_route
    mode_runs_enabled = (
        runtime.config.startup_enabled_for_mode(session.runtime_mode)
        if hasattr(runtime.config, "startup_enabled_for_mode")
        else True
    )
    allow_disabled_dashboard = not mode_runs_enabled and (route.command == "plan" or route_is_implicit_start(route))
    session.disabled_startup_mode = allow_disabled_dashboard
    if not allow_disabled_dashboard:
        return None
    ensure_run_id(session)
    announce_session_identifiers(session)
    run_state = build_planning_dashboard_state(
        runtime,
        route=route,
        runtime_mode=session.runtime_mode,
        run_id=resolved_run_id(session),
        project_contexts=session.selected_contexts,
        configured_service_types=configured_service_types_for_mode(session.runtime_mode),
        base_metadata=session.base_metadata,
    )
    artifacts_started = time.monotonic()
    runtime._write_artifacts(run_state, session.selected_contexts, errors=[])
    emit_phase(session, "artifacts_write", artifacts_started, status="ok")
    if route.command == "plan":
        validate_plan_agent_handoff(session, phase="disabled_startup_finalization")
        print_plan_dry_run_preview(session)
        print_fn(
            "Planning mode complete; skipping service startup because "
            f"envctl runs are disabled for {session.runtime_mode}."
        )
    if headless_plan_output_only(session):
        print_headless_plan_session_summary(session)
        return 0
    enter_interactive_dashboard = runtime._should_enter_post_start_interactive(route)
    attach_code = maybe_attach_plan_agent_terminal(session)
    if attach_code is not None:
        return attach_code
    if not enter_interactive_dashboard:
        print_fn(f"envctl runs are disabled for {session.runtime_mode}; opening dashboard without starting services.")
    if enter_interactive_dashboard:
        return runtime._run_interactive_dashboard_loop(run_state)
    return 0

