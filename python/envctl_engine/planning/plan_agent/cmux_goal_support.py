from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from envctl_engine.planning.plan_agent.constants import (
    _CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS,
    _CODEX_QUEUE_READY_TIMEOUT_SECONDS,
)
from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
)
from envctl_engine.planning.plan_agent.terminal_screen import _codex_goal_screen_looks_active


CodexGoalTextForWorktreeFn = Callable[..., str]
EmitCodexGoalEventFn = Callable[..., None]
SubmitSurfaceCodexGoalFn = Callable[..., str | None]
SubmitDirectPromptWorkflowStepFn = Callable[..., str | None]
WaitForSurfaceCodexGoalActiveFn = Callable[..., bool]
WaitForCodexQueueReadyFn = Callable[..., bool]
ReadSurfaceScreenFn = Callable[..., str]


def maybe_submit_surface_codex_goal(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
    codex_goal_text_for_worktree_fn: CodexGoalTextForWorktreeFn,
    submit_surface_codex_goal_fn: SubmitSurfaceCodexGoalFn,
    emit_codex_goal_event_fn: EmitCodexGoalEventFn,
) -> str | None:
    if launch_config.cli != "codex" or not launch_config.codex_goal_enable:
        return None
    goal_text = codex_goal_text_for_worktree_fn(
        worktree=worktree,
        preset=launch_config.preset,
        workflow_mode=workflow.mode,
        omx_workflow=launch_config.omx_workflow,
    )
    error = submit_surface_codex_goal_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        goal_text=goal_text,
    )
    if error is None:
        emit_codex_goal_event_fn(
            runtime,
            "planning.agent_launch.codex_goal_submitted",
            workspace_id=workspace_id,
            surface_id=surface_id,
            cli=launch_config.cli,
            workflow=workflow,
            transport="cmux",
            worktree=worktree,
        )
        return None
    if error == "codex_goal_ready_timeout":
        emit_codex_goal_event_fn(
            runtime,
            "planning.agent_launch.codex_goal_fallback",
            workspace_id=workspace_id,
            surface_id=surface_id,
            cli=launch_config.cli,
            workflow=workflow,
            transport="cmux",
            worktree=worktree,
            reason=error,
        )
        return error
    return error


def submit_surface_codex_goal(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    goal_text: str,
    submit_direct_prompt_workflow_step_fn: SubmitDirectPromptWorkflowStepFn,
    wait_for_surface_codex_goal_active_fn: WaitForSurfaceCodexGoalActiveFn,
    wait_for_codex_queue_ready_fn: WaitForCodexQueueReadyFn,
) -> str | None:
    submit_error = submit_direct_prompt_workflow_step_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        prompt_text=f"/goal {goal_text}",
    )
    if submit_error is not None:
        return submit_error
    if not wait_for_surface_codex_goal_active_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        goal_text=goal_text,
    ):
        return "codex_goal_active_timeout"
    if not wait_for_codex_queue_ready_fn(runtime, workspace_id=workspace_id, surface_id=surface_id):
        return "codex_goal_ready_timeout"
    return None


def wait_for_surface_codex_goal_active(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    goal_text: str,
    read_surface_screen_fn: ReadSurfaceScreenFn,
) -> bool:
    deadline = time.monotonic() + _CODEX_QUEUE_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        screen = read_surface_screen_fn(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if _codex_goal_screen_looks_active(screen, goal_text):
            return True
        time.sleep(_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS)
    return False
