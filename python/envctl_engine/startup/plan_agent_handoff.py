from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import shlex
from typing import Any, cast

from envctl_engine.planning.plan_agent.config import resolve_plan_agent_launch_config
from envctl_engine.planning.plan_agent.launch import launch_plan_agent_terminals
from envctl_engine.planning.plan_agent.models import (
    PlanAgentAttachValidation,
    PlanAgentLaunchOutcome,
    PlanAgentLaunchResult,
)
from envctl_engine.planning.plan_agent.recovery import plan_agent_native_recovery_command
from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.plan_agent_dependency_bootstrap import prepare_plan_agent_dependencies_for_launch
from envctl_engine.startup.plan_agent_launch_spinner import (
    launch_plan_agent_terminals_with_spinner,
    plan_agent_launch_spinner_label as _plan_agent_launch_spinner_label,
    plan_agent_launch_spinner_message as _plan_agent_launch_spinner_message,
    plan_agent_launch_spinner_success_message as _plan_agent_launch_spinner_success_message,
)
from envctl_engine.startup.dependency_bootstrap import prepare_project_dependencies
from envctl_engine.startup.session import LocalStartupFailure, StartupSession

PLAN_AGENT_WORKTREE_COMMANDS = {"plan", "import"}


def prepare_and_launch_plan_agent_worktrees(
    runtime: Any,
    session: StartupSession,
    *,
    resolve_launch_config_fn: Callable[..., object] = resolve_plan_agent_launch_config,
    ensure_run_id: Callable[[StartupSession], None],
    report_progress: Callable[..., None],
    prepare_dependencies_for_launch: Callable[..., None] = prepare_plan_agent_dependencies_for_launch,
    prepare_fn: Callable[..., object] = prepare_project_dependencies,
    launch_with_spinner: Callable[..., object] = launch_plan_agent_terminals_with_spinner,
    launch_fn: Callable[..., object] = launch_plan_agent_terminals,
    suppress_progress_output: Callable[[Route], bool],
    validate_attach_target_fn: Callable[..., PlanAgentAttachValidation],
    emit_launch_state: Callable[..., None] | None = None,
    should_fail_for_launch_result: Callable[..., bool] | None = None,
    launch_failure_message: Callable[[object], str] | None = None,
) -> int | None:
    emit_launch_state = emit_launch_state or emit_plan_agent_launch_state
    should_fail_for_launch_result = should_fail_for_launch_result or should_fail_for_plan_agent_launch_result
    launch_failure_message = launch_failure_message or plan_agent_launch_failure_message
    route = session.effective_route
    if route.command not in PLAN_AGENT_WORKTREE_COMMANDS or bool(route.flags.get("planning_prs")):
        return None
    if not session.plan_agent_launch_requested:
        return None
    created_worktrees = tuple(session.pending_plan_agent_worktrees)
    launch_config = resolve_launch_config_fn(runtime.config, getattr(runtime, "env", {}), route=route)
    if bool(getattr(launch_config, "enabled", False)) and created_worktrees:
        ensure_run_id(session)
        prepare_dependencies_for_launch(
            runtime,
            session,
            created_worktrees=created_worktrees,
            launch_config=launch_config,
            report_progress=report_progress,
            prepare_fn=prepare_fn,
        )
    launch_result = cast(
        PlanAgentLaunchResult,
        launch_with_spinner(
            runtime,
            route=session.effective_route,
            created_worktrees=created_worktrees,
            launch_config=launch_config,
            suppress_progress_output=suppress_progress_output(session.effective_route),
            launch_fn=launch_fn,
        ),
    )
    session.plan_agent_launch_result = launch_result
    session.plan_agent_attach_target = getattr(launch_result, "attach_target", None)
    validate_plan_agent_handoff_with_attach_target(
        runtime,
        validate_attach_target_fn,
        session,
        phase="post_launch",
    )
    emit_launch_state(runtime, session, launch_result)
    if should_fail_for_launch_result(session, launch_result):
        raise RuntimeError(launch_failure_message(launch_result))
    return None


