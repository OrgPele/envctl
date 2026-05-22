from __future__ import annotations

from pathlib import Path
import shlex
import sys
import time
from collections.abc import Callable
from typing import cast

from envctl_engine.dashboard_metadata import (
    APP_SERVICE_TYPES,
    DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY,
    serialize_dashboard_project_configured_services,
)
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.engine_runtime_env import effective_dependency_scope
from envctl_engine.shared.services import service_display_name
from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree
from envctl_engine.startup.run_reuse_support import build_startup_identity_metadata
from envctl_engine.startup.protocols import ProjectContextLike, StartupRuntime
from envctl_engine.startup.session import StartupSession
from envctl_engine.state.models import RunState
from envctl_engine.ui.color_policy import colors_enabled
from envctl_engine.ui.path_links import local_paths_in_text, render_paths_in_terminal_text
from envctl_engine.ui.status_symbols import STATUS_FAILURE


def build_success_run_state(runtime: StartupRuntime, session: StartupSession) -> RunState:
    return _build_run_state(runtime, session, failed=False)


def build_failure_run_state(runtime: StartupRuntime, session: StartupSession, error: str) -> RunState:
    run_state = _build_run_state(runtime, session, failed=True)
    run_state.metadata["failed"] = True
    run_state.metadata["failure_message"] = error
    return run_state


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
    ensure_run_id(session)
    validate_plan_agent_handoff(session, phase="degraded_finalization")
    run_state = build_success_run_state(runtime, session)
    artifacts_started = time.monotonic()
    runtime._write_artifacts(run_state, session.selected_contexts, errors=session.errors)
    emit_phase(session, "artifacts_write", artifacts_started, status="degraded")
    render_plan_agent_degraded_handoff(session)
    if headless_plan_output_only(session):
        return 0
    attach_code = maybe_attach_plan_agent_terminal(session)
    if attach_code is not None:
        return attach_code
    return 0


def finalize_failed_startup(
    *,
    runtime: StartupRuntime,
    session: StartupSession,
    error: str,
    ensure_run_id: Callable[[StartupSession], None],
    port_allocator: Callable[[StartupRuntime], object],
    emit_phase: Callable[..., None],
    render_final_failure_status: Callable[..., str],
) -> int:
    ensure_run_id(session)
    allocator = port_allocator(runtime)
    if "no free port found" in error.lower():
        final_error = f"Port reservation failed: {error}"
    elif error.startswith("Startup failed:"):
        final_error = error
    else:
        final_error = f"Startup failed: {error}"
    session.failure_message = final_error
    session.errors.append(final_error)
    failure_payload: dict[str, object] = {
        "mode": session.runtime_mode,
        "command": session.effective_route.command,
        "error": final_error,
    }
    if session.strict_truth_failed:
        failure_payload["services"] = sorted(session.merged_services)
    runtime._emit("startup.failed", **failure_payload)
    started_services = {
        service_name: service
        for project_name in session.started_context_names
        for service_name, service in session.services_by_project.get(project_name, {}).items()
    }
    if started_services:
        runtime._terminate_started_services(started_services)
    allocator.release_session()
    run_state = build_failure_run_state(runtime, session, final_error)
    artifacts_started = time.monotonic()
    runtime._write_artifacts(run_state, session.selected_contexts, errors=session.errors)
    emit_phase(session, "artifacts_write", artifacts_started, status="error")
    link_mode = str(runtime.env.get("ENVCTL_UI_HYPERLINK_MODE", "")).strip().lower()
    rendered_error = render_final_failure_status(
        runtime,
        session,
        final_error,
        interactive_tty=(True if link_mode == "on" else None),
    )
    print(
        render_paths_in_terminal_text(
            rendered_error,
            paths=local_paths_in_text(rendered_error),
            env=runtime.env,
            stream=sys.stdout,
            interactive_tty=(True if link_mode == "on" else None),
        )
    )
    return 1


def plan_dry_run_preview_lines(session: StartupSession, *, created_names: set[str]) -> list[str]:
    lines = ["Dry run: no worktrees, git state, or services were modified."]
    for context in session.selected_contexts:
        action = "create" if context.name in created_names else "reuse"
        lines.append(f"{context.name}: {action}")
    return lines


