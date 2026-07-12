from __future__ import annotations

from typing import Any

from envctl_engine.planning.plan_agent.constants import _OMX_WORKFLOW_KEYWORDS
from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
)


def _surface_respawn_command(launch_config: PlanAgentLaunchConfig, worktree: CreatedPlanWorktree) -> str:
    _ = worktree
    return launch_config.shell


def _wrap_omx_initial_prompt_for_workflow(text: str, *, workflow: str) -> str:
    normalized_workflow = str(workflow or "").strip().lower()
    if normalized_workflow not in _OMX_WORKFLOW_KEYWORDS:
        return text
    stripped = str(text).lstrip()
    prefix = f"${normalized_workflow}"
    if stripped == prefix or stripped.startswith(f"{prefix} ") or stripped.startswith(f"{prefix}\n"):
        return text
    return f"{prefix}\n\n{text}"


def _codex_goal_text_for_worktree(
    *,
    worktree: CreatedPlanWorktree,
    preset: str,
    workflow_mode: str,
    omx_workflow: str,
) -> str:
    _ = (worktree, preset, workflow_mode)
    lines = [
        "Implement MAIN_TASK.md end-to-end in this worktree.",
        "Read it first, update code/tests, run focused validation, then ship with `envctl ship -m \"<message>\"`.",
    ]
    normalized_omx = str(omx_workflow or "").strip().lower()
    if normalized_omx:
        lines.append(f"Keep ${normalized_omx} completion contract active.")
    return " ".join(lines)


def _emit_codex_goal_event(
    runtime: Any,
    event: str,
    *,
    cli: str,
    workflow: _PlanAgentWorkflow,
    transport: str,
    worktree: CreatedPlanWorktree,
    reason: str | None = None,
    **target: object,
) -> None:
    payload: dict[str, object] = {
        **target,
        "worktree": worktree.name,
        "cli": cli,
        "workflow_mode": workflow.mode,
        "codex_cycles": workflow.codex_cycles,
        "transport": transport,
    }
    if reason is not None:
        payload["reason"] = reason
    runtime._emit(event, **payload)