def emit_plan_agent_launch_state(runtime: Any, session: StartupSession, launch_result: object) -> None:
    attach_target = getattr(launch_result, "attach_target", None)
    session_name = str(getattr(attach_target, "session_name", "")).strip() if attach_target is not None else ""
    launched_worktrees: list[str] = []
    failed_worktrees: list[str] = []
    launched_surface_ids: list[str] = []
    launched_workspace_ids: list[str] = []
    for outcome in tuple(getattr(launch_result, "outcomes", ()) or ()):
        status = str(getattr(outcome, "status", "")).strip().lower()
        worktree_name = str(getattr(outcome, "worktree_name", "")).strip()
        if status == "launched" and worktree_name:
            launched_worktrees.append(worktree_name)
        elif status == "failed" and worktree_name:
            failed_worktrees.append(worktree_name)
        if status == "launched":
            surface_id = str(getattr(outcome, "surface_id", "") or "").strip()
            workspace_id = str(getattr(outcome, "workspace_id", "") or "").strip()
            if surface_id and surface_id not in launched_surface_ids:
                launched_surface_ids.append(surface_id)
            if workspace_id and workspace_id not in launched_workspace_ids:
                launched_workspace_ids.append(workspace_id)
    route = session.effective_route
    route_transport = "omx" if bool(route.flags.get("omx")) else ("tmux" if bool(route.flags.get("tmux")) else "cmux")
    runtime._emit(
        "startup.plan_agent_launch_state",
        command=session.effective_route.command,
        mode=session.runtime_mode,
        route_transport=route_transport,
        status=str(getattr(launch_result, "status", "")).strip(),
        reason=str(getattr(launch_result, "reason", "")).strip(),
        launched_worktrees=launched_worktrees,
        failed_worktrees=failed_worktrees,
        launched_surface_ids=launched_surface_ids,
        launched_workspace_ids=launched_workspace_ids,
        session_name=session_name or None,
        implementation_session_running=session.plan_agent_session_started,
    )


def record_stale_plan_agent_handoff(
    runtime: Any,
    session: StartupSession,
    *,
    validation_reason: str,
    resolve_launch_config_fn: Callable[..., object] = resolve_plan_agent_launch_config,
    recovery_command_fn: Callable[..., tuple[str, ...]] = plan_agent_native_recovery_command,
) -> None:
    attach_target = session.plan_agent_attach_target
    if attach_target is None:
        return
    stale_session_name = str(getattr(attach_target, "session_name", "") or "").strip()
    stale_attach_command = " ".join(
        str(part).strip() for part in getattr(attach_target, "attach_command", ()) if str(part).strip()
    )
    session.plan_agent_stale_session_name = stale_session_name
    session.plan_agent_stale_attach_command = stale_attach_command
    session.plan_agent_handoff_validation_reason = validation_reason
    session.plan_agent_handoff_degraded = True
    launch_config = resolve_launch_config_fn(runtime.config, getattr(runtime, "env", {}), route=session.effective_route)
    recovery_command = shlex.join(
        recovery_command_fn(
            runtime,
            route=session.effective_route,
            launch_config=launch_config,
            created_worktrees=tuple(session.pending_plan_agent_worktrees),
        )
    )
    session.plan_agent_recovery_command = recovery_command
    session.plan_agent_attach_target = None
    launch_result = session.plan_agent_launch_result
    outcomes = tuple(getattr(launch_result, "outcomes", ()) or ()) if launch_result is not None else ()
    failed_outcomes = []
    for outcome in outcomes:
        failed_outcomes.append(
            PlanAgentLaunchOutcome(
                worktree_name=str(getattr(outcome, "worktree_name", "") or ""),
                worktree_root=Path(getattr(outcome, "worktree_root", ".") or "."),
                surface_id=getattr(outcome, "surface_id", None),
                status="failed",
                reason=validation_reason,
            )
        )
    session.plan_agent_launch_result = PlanAgentLaunchResult(
        status="failed",
        reason=validation_reason,
        outcomes=tuple(failed_outcomes),
        attach_target=None,
    )
    session.base_metadata.update(
        {
            "plan_agent_handoff_degraded": True,
            "implementation_session_running": False,
            "plan_agent_stale_session_name": stale_session_name,
            "plan_agent_stale_attach_command": stale_attach_command,
            "plan_agent_handoff_validation_reason": validation_reason,
            "plan_agent_launch_status": "failed",
            "plan_agent_launch_reason": validation_reason,
        }
    )
    if recovery_command:
        session.base_metadata["plan_agent_recovery_command"] = recovery_command
    runtime._emit(
        "startup.plan_agent_handoff.validation_failed",
        reason=validation_reason,
        stale_session_name=stale_session_name or None,
        stale_attach_command=stale_attach_command or None,
        recovery_command=recovery_command or None,
    )