def print_plan_dry_run_preview(
    runtime: StartupRuntime,
    session: StartupSession,
    *,
    print_fn: Callable[[str], None],
) -> None:
    route = session.effective_route
    if route.command != "plan" or not bool(route.flags.get("dry_run")):
        return
    planning_orchestrator = getattr(runtime, "planning_worktree_orchestrator", None)
    selection_getter = getattr(planning_orchestrator, "last_plan_selection_result", None)
    selection_result = selection_getter() if callable(selection_getter) else None
    created_names = {
        worktree.name
        for worktree in getattr(selection_result, "created_worktrees", ())
        if isinstance(worktree, CreatedPlanWorktree)
    }
    for line in plan_dry_run_preview_lines(session, created_names=created_names):
        print_fn(line)


def restart_port_rebound_summary_lines(
    session: StartupSession,
    events: list[dict[str, object]],
) -> list[str]:
    route = session.effective_route
    if session.requested_command != "restart" or not bool(route.flags.get("interactive_command")):
        return []
    lines: list[str] = []
    seen: set[tuple[str, str, int, int]] = set()
    for event in events[session.startup_event_index :]:
        if event.get("event") != "port.rebound":
            continue
        previous = event.get("restart_preferred_port")
        current = event.get("port")
        project = str(event.get("project") or "").strip()
        service = str(event.get("service") or "").strip()
        if not project or not service:
            continue
        if not isinstance(previous, int) or previous <= 0:
            continue
        if not isinstance(current, int) or current <= 0 or current == previous:
            continue
        key = (project, service, previous, current)
        if key in seen:
            continue
        seen.add(key)
        lines.append(
            f"Port changed: {project} {service_display_name(service)} "
            f"{previous} -> {current} (previous port still in use)"
        )
    return lines


def print_restart_port_rebound_summary(
    runtime: StartupRuntime,
    session: StartupSession,
    *,
    print_fn: Callable[[str], None],
) -> None:
    for line in restart_port_rebound_summary_lines(session, runtime.events):
        print_fn(line)


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


def render_final_failure_status(
    runtime: StartupRuntime,
    session: StartupSession,
    final_error: str,
    *,
    interactive_tty: bool | None,
) -> str:
    symbol = STATUS_FAILURE
    if colors_enabled(runtime.env, stream=sys.stdout, interactive_tty=bool(interactive_tty)):
        symbol = f"\033[31m{STATUS_FAILURE}\033[0m"
    rendered = f"{symbol} {final_error}"
    context_label = failure_context_label(session, final_error)
    if context_label and context_label not in rendered:
        rendered = f"{rendered} ({context_label})"
    return rendered


def plan_session_summary_lines(
    session: StartupSession,
    *,
    attach_target: object | None = None,
) -> list[str]:
    resolved_target = attach_target or session.plan_agent_attach_target
    if resolved_target is None:
        return []
    lines: list[str] = []
    attach_command = " ".join(
        str(part).strip() for part in getattr(resolved_target, "attach_command", ()) if str(part).strip()
    )
    new_session_command = " ".join(
        str(part).strip() for part in getattr(resolved_target, "new_session_command", ()) if str(part).strip()
    )
    session_name = str(getattr(resolved_target, "session_name", "")).strip()
    if new_session_command:
        lines.append(
            "existing session: envctl did not create a new AI session because one already exists for this "
            "plan/workspace/CLI."
        )
    if attach_command:
        lines.append(f"attach: {attach_command}")
    if new_session_command:
        lines.append(f"new session: {new_session_command}")
    if session_name:
        lines.append(f"kill: tmux kill-session -t {shlex.quote(session_name)}")
    return lines


def headless_plan_session_summary_lines(
    session: StartupSession,
    *,
    attach_target: object | None = None,
) -> list[str]:
    lines = plan_session_summary_lines(session, attach_target=attach_target)
    if attach_target is not None or session.plan_agent_attach_target is not None:
        return lines
    reason = str(session.plan_agent_handoff_validation_reason or "").strip()
    if not reason:
        return lines
    lines.append("Plan agent launch did not leave an attachable AI session.")
    lines.append(f"reason: {reason}")
    stale_name = str(session.plan_agent_stale_session_name or "").strip()
    if stale_name:
        lines.append(f"stale_session: {stale_name}")
    recovery_command = str(session.plan_agent_recovery_command or "").strip()
    if recovery_command:
        lines.append(f"recovery: {recovery_command}")
    return lines


