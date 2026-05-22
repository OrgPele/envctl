from __future__ import annotations

from typing import Any

from envctl_engine.startup.session import LocalStartupFailure, StartupSession


def local_startup_failure_reason(error: str) -> str | None:
    if "missing_service_start_command" in error:
        return "missing_service_start_command"
    return None


def record_plan_agent_handoff_local_startup_failure(
    runtime: Any,
    session: StartupSession,
    *,
    project_name: str,
    error: str,
) -> None:
    reason = local_startup_failure_reason(error) or "local_startup_failed"
    failure = LocalStartupFailure(project=project_name, error=error, reason=reason)
    session.local_startup_failures.append(failure)
    session.plan_agent_handoff_degraded = True
    warning = f"Implementation session is running, but local app startup failed for {project_name}: {error}"
    session.warnings.append(warning)
    launch_result = session.plan_agent_launch_result
    attach_target = session.plan_agent_attach_target
    session_name = str(getattr(attach_target, "session_name", "")).strip() if attach_target is not None else ""
    route = session.effective_route
    route_transport = "omx" if bool(route.flags.get("omx")) else ("tmux" if bool(route.flags.get("tmux")) else "cmux")
    if bool(route.flags.get("ultragoal")):
        omx_workflow = "ultragoal"
    elif bool(route.flags.get("ralph")):
        omx_workflow = "ralph"
    elif bool(route.flags.get("team")):
        omx_workflow = "team"
    else:
        omx_workflow = None
    runtime._emit(
        "startup.project.warning",
        project=project_name,
        warning=warning,
        reason="plan_agent_handoff_local_startup_failed",
        implementation_session_running=True,
        local_startup_failed=True,
        session_name=session_name or None,
    )
    runtime._emit(
        "startup.plan_agent_handoff.degraded",
        project=project_name,
        error=error,
        reason=reason,
        implementation_session_running=True,
        session_name=session_name or None,
        route_transport=route_transport,
        omx_workflow=omx_workflow,
        launch_status=str(getattr(launch_result, "status", "")).strip() if launch_result is not None else None,
    )
