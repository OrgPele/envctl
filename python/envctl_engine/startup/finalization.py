from __future__ import annotations

from pathlib import Path
import shlex
import sys
from typing import cast

from envctl_engine.dashboard_metadata import (
    APP_SERVICE_TYPES,
    DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY,
    serialize_dashboard_project_configured_services,
)
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.engine_runtime_env import effective_dependency_scope
from envctl_engine.startup.run_reuse_support import build_startup_identity_metadata
from envctl_engine.startup.protocols import ProjectContextLike, StartupRuntime
from envctl_engine.startup.session import StartupSession
from envctl_engine.state.models import RunState
from envctl_engine.ui.color_policy import colors_enabled
from envctl_engine.ui.status_symbols import STATUS_FAILURE


def build_success_run_state(runtime: StartupRuntime, session: StartupSession) -> RunState:
    return _build_run_state(runtime, session, failed=False)


def build_failure_run_state(runtime: StartupRuntime, session: StartupSession, error: str) -> RunState:
    run_state = _build_run_state(runtime, session, failed=True)
    run_state.metadata["failed"] = True
    run_state.metadata["failure_message"] = error
    return run_state


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