def print_headless_plan_session_summary(
    session: StartupSession,
    *,
    validate_plan_agent_handoff: Callable[..., None],
    print_fn: Callable[[str], None],
    attach_target: object | None = None,
) -> None:
    if attach_target is None:
        validate_plan_agent_handoff(session, phase="headless_output")
    for line in headless_plan_session_summary_lines(session, attach_target=attach_target):
        print_fn(line)


def maybe_attach_plan_agent_terminal(
    *,
    runtime: StartupRuntime,
    session: StartupSession,
    validate_plan_agent_handoff: Callable[..., None],
    attach_plan_agent_terminal: Callable[[StartupRuntime, object], int],
    print_headless_plan_session_summary: Callable[..., None],
) -> int | None:
    validate_plan_agent_handoff(session, phase="interactive_attach")
    attach_target = session.plan_agent_attach_target
    if attach_target is None:
        return None
    session.plan_agent_attach_target = None
    attach_code = attach_plan_agent_terminal(runtime, attach_target)
    if attach_code != 0:
        print_headless_plan_session_summary(session, attach_target=attach_target)
        return 0
    return attach_code


def plan_agent_degraded_handoff_text(session: StartupSession) -> str:
    lines = [
        "Implementation session is running, but local app startup failed.",
        "",
        "AI session:",
    ]
    session_lines = plan_session_summary_lines(session)
    if session_lines:
        lines.extend(f"  {line}" for line in session_lines)
    else:
        lines.append("  status: running (attach guidance unavailable for this launch transport)")
    failures = list(session.local_startup_failures)
    if failures:
        lines.append("")
        if len(failures) == 1:
            failure = failures[0]
            lines.extend(
                [
                    "Local app startup:",
                    f"  project: {failure.project}",
                    f"  error: {failure.error}",
                    (
                        "  effect: backend/frontend services were not started; the AI implementation session "
                        "can continue."
                    ),
                    (
                        "  next: configure ENVCTL_BACKEND_START_CMD / ENVCTL_FRONTEND_START_CMD if this "
                        "worktree should start services, or disable tree startup when you only want AI "
                        "implementation sessions."
                    ),
                ]
            )
        else:
            lines.append("Local app startup:")
            for failure in failures:
                lines.extend(
                    [
                        f"  project: {failure.project}",
                        f"  error: {failure.error}",
                        (
                            "  effect: backend/frontend services were not started; the AI implementation "
                            "session can continue."
                        ),
                    ]
                )
            lines.append(
                "  next: configure ENVCTL_BACKEND_START_CMD / ENVCTL_FRONTEND_START_CMD if these worktrees "
                "should start services, or disable tree startup when you only want AI implementation sessions."
            )
    return "\n".join(lines)


def format_degraded_handoff_text_for_terminal(
    runtime: StartupRuntime,
    session: StartupSession,
    *,
    stream: object | None,
) -> str:
    text = plan_agent_degraded_handoff_text(session)
    link_mode = str(runtime.env.get("ENVCTL_UI_HYPERLINK_MODE", "")).strip().lower()
    return render_paths_in_terminal_text(
        text,
        paths=local_paths_in_text(text),
        env=runtime.env,
        stream=stream,
        interactive_tty=(True if link_mode == "on" else None),
    )


def failure_context_label(session: StartupSession, final_error: str) -> str | None:
    contexts: list[ProjectContextLike] = []
    seen_names: set[str] = set()
    for context in [*session.selected_contexts, *session.contexts_to_start]:
        name = str(getattr(context, "name", "") or "").strip()
        if not name or name in seen_names:
            continue
        contexts.append(context)
        seen_names.add(name)
    if not contexts:
        return None
    error_text = str(final_error or "")
    matches = [context for context in contexts if str(getattr(context, "name", "") or "").strip() in error_text]
    if matches:
        return format_failure_context_label(
            sorted(matches, key=lambda context: len(str(getattr(context, "name", "") or "")), reverse=True)[0]
        )
    if len(contexts) == 1:
        return format_failure_context_label(contexts[0])
    return None


