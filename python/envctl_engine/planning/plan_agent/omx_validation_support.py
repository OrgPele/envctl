from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentAttachTarget,
    PlanAgentAttachValidation,
)


def validate_omx_attach_target(
    runtime: Any,
    attach_target: PlanAgentAttachTarget | None,
    *,
    worktree: CreatedPlanWorktree | None = None,
    transport: str = "",
    phase: str = "handoff",
    tmux_session_exists_fn: Callable[[Any, str], bool],
    tmux_display_message_succeeds_fn: Callable[[Any, str], tuple[bool, str]],
    attach_target_state_check_fn: Callable[..., tuple[bool | None, dict[str, object]]],
    omx_late_spawn_exit_reason_fn: Callable[..., str | None],
) -> PlanAgentAttachValidation:
    session_name = str(getattr(attach_target, "session_name", "") or "").strip() if attach_target else ""
    attach_command = " ".join(
        str(part).strip()
        for part in (getattr(attach_target, "attach_command", ()) if attach_target is not None else ())
        if str(part).strip()
    )
    worktree_root = Path(getattr(worktree, "root", "") or "") if worktree is not None else None
    worktree_name = str(getattr(worktree, "name", "") or "").strip() if worktree is not None else ""
    normalized_transport = str(transport).strip().lower()
    payload = {
        "session_name": session_name or None,
        "attach_command": attach_command or None,
        "worktree": worktree_name or None,
        "worktree_root": str(worktree_root.resolve(strict=False)) if worktree_root is not None else None,
        "transport": str(transport or "").strip() or None,
        "phase": str(phase or "").strip() or None,
    }
    if not session_name:
        reason = "omx_session_unavailable" if normalized_transport == "omx" else "attach_target_unavailable"
        runtime._emit("planning.agent_launch.attach_validation.failed", reason=reason, **payload)
        return PlanAgentAttachValidation(False, reason, session_name=session_name, attach_command=attach_command)
    if worktree_root is not None and not worktree_root.is_dir():
        reason = "worktree_removed_after_launch"
        runtime._emit("planning.agent_launch.worktree_missing_after_launch", reason=reason, **payload)
        runtime._emit("planning.agent_launch.attach_validation.failed", reason=reason, **payload)
        return PlanAgentAttachValidation(False, reason, session_name=session_name, attach_command=attach_command)
    try:
        session_exists = tmux_session_exists_fn(runtime, session_name)
    except OSError:
        session_exists = False
    if not session_exists:
        reason = "omx_attach_target_stale" if normalized_transport == "omx" else "attach_target_stale"
        runtime._emit("planning.agent_launch.attach_validation.failed", reason=reason, **payload)
        return PlanAgentAttachValidation(False, reason, session_name=session_name, attach_command=attach_command)
    try:
        pane_ok, pane_id = tmux_display_message_succeeds_fn(runtime, session_name)
    except OSError:
        pane_ok, pane_id = False, ""
    if not pane_ok:
        reason = "omx_session_unavailable" if normalized_transport == "omx" else "attach_target_unavailable"
        runtime._emit("planning.agent_launch.attach_validation.failed", reason=reason, **payload)
        return PlanAgentAttachValidation(False, reason, session_name=session_name, attach_command=attach_command)
    if normalized_transport == "omx":
        state_ok, state_diagnostics = attach_target_state_check_fn(
            runtime,
            session_name=session_name,
            worktree=worktree,
        )
        if state_ok is False:
            reason = "omx_attach_target_stale"
            runtime._emit(
                "planning.agent_launch.attach_validation.failed",
                reason=reason,
                **payload,
                **state_diagnostics,
            )
            return PlanAgentAttachValidation(False, reason, session_name=session_name, attach_command=attach_command)
        exit_reason = omx_late_spawn_exit_reason_fn(runtime, session_name=session_name, worktree=worktree)
        if exit_reason:
            runtime._emit("planning.agent_launch.attach_validation.failed", reason=exit_reason, **payload)
            return PlanAgentAttachValidation(
                False,
                exit_reason,
                session_name=session_name,
                attach_command=attach_command,
            )
    runtime._emit("planning.agent_launch.attach_validation.ok", pane_id=pane_id, **payload)
    return PlanAgentAttachValidation(True, "ok", session_name=session_name, attach_command=attach_command)


def omx_late_spawn_exit_reason(
    runtime: Any,
    *,
    session_name: str,
    worktree: CreatedPlanWorktree | None,
    retained_returncode_fn: Callable[[object], object],
    retained_event_payload_fn: Callable[..., dict[str, object]],
) -> str | None:
    retained = getattr(runtime, "_omx_spawn_processes", None)
    if not isinstance(retained, list):
        return None
    still_running: list[object] = []
    exited = False
    for record in retained:
        returncode = retained_returncode_fn(record)
        if returncode is None:
            still_running.append(record)
            continue
        exited = True
        runtime._emit(
            "planning.agent_launch.omx_spawn.exited_early",
            **retained_event_payload_fn(
                record,
                session_name=session_name,
                worktree=worktree,
                returncode=returncode,
            ),
        )
    retained[:] = still_running
    return "omx_session_exited" if exited else None
