from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
    _PlanAgentWorkflowStep,
    _QueueFailure,
)


WorkflowStepPromptTextFn = Callable[..., tuple[str, str | None]]
CodexGoalTextForWorktreeFn = Callable[..., str]
SendQueueTextFn = Callable[[str], str | None]
QueueMessageFn = Callable[[str], bool]


def run_codex_workflow_queue(
    runtime: Any,
    *,
    worktree: CreatedPlanWorktree,
    workflow: _PlanAgentWorkflow,
    queued_steps: tuple[_PlanAgentWorkflowStep, ...],
    launch_config: PlanAgentLaunchConfig,
    cli: str,
    transport: str,
    event_context: Mapping[str, object],
    codex_goal_text_for_worktree_fn: CodexGoalTextForWorktreeFn,
    workflow_step_prompt_text_fn: WorkflowStepPromptTextFn,
    send_text_fn: Callable[[str], str | None],
    queue_message_fn: Callable[..., bool],
) -> str | None:
    for step_index, step in enumerate(queued_steps):
        if launch_config.codex_goal_enable and step.requires_goal:
            queued_goal_text = _queued_goal_text(
                worktree=worktree,
                workflow=workflow,
                launch_config=launch_config,
                codex_goal_text_for_worktree_fn=codex_goal_text_for_worktree_fn,
            )
            goal_error = _send_and_confirm_queue_message(
                text=queued_goal_text,
                send_text_fn=send_text_fn,
                queue_message_fn=queue_message_fn,
                send_failure="queue_goal_send_failed",
                ready_failure="queue_goal_not_ready",
                step_index=step_index,
                step_kind=step.kind,
            )
            if goal_error is not None:
                return goal_error

        queued_text, resolution_error = workflow_step_prompt_text_fn(
            runtime,
            launch_config=launch_config,
            cli=cli,
            step=step,
            worktree=worktree,
        )
        if resolution_error is not None:
            return _QueueFailure("queue_prompt_resolution_failed", step_index=step_index, step_kind=step.kind)

        prompt_error = _send_and_confirm_queue_message(
            text=queued_text,
            send_text_fn=send_text_fn,
            queue_message_fn=queue_message_fn,
            send_failure="queue_send_failed",
            ready_failure="queue_not_ready",
            step_index=step_index,
            step_kind=step.kind,
        )
        if prompt_error is not None:
            return prompt_error

    runtime._emit(
        "planning.agent_launch.workflow_queued",
        **dict(event_context),
        worktree=worktree.name,
        cli=cli,
        workflow_mode=workflow.mode,
        codex_cycles=workflow.codex_cycles,
        queued_steps=len(queued_steps),
        queued_steps_confirmed=len(queued_steps),
        transport=transport,
    )
    return None


def _queued_goal_text(
    *,
    worktree: CreatedPlanWorktree,
    workflow: _PlanAgentWorkflow,
    launch_config: PlanAgentLaunchConfig,
    codex_goal_text_for_worktree_fn: CodexGoalTextForWorktreeFn,
) -> str:
    goal_text = codex_goal_text_for_worktree_fn(
        worktree=worktree,
        preset=launch_config.preset,
        workflow_mode=workflow.mode,
        omx_workflow=launch_config.omx_workflow,
    )
    return f"/goal {goal_text}"


def _send_and_confirm_queue_message(
    *,
    text: str,
    send_text_fn: Callable[[str], str | None],
    queue_message_fn: Callable[..., bool],
    send_failure: str,
    ready_failure: str,
    step_index: int,
    step_kind: str,
) -> _QueueFailure | None:
    send_error = send_text_fn(text)
    if send_error is not None:
        return _QueueFailure(send_failure, step_index=step_index, step_kind=step_kind)
    if not queue_message_fn(text, require_text_match=False):
        return _QueueFailure(ready_failure, step_index=step_index, step_kind=step_kind)
    return None