def format_failure_context_label(context: ProjectContextLike) -> str:
    name = str(getattr(context, "name", "") or "").strip()
    root = Path(str(getattr(context, "root", "") or ""))
    kind = "worktree" if any(part == "trees" or part.startswith("trees-") for part in root.parts) else "project"
    return f"{kind}: {name}"


def build_planning_dashboard_state(
    runtime: StartupRuntime,
    *,
    route: Route,
    runtime_mode: str,
    run_id: str,
    project_contexts: list[ProjectContextLike],
    configured_service_types: list[str],
    base_metadata: dict[str, object] | None = None,
) -> RunState:
    metadata = build_startup_identity_metadata(
        runtime,
        runtime_mode=runtime_mode,
        project_contexts=cast(list[object], project_contexts),
        base_metadata=base_metadata,
        route=route,
    )
    metadata.update(
        {
            "command": route.command,
            "repo_scope_id": runtime.config.runtime_scope_id,
            "dashboard_configured_service_types": configured_service_types,
            "dashboard_hidden_commands": [
                "stop",
                "restart",
                "stop-all",
                "blast-all",
                "logs",
                "clear-logs",
                "health",
                "errors",
            ],
            "dashboard_runs_disabled": True,
            "dashboard_banner": (
                f"envctl runs are disabled for {runtime_mode}; planning and action commands remain available."
            ),
        }
    )
    run_state = RunState(
        run_id=run_id,
        mode=runtime_mode,
        services={},
        requirements={},
        pointers={},
        metadata=metadata,
    )
    run_state.pointers = _build_pointer_map(runtime, run_id)
    return run_state


def _build_run_state(runtime: StartupRuntime, session: StartupSession, *, failed: bool) -> RunState:
    if session.run_id is None:
        raise RuntimeError("run_id must be resolved before building run state")
    metadata = build_startup_identity_metadata(
        runtime,
        runtime_mode=session.runtime_mode,
        project_contexts=cast(list[object], session.selected_contexts),
        base_metadata=session.base_metadata,
        route=session.effective_route,
    )
    metadata.update(
        {
            "command": session.effective_route.command,
            "repo_scope_id": runtime.config.runtime_scope_id,
        }
    )
    dependency_mode = effective_dependency_scope(session.effective_route, session.runtime_mode)
    metadata["dependency_mode"] = dependency_mode
    metadata["shared_dependencies"] = dependency_mode == "shared"
    metadata["frontend_dependency_env_projection_active"] = _frontend_dependency_env_projection_active(runtime)
    launch_diagnostics = session.effective_route.flags.get("_runtime_launch_diagnostics")
    if isinstance(launch_diagnostics, dict) and launch_diagnostics:
        metadata["runtime_launch_diagnostics"] = launch_diagnostics
    requested_dependency_scope = session.effective_route.flags.get("dependency_scope")
    if requested_dependency_scope is not None:
        metadata["dependency_scope_requested"] = str(requested_dependency_scope)
    project_configured_services = _project_configured_services_metadata(runtime, session)
    if project_configured_services:
        metadata[DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY] = project_configured_services
    shared_dependency_project = _shared_dependency_dashboard_project(session)
    if shared_dependency_project:
        metadata["dashboard_dependency_scope"] = "shared"
        metadata["dashboard_shared_dependency_project"] = shared_dependency_project
    if session.warnings:
        metadata["warnings"] = list(session.warnings)
    if session.plan_agent_launch_result is not None:
        launch_result = session.plan_agent_launch_result
        metadata["plan_agent_launch_status"] = str(getattr(launch_result, "status", "")).strip()
        metadata["plan_agent_launch_reason"] = str(getattr(launch_result, "reason", "")).strip()
        if metadata["plan_agent_launch_status"] == "failed":
            metadata["plan_agent_launch_failed"] = True
        launch_outcomes: list[dict[str, object]] = []
        for outcome in tuple(getattr(launch_result, "outcomes", ()) or ()):
            launch_outcomes.append(
                {
                    "worktree_name": str(getattr(outcome, "worktree_name", "")).strip(),
                    "worktree_root": str(getattr(outcome, "worktree_root", "")).strip(),
                    "surface_id": getattr(outcome, "surface_id", None),
                    "status": str(getattr(outcome, "status", "")).strip(),
                    "reason": getattr(outcome, "reason", None),
                }
            )
        if launch_outcomes:
            metadata["plan_agent_launch_outcomes"] = launch_outcomes
    if session.plan_agent_handoff_degraded or session.local_startup_failures:
        metadata["plan_agent_handoff_degraded"] = bool(session.plan_agent_handoff_degraded)
        metadata["implementation_session_running"] = bool(session.plan_agent_session_started)
        metadata["local_startup_failed"] = bool(session.local_startup_failures)
        metadata["local_startup_failures"] = [failure.to_metadata() for failure in session.local_startup_failures]
    if session.plan_agent_handoff_validation_reason:
        metadata["plan_agent_handoff_degraded"] = True
        metadata["implementation_session_running"] = False
        metadata["plan_agent_handoff_validation_reason"] = session.plan_agent_handoff_validation_reason
    if session.plan_agent_stale_session_name:
        metadata["plan_agent_stale_session_name"] = session.plan_agent_stale_session_name
    if session.plan_agent_stale_attach_command:
        metadata["plan_agent_stale_attach_command"] = session.plan_agent_stale_attach_command
    if session.plan_agent_recovery_command:
        metadata["plan_agent_recovery_command"] = session.plan_agent_recovery_command
    attach_target = session.plan_agent_attach_target
    if attach_target is None and session.plan_agent_launch_result is not None:
        attach_target = getattr(session.plan_agent_launch_result, "attach_target", None)
    if attach_target is not None:
        session_name = str(getattr(attach_target, "session_name", "")).strip()
        attach_command = " ".join(
            str(part).strip() for part in getattr(attach_target, "attach_command", ()) if str(part).strip()
        )
        if session_name:
            metadata["plan_agent_session_name"] = session_name
        if attach_command:
            metadata["plan_agent_attach_command"] = attach_command
    run_state = RunState(
        run_id=session.run_id,
        mode=session.runtime_mode,
        services=session.merged_services,
        requirements=session.merged_requirements,
        pointers={},
        metadata=metadata,
    )
    if failed:
        run_state.metadata["failed"] = True
    run_state.pointers = _build_pointer_map(runtime, session.run_id)
    return run_state


