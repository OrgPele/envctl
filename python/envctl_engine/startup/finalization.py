from __future__ import annotations

import time
import sys
from collections.abc import Callable

from envctl_engine.planning.plan_agent.tmux_transport import attach_plan_agent_terminal
from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.finalization_plan_output import (
    format_degraded_handoff_text_for_terminal,
    headless_plan_output_only,
    headless_plan_session_summary_lines,
    maybe_attach_plan_agent_terminal,
    plan_agent_degraded_handoff_text,
    plan_dry_run_preview_lines,
    plan_session_summary_lines,
    print_headless_plan_session_summary,
    print_plan_dry_run_preview,
    print_restart_port_rebound_summary,
    render_plan_agent_degraded_handoff_for_terminal,
    resolve_plan_dry_run,
    restart_port_rebound_summary_lines,
)
from envctl_engine.startup.finalization_failure import (
    build_failure_run_state as build_failure_run_state,
    failure_context_label as failure_context_label,
    finalize_failed_startup as finalize_failed_startup,
    format_failure_context_label as format_failure_context_label,
    render_final_failure_status as render_final_failure_status,
)
from envctl_engine.startup.finalization_run_state import (
    _build_run_state as _build_run_state,
    build_planning_dashboard_state as build_planning_dashboard_state,
)
from envctl_engine.startup.requirements_execution import requirements_timing_enabled, startup_breakdown_enabled
from envctl_engine.startup.protocols import ProjectContextLike, StartupRuntime
from envctl_engine.startup.session import StartupSession
from envctl_engine.startup.session_lifecycle import emit_startup_phase, ensure_run_id
from envctl_engine.startup.startup_execution_support import print_startup_summary
from envctl_engine.startup.startup_progress import suppress_progress_output, suppress_timing_output
from envctl_engine.state.models import RunState
from envctl_engine.ui.debug_snapshot import emit_startup_plan_handoff_snapshot
from envctl_engine.ui.path_links import local_paths_in_text, render_paths_in_terminal_text

__all__ = [
    "format_degraded_handoff_text_for_terminal",
    "headless_plan_output_only",
    "headless_plan_session_summary_lines",
    "maybe_attach_plan_agent_terminal",
    "plan_agent_degraded_handoff_text",
    "plan_dry_run_preview_lines",
    "plan_session_summary_lines",
    "print_headless_plan_session_summary",
    "print_plan_dry_run_preview",
    "print_restart_port_rebound_summary",
    "render_plan_agent_degraded_handoff_for_terminal",
    "resolve_plan_dry_run",
    "restart_port_rebound_summary_lines",
]


def build_success_run_state(runtime: StartupRuntime, session: StartupSession) -> RunState:
    return _build_run_state(runtime, session, failed=False)


def emit_preserved_service_merge(runtime: StartupRuntime, session: StartupSession) -> None:
    if not session.preserved_services:
        return
    replaced = sorted(name for project_services in session.services_by_project.values() for name in project_services)
    runtime._emit(
        "runtime.state.merge_preserved_services",
        preserved_services=sorted(session.preserved_services),
        replaced_services=replaced,
        preserved_requirements=sorted(session.preserved_requirements),
        replaced_requirements=sorted(session.requirements_by_project),
    )