def should_fail_for_plan_agent_launch_result(session: StartupSession, launch_result: object) -> bool:
    if session.effective_route.command not in PLAN_AGENT_WORKTREE_COMMANDS:
        return False
    if not session.plan_agent_launch_requested:
        return False
    launch_failed = str(getattr(launch_result, "status", "")).strip().lower() == "failed"
    return launch_failed and not session.plan_agent_attach_target


def plan_agent_handoff_validation_required(session: StartupSession) -> bool:
    route = session.effective_route
    if route.command not in PLAN_AGENT_WORKTREE_COMMANDS:
        return False
    return bool(route.flags.get("omx"))


def should_degrade_to_plan_agent_handoff(session: StartupSession, *, error: str) -> bool:
    route = session.effective_route
    if route.command not in PLAN_AGENT_WORKTREE_COMMANDS:
        return False
    if local_startup_failure_reason(error) is None:
        return False
    if not session.plan_agent_session_started:
        return False
    if bool(route.flags.get("batch")):
        return True
    return session.plan_agent_attach_target is not None


def validate_plan_agent_handoff(
    runtime: Any,
    session: StartupSession,
    *,
    phase: str,
    validate_attach_target_fn: Callable[..., PlanAgentAttachValidation],
    record_stale_handoff_fn: Callable[..., None] = record_stale_plan_agent_handoff,
) -> None:
    if not plan_agent_handoff_validation_required(session):
        return
    attach_target = session.plan_agent_attach_target
    if attach_target is None:
        return
    created_worktrees = tuple(session.pending_plan_agent_worktrees)
    worktree = created_worktrees[0] if created_worktrees else None
    validation = validate_attach_target_fn(
        runtime,
        attach_target,
        worktree=worktree,
        transport="omx",
        phase=phase,
    )
    if validation.ok:
        return
    record_stale_handoff_fn(
        runtime,
        session,
        validation_reason="attach_target_stale_after_launch",
    )


def validate_plan_agent_handoff_with_attach_target(
    runtime: Any,
    validate_attach_target_fn: Callable[..., PlanAgentAttachValidation],
    session: StartupSession,
    *,
    phase: str,
) -> None:
    validate_plan_agent_handoff(
        runtime,
        session,
        phase=phase,
        validate_attach_target_fn=validate_attach_target_fn,
    )


def should_degrade_to_validated_plan_agent_handoff(
    runtime: Any,
    session: StartupSession,
    *,
    error: str,
    validate_attach_target_fn: Callable[..., PlanAgentAttachValidation],
    record_stale_handoff_fn: Callable[..., None] = record_stale_plan_agent_handoff,
) -> bool:
    validate_plan_agent_handoff(
        runtime,
        session,
        phase="local_startup_failure",
        validate_attach_target_fn=validate_attach_target_fn,
        record_stale_handoff_fn=record_stale_handoff_fn,
    )
    return should_degrade_to_plan_agent_handoff(session, error=error)


def plan_agent_launch_failure_message(launch_result: object) -> str:
    details = []
    for outcome in tuple(getattr(launch_result, "outcomes", ()) or ()):
        reason = str(getattr(outcome, "reason", "") or "").strip()
        worktree_name = str(getattr(outcome, "worktree_name", "") or "").strip()
        if reason:
            details.append(f"{worktree_name}: {reason}" if worktree_name else reason)
    if not details:
        reason = str(getattr(launch_result, "reason", "") or "").strip()
        if reason:
            details.append(reason)
    suffix = f": {'; '.join(details[:3])}" if details else ""
    return f"Plan agent session failed to start{suffix}"


def plan_agent_launch_spinner_label(launch_config: object) -> str:
    return _plan_agent_launch_spinner_label(launch_config)


def plan_agent_launch_spinner_message(launch_config: object, *, count: int) -> str:
    return _plan_agent_launch_spinner_message(launch_config, count=count)


def plan_agent_launch_spinner_success_message(launch_config: object, *, count: int) -> str:
    return _plan_agent_launch_spinner_success_message(launch_config, count=count)


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
