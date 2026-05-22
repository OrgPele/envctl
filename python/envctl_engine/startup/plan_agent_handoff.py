from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
import shlex
from typing import Any

from envctl_engine.planning.plan_agent.config import resolve_plan_agent_launch_config
from envctl_engine.planning.plan_agent.launch import launch_plan_agent_terminals
from envctl_engine.planning.plan_agent.models import PlanAgentLaunchOutcome, PlanAgentLaunchResult
from envctl_engine.planning.plan_agent.recovery import plan_agent_native_recovery_command
from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy
from envctl_engine.startup.session import LocalStartupFailure, StartupSession


def launch_plan_agent_terminals_with_spinner(
    runtime: Any,
    *,
    route: object,
    created_worktrees: tuple[object, ...],
    launch_config: object,
    suppress_progress_output: bool,
    launch_fn: Callable[..., object] = launch_plan_agent_terminals,
    resolve_spinner_policy_fn: Callable[[dict[str, object]], object] = resolve_spinner_policy,
    emit_spinner_policy_fn: Callable[..., None] = emit_spinner_policy,
    spinner_fn: Callable[..., AbstractContextManager[Any]] = spinner,
    use_spinner_policy_fn: Callable[[object], AbstractContextManager[object]] = use_spinner_policy,
) -> object:
    spinner_policy = resolve_spinner_policy_fn(dict(runtime.env))
    use_launch_spinner = (
        bool(getattr(spinner_policy, "enabled", False))
        and bool(getattr(launch_config, "enabled", False))
        and bool(created_worktrees)
        and not suppress_progress_output
    )
    emit_spinner_policy_fn(
        runtime._emit,
        spinner_policy,
        context={"component": "startup_orchestrator", "op_id": "plan_agent.launch"},
    )
    if not use_launch_spinner:
        return launch_fn(runtime, route=route, created_worktrees=created_worktrees)

    launch_message = plan_agent_launch_spinner_message(launch_config, count=len(created_worktrees))
    with use_spinner_policy_fn(spinner_policy), spinner_fn(launch_message, enabled=True) as active_spinner:
        runtime._emit(
            "ui.spinner.lifecycle",
            component="startup_orchestrator",
            op_id="plan_agent.launch",
            state="start",
            message=launch_message,
        )
        try:
            launch_result = launch_fn(runtime, route=route, created_worktrees=created_worktrees)
        except Exception:
            failure_message = "AI session launch failed"
            active_spinner.fail(failure_message)
            runtime._emit(
                "ui.spinner.lifecycle",
                component="startup_orchestrator",
                op_id="plan_agent.launch",
                state="fail",
                message=failure_message,
            )
            runtime._emit(
                "ui.spinner.lifecycle",
                component="startup_orchestrator",
                op_id="plan_agent.launch",
                state="stop",
            )
            raise
        status = str(getattr(launch_result, "status", "")).strip().lower()
        if status == "failed":
            failure_message = "AI session launch failed"
            active_spinner.fail(failure_message)
            runtime._emit(
                "ui.spinner.lifecycle",
                component="startup_orchestrator",
                op_id="plan_agent.launch",
                state="fail",
                message=failure_message,
            )
        else:
            success_message = plan_agent_launch_spinner_success_message(launch_config, count=len(created_worktrees))
            active_spinner.succeed(success_message)
            runtime._emit(
                "ui.spinner.lifecycle",
                component="startup_orchestrator",
                op_id="plan_agent.launch",
                state="success",
                message=success_message,
            )
        runtime._emit(
            "ui.spinner.lifecycle",
            component="startup_orchestrator",
            op_id="plan_agent.launch",
            state="stop",
        )
        return launch_result


def emit_plan_agent_launch_state(runtime: Any, session: StartupSession, launch_result: object) -> None:
    attach_target = getattr(launch_result, "attach_target", None)
    session_name = str(getattr(attach_target, "session_name", "")).strip() if attach_target is not None else ""
    launched_worktrees: list[str] = []
    failed_worktrees: list[str] = []
    for outcome in tuple(getattr(launch_result, "outcomes", ()) or ()):
        status = str(getattr(outcome, "status", "")).strip().lower()
        worktree_name = str(getattr(outcome, "worktree_name", "")).strip()
        if status == "launched" and worktree_name:
            launched_worktrees.append(worktree_name)
        elif status == "failed" and worktree_name:
            failed_worktrees.append(worktree_name)
    runtime._emit(
        "startup.plan_agent_launch_state",
        command=session.effective_route.command,
        mode=session.runtime_mode,
        status=str(getattr(launch_result, "status", "")).strip(),
        reason=str(getattr(launch_result, "reason", "")).strip(),
        launched_worktrees=launched_worktrees,
        failed_worktrees=failed_worktrees,
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
    if session.effective_route.command != "plan":
        return False
    if not session.plan_agent_launch_requested:
        return False
    launch_failed = str(getattr(launch_result, "status", "")).strip().lower() == "failed"
    return launch_failed and not session.plan_agent_attach_target


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
    transport = str(getattr(launch_config, "transport", "")).strip().lower()
    cli = str(getattr(launch_config, "cli", "")).strip().lower()
    if transport == "omx":
        return "OMX-managed Codex"
    if cli == "opencode":
        return "OpenCode"
    if cli == "codex":
        return "Codex"
    return "AI"


def plan_agent_launch_spinner_message(launch_config: object, *, count: int) -> str:
    label = plan_agent_launch_spinner_label(launch_config)
    noun = "session" if count == 1 else "sessions"
    return f"Launching {label} AI {noun}..."


def plan_agent_launch_spinner_success_message(launch_config: object, *, count: int) -> str:
    label = plan_agent_launch_spinner_label(launch_config)
    noun = "session" if count == 1 else "sessions"
    return f"{label} AI {noun} ready"


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