def finalize_successful_startup(
    *,
    runtime: StartupRuntime,
    session: StartupSession,
    ensure_run_id: Callable[[StartupSession], None],
    validate_plan_agent_handoff: Callable[..., None],
    build_success_run_state: Callable[[StartupRuntime, StartupSession], RunState],
    emit_preserved_service_merge: Callable[[StartupSession], None],
    emit_phase: Callable[..., None],
    requirements_timing_enabled: Callable[[Route], bool],
    suppress_timing_output: Callable[[Route], bool],
    print_startup_summary: Callable[..., None],
    startup_breakdown_enabled: Callable[[Route], bool],
    suppress_progress_output: Callable[[Route], bool],
    print_restart_port_rebound_summary: Callable[[StartupSession], None],
    emit_snapshot: Callable[..., None],
    headless_plan_output_only: Callable[[StartupSession], bool],
    print_headless_plan_session_summary: Callable[[StartupSession], None],
    maybe_attach_plan_agent_terminal: Callable[[StartupSession], int | None],
    finalize_plan_agent_degraded_handoff: Callable[[StartupSession], int],
) -> int:
    if session.plan_agent_handoff_degraded:
        return finalize_plan_agent_degraded_handoff(session)
    ensure_run_id(session)
    validate_plan_agent_handoff(session, phase="success_finalization")
    run_state = build_success_run_state(runtime, session)
    emit_preserved_service_merge(session)
    artifacts_started = time.monotonic()
    runtime._write_artifacts(run_state, session.selected_contexts, errors=session.errors)
    emit_phase(session, "artifacts_write", artifacts_started, status="ok")
    if requirements_timing_enabled(session.effective_route) and not suppress_timing_output(session.effective_route):
        runtime._emit(
            "startup.debug_tty_group",
            component="startup_orchestrator",
            group="output",
            action="print_startup_summary",
            enabled=True,
            detail="startup_branch",
        )
        print_startup_summary(
            project_contexts=session.selected_contexts,
            start_event_index=session.startup_event_index,
            startup_started_at=session.startup_started_at,
        )
    else:
        runtime._emit(
            "startup.debug_tty_group",
            component="startup_orchestrator",
            group="output",
            action="print_startup_summary",
            enabled=False,
            detail="startup_branch",
        )
    if startup_breakdown_enabled(session.effective_route):
        runtime._emit(
            "startup.breakdown",
            command=session.requested_command,
            mode=session.runtime_mode,
            project_count=len(session.selected_contexts),
            projects=[context.name for context in session.selected_contexts],
            total_ms=round((time.monotonic() - session.startup_started_at) * 1000.0, 2),
        )
    runtime._emit(
        "startup.debug_tty_group",
        component="startup_orchestrator",
        group="output",
        action="dashboard_summary_or_status",
        enabled=True,
        detail="startup_branch",
    )
    if not suppress_progress_output(session.effective_route):
        if session.used_project_spinner_group:
            pass
        else:
            print_restart_port_rebound_summary(session)
            runtime._print_summary(run_state, session.selected_contexts)
    else:
        print_restart_port_rebound_summary(session)
        runtime._emit("ui.status", message="Startup complete; refreshing dashboard...")
    emit_snapshot(
        session,
        "before_dashboard_entry",
        source="startup_branch",
        command=session.requested_command,
        mode=session.runtime_mode,
        service_count=len(run_state.services),
        requirement_count=len(run_state.requirements),
    )
    if headless_plan_output_only(session):
        print_headless_plan_session_summary(session)
        return 0
    attach_code = maybe_attach_plan_agent_terminal(session)
    if attach_code is not None:
        return attach_code
    if runtime._should_enter_post_start_interactive(session.effective_route):
        return runtime._run_interactive_dashboard_loop(run_state)
    return 0


def finalize_successful_startup_with_runtime(
    runtime: StartupRuntime,
    session: StartupSession,
    *,
    validate_plan_agent_handoff: Callable[..., None],
    print_fn: Callable[[str], None] = print,
) -> int:
    orchestrator_like = type("_StartupFinalizationRuntimeFacade", (), {"runtime": runtime})()
    return finalize_successful_startup(
        runtime=runtime,
        session=session,
        ensure_run_id=lambda session: ensure_run_id(runtime, session),
        validate_plan_agent_handoff=validate_plan_agent_handoff,
        build_success_run_state=build_success_run_state,
        emit_preserved_service_merge=lambda session: emit_preserved_service_merge(runtime, session),
        emit_phase=lambda *args, **kwargs: emit_startup_phase(runtime, *args, **kwargs),
        requirements_timing_enabled=lambda route: requirements_timing_enabled(orchestrator_like, route),
        suppress_timing_output=suppress_timing_output,
        print_startup_summary=lambda **kwargs: print_startup_summary(orchestrator_like, **kwargs),
        startup_breakdown_enabled=lambda route: startup_breakdown_enabled(orchestrator_like, route),
        suppress_progress_output=suppress_progress_output,
        print_restart_port_rebound_summary=lambda session: print_restart_port_rebound_summary(
            runtime,
            session,
            print_fn=print_fn,
        ),
        emit_snapshot=lambda *args, **kwargs: emit_startup_plan_handoff_snapshot(runtime, *args, **kwargs),
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
        finalize_plan_agent_degraded_handoff=lambda session: finalize_plan_agent_degraded_handoff_with_runtime(
            runtime,
            session,
            validate_plan_agent_handoff=validate_plan_agent_handoff,
            print_fn=print_fn,
        ),
    )