def _project_configured_services_metadata(
    runtime: StartupRuntime, session: StartupSession
) -> dict[str, list[str]]:
    configured: dict[str, list[str]] = {}
    for context in session.selected_contexts:
        service_types = [
            service_type
            for service_type in APP_SERVICE_TYPES
            if runtime._service_enabled_for_mode(session.runtime_mode, service_type)
        ]
        if service_types:
            configured[str(context.name)] = service_types
    return serialize_dashboard_project_configured_services(configured)


def _frontend_dependency_env_projection_active(runtime: StartupRuntime) -> bool:
    config = runtime.config
    return bool(
        getattr(config, "dependency_env_section_present", False)
        or getattr(config, "frontend_dependency_env_section_present", False)
        or getattr(config, "main_frontend_dependency_env_section_present", False)
        or getattr(config, "trees_frontend_dependency_env_section_present", False)
        or bool(getattr(config, "service_dependency_env_section_present", {}) or {})
        or bool(getattr(config, "mode_service_dependency_env_section_present", {}) or {})
    )


def _shared_dependency_dashboard_project(session: StartupSession) -> str | None:
    if session.runtime_mode != "trees":
        return None
    if effective_dependency_scope(session.effective_route, session.runtime_mode) != "shared":
        return None
    for requirements in session.merged_requirements.values():
        project = str(getattr(requirements, "project", "") or "").strip()
        if project:
            return project
    return "Main"


def _build_pointer_map(runtime: StartupRuntime, run_id: str) -> dict[str, str]:
    run_dir = runtime._run_dir_path(run_id)
    return {
        "run_state": str(run_dir / "run_state.json"),
        "runtime_map": str(run_dir / "runtime_map.json"),
        "ports_manifest": str(run_dir / "ports_manifest.json"),
        "error_report": str(run_dir / "error_report.json"),
        "events": str(run_dir / "events.jsonl"),
        "runtime_readiness_report": str(run_dir / "runtime_readiness_report.json"),
    }
