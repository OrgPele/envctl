from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.engine_runtime_env import route_is_implicit_start
from envctl_engine.startup.finalization import (
    build_planning_dashboard_state,
    headless_plan_output_only,
    maybe_attach_plan_agent_terminal,
    print_headless_plan_session_summary,
    print_plan_dry_run_preview,
)
from envctl_engine.startup.plan_agent_handoff import validate_plan_agent_handoff_with_attach_target
from envctl_engine.startup.session import StartupSession
from envctl_engine.startup.session_lifecycle import (
    announce_session_identifiers,
    emit_startup_phase,
    ensure_run_id,
    resolved_run_id,
)
from envctl_engine.startup.service_bootstrap_domain import configured_service_types_for_mode


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


def resolve_disabled_startup_mode_with_runtime(
    runtime: Any,
    session: StartupSession,
    *,
    validate_attach_target_fn: Callable[..., Any],
    attach_plan_agent_terminal: Callable[..., Any],
    print_fn: Callable[[str], None] = print,
) -> int | None:
    def validate_plan_agent_handoff(session: StartupSession, *, phase: str) -> None:
        validate_plan_agent_handoff_with_attach_target(
            runtime,
            validate_attach_target_fn,
            session,
            phase=phase,
        )

    return resolve_disabled_startup_mode(
        runtime=runtime,
        session=session,
        route_is_implicit_start=route_is_implicit_start,
        ensure_run_id=lambda session: ensure_run_id(runtime, session),
        announce_session_identifiers=lambda session: announce_session_identifiers(
            runtime,
            session,
            headless_plan_output_only=headless_plan_output_only,
        ),
        resolved_run_id=resolved_run_id,
        build_planning_dashboard_state=build_planning_dashboard_state,
        configured_service_types_for_mode=lambda runtime_mode: configured_service_types_for_mode(
            runtime.config,
            runtime_mode,
        ),
        emit_phase=lambda *args, **kwargs: emit_startup_phase(runtime, *args, **kwargs),
        validate_plan_agent_handoff=validate_plan_agent_handoff,
        print_plan_dry_run_preview=lambda session: print_plan_dry_run_preview(
            runtime,
            session,
            print_fn=print_fn,
        ),
        headless_plan_output_only=headless_plan_output_only,
        print_headless_plan_session_summary=lambda session: print_headless_plan_session_summary(
            session,
            validate_plan_agent_handoff=validate_plan_agent_handoff,
            print_fn=print_fn,
        ),
        maybe_attach_plan_agent_terminal=lambda session: maybe_attach_plan_agent_terminal(
            runtime=runtime,
            session=session,
            validate_plan_agent_handoff=validate_plan_agent_handoff,
            attach_plan_agent_terminal=attach_plan_agent_terminal,
            print_headless_plan_session_summary=lambda session, *, attach_target: (
                print_headless_plan_session_summary(
                    session,
                    validate_plan_agent_handoff=validate_plan_agent_handoff,
                    print_fn=print_fn,
                    attach_target=attach_target,
                )
            ),
        ),
        print_fn=print_fn,
    )