def finalize_plan_agent_degraded_handoff_with_runtime(
    runtime: StartupRuntime,
    session: StartupSession,
    *,
    validate_plan_agent_handoff: Callable[..., None],
    print_fn: Callable[[str], None] = print,
) -> int:
    return finalize_plan_agent_degraded_handoff(
        runtime=runtime,
        session=session,
        ensure_run_id=lambda session: ensure_run_id(runtime, session),
        validate_plan_agent_handoff=validate_plan_agent_handoff,
        build_success_run_state=build_success_run_state,
        emit_phase=lambda *args, **kwargs: emit_startup_phase(runtime, *args, **kwargs),
        render_plan_agent_degraded_handoff=lambda session: render_plan_agent_degraded_handoff_for_terminal(
            runtime,
            session,
            stream=sys.stdout,
            print_fn=print_fn,
        ),
        headless_plan_output_only=headless_plan_output_only,
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
    )


def finalize_plan_agent_degraded_handoff(
    *,
    runtime: StartupRuntime,
    session: StartupSession,
    ensure_run_id: Callable[[StartupSession], None],
    validate_plan_agent_handoff: Callable[..., None],
    build_success_run_state: Callable[[StartupRuntime, StartupSession], RunState],
    emit_phase: Callable[..., None],
    render_plan_agent_degraded_handoff: Callable[[StartupSession], None],
    headless_plan_output_only: Callable[[StartupSession], bool],
    maybe_attach_plan_agent_terminal: Callable[[StartupSession], int | None],
) -> int:
    finalize_plan_agent_degraded_handoff_artifacts(
        runtime=runtime,
        session=session,
        ensure_run_id=ensure_run_id,
        validate_plan_agent_handoff=validate_plan_agent_handoff,
        build_success_run_state=build_success_run_state,
        emit_phase=emit_phase,
    )
    render_plan_agent_degraded_handoff(session)
    if headless_plan_output_only(session):
        return 0
    attach_code = maybe_attach_plan_agent_terminal(session)
    if attach_code is not None:
        return attach_code
    return 0


def finalize_plan_agent_degraded_handoff_artifacts(
    *,
    runtime: StartupRuntime,
    session: StartupSession,
    ensure_run_id: Callable[[StartupSession], None],
    validate_plan_agent_handoff: Callable[..., None],
    build_success_run_state: Callable[[StartupRuntime, StartupSession], RunState],
    emit_phase: Callable[..., None],
) -> RunState:
    ensure_run_id(session)
    validate_plan_agent_handoff(session, phase="degraded_finalization")
    run_state = build_success_run_state(runtime, session)
    artifacts_started = time.monotonic()
    runtime._write_artifacts(run_state, session.selected_contexts, errors=session.errors)
    emit_phase(session, "artifacts_write", artifacts_started, status="degraded")
    return run_state


def render_project_startup_warnings(
    runtime: StartupRuntime,
    *,
    context: ProjectContextLike,
    warnings: list[str],
    suppress_progress: bool,
    project_spinner_group: object | None,
) -> None:
    warning_lines = [str(line).strip() for line in warnings if str(line).strip()]
    if not warning_lines:
        return
    if project_spinner_group is not None and hasattr(project_spinner_group, "print_detail"):
        for line in warning_lines:
            getattr(project_spinner_group, "print_detail")(context.name, line)
        return
    if suppress_progress:
        for line in warning_lines:
            runtime._emit("ui.status", message=line)  # type: ignore[attr-defined]
        return
    link_mode = str(runtime.env.get("ENVCTL_UI_HYPERLINK_MODE", "")).strip().lower()
    for line in warning_lines:
        print(
            render_paths_in_terminal_text(
                line,
                paths=local_paths_in_text(line),
                env=runtime.env,
                stream=sys.stdout,
                interactive_tty=(True if link_mode == "on" else None),
            )
        )


def render_project_startup_warnings_for_route(
    runtime: StartupRuntime,
    *,
    context: ProjectContextLike,
    warnings: list[str],
    route: Route,
    project_spinner_group: object | None,
    suppress_progress_output: Callable[[Route], bool],
) -> None:
    render_project_startup_warnings(
        runtime,
        context=context,
        warnings=warnings,
        suppress_progress=suppress_progress_output(route),
        project_spinner_group=project_spinner_group,
    )
