from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from envctl_engine.planning.plan_agent.constants import (
    _CODEX_QUEUE_MAX_TAB_ATTEMPTS,
    _CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS,
    _CODEX_QUEUE_READY_TIMEOUT_SECONDS,
)
from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
    _PlanAgentWorkflowStep,
    _QueueFailure,
)
from envctl_engine.planning.plan_agent.terminal_screen import (
    _codex_queue_message_needs_tab,
    _codex_queue_screen_confirms_queued,
    _codex_queue_screen_looks_ready,
    _prompt_picker_screen_looks_ready,
)


SendPromptTextFn = Callable[..., str | None]
SendSurfaceKeyFn = Callable[..., str | None]
PasteSurfaceTextFn = Callable[..., str | None]
ReadSurfaceScreenFn = Callable[..., str]
WaitForPromptReadyFn = Callable[..., None]
WorkflowStepPromptTextFn = Callable[..., tuple[str, str | None]]
QueueCodexMessageFn = Callable[..., bool]
CodexGoalTextForWorktreeFn = Callable[..., str]


def submit_prompt_workflow_step(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cli: str,
    prompt_text: str,
    failure_event: str = "planning.agent_launch.failed",
    send_prompt_text_fn: SendPromptTextFn,
    send_surface_key_fn: SendSurfaceKeyFn,
    wait_for_prompt_picker_ready_fn: WaitForPromptReadyFn,
    wait_for_prompt_submit_ready_fn: WaitForPromptReadyFn,
) -> str | None:
    failure_kwargs = {} if failure_event == "planning.agent_launch.failed" else {"failure_event": failure_event}
    final_errors = [
        send_prompt_text_fn(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            cli=cli,
            text=prompt_text,
            **failure_kwargs,
        ),
        send_surface_key_fn(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            key="ctrl+e",
            failure_event=failure_event,
        ),
    ]
    for error in final_errors:
        if error is not None:
            return error
    wait_for_prompt_picker_ready_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=cli,
        prompt_text=prompt_text,
    )
    submit_error = send_surface_key_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        key="enter",
        failure_event=failure_event,
    )
    if submit_error is not None:
        return submit_error
    wait_for_prompt_submit_ready_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=cli,
        prompt_text=prompt_text,
    )
    return send_surface_key_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        key="enter",
        failure_event=failure_event,
    )


def submit_direct_prompt_workflow_step(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    prompt_text: str,
    failure_event: str = "planning.agent_launch.failed",
    paste_surface_text_fn: PasteSurfaceTextFn,
    send_surface_key_fn: SendSurfaceKeyFn,
) -> str | None:
    paste_error = paste_surface_text_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        text=prompt_text,
        failure_event=failure_event,
    )
    if paste_error is not None:
        return paste_error
    return send_surface_key_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        key="enter",
        failure_event=failure_event,
    )


def queue_codex_workflow_steps(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    worktree: CreatedPlanWorktree,
    workflow: _PlanAgentWorkflow,
    queued_steps: tuple[_PlanAgentWorkflowStep, ...],
    launch_config: PlanAgentLaunchConfig,
    cli: str,
    workflow_step_prompt_text_fn: WorkflowStepPromptTextFn,
    codex_goal_text_for_worktree_fn: CodexGoalTextForWorktreeFn,
    paste_surface_text_fn: PasteSurfaceTextFn,
    queue_codex_message_fn: QueueCodexMessageFn,
) -> str | None:
    for step_index, step in enumerate(queued_steps):
        if launch_config.codex_goal_enable and step.requires_goal:
            goal_text = codex_goal_text_for_worktree_fn(
                worktree=worktree,
                preset=launch_config.preset,
                workflow_mode=workflow.mode,
                omx_workflow=launch_config.omx_workflow,
            )
            queued_goal_text = f"/goal {goal_text}"
            goal_send_error = paste_surface_text_fn(
                runtime,
                workspace_id=workspace_id,
                surface_id=surface_id,
                text=queued_goal_text,
                emit_failure_event=False,
            )
            if goal_send_error is not None:
                return _QueueFailure("queue_goal_send_failed", step_index=step_index, step_kind=step.kind)
            if not queue_codex_message_fn(
                runtime,
                workspace_id=workspace_id,
                surface_id=surface_id,
                text=queued_goal_text,
                require_text_match=False,
            ):
                return _QueueFailure("queue_goal_not_ready", step_index=step_index, step_kind=step.kind)
        queued_text, resolution_error = workflow_step_prompt_text_fn(
            runtime,
            launch_config=launch_config,
            cli=cli,
            step=step,
            worktree=worktree,
        )
        if resolution_error is not None:
            return _QueueFailure("queue_prompt_resolution_failed", step_index=step_index, step_kind=step.kind)
        send_error = paste_surface_text_fn(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            text=queued_text,
            emit_failure_event=False,
        )
        if send_error is not None:
            return _QueueFailure("queue_send_failed", step_index=step_index, step_kind=step.kind)
        if not queue_codex_message_fn(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            text=queued_text,
            require_text_match=False,
        ):
            return _QueueFailure("queue_not_ready", step_index=step_index, step_kind=step.kind)
    runtime._emit(
        "planning.agent_launch.workflow_queued",
        workspace_id=workspace_id,
        surface_id=surface_id,
        worktree=worktree.name,
        cli=cli,
        workflow_mode=workflow.mode,
        codex_cycles=workflow.codex_cycles,
        queued_steps=len(queued_steps),
        queued_steps_confirmed=len(queued_steps),
        transport="cmux",
    )
    return None


def wait_for_codex_queue_ready(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    read_surface_screen_fn: ReadSurfaceScreenFn,
) -> bool:
    deadline = time.monotonic() + _CODEX_QUEUE_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        screen = read_surface_screen_fn(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if _codex_queue_screen_looks_ready(screen):
            return True
        time.sleep(_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS)
    return False


def queue_codex_message(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    text: str,
    require_text_match: bool = True,
    read_surface_screen_fn: ReadSurfaceScreenFn,
    send_surface_key_fn: SendSurfaceKeyFn,
) -> bool:
    deadline = time.monotonic() + _CODEX_QUEUE_READY_TIMEOUT_SECONDS
    normalized_text = str(text).strip()
    picker_submitted = False
    tab_attempts = 0
    while time.monotonic() < deadline:
        screen = read_surface_screen_fn(runtime, workspace_id=workspace_id, surface_id=surface_id)
        if (
            normalized_text.startswith("/")
            and not picker_submitted
            and _prompt_picker_screen_looks_ready("codex", screen, normalized_text)
        ):
            submit_error = send_surface_key_fn(
                runtime,
                workspace_id=workspace_id,
                surface_id=surface_id,
                key="enter",
                emit_failure_event=False,
            )
            if submit_error is not None:
                return False
            picker_submitted = True
            time.sleep(_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS)
            continue
        if tab_attempts > 0 and _codex_queue_screen_confirms_queued(
            screen,
            text,
            require_text_match=require_text_match,
        ):
            return True
        if _codex_queue_message_needs_tab(screen, text, require_text_match=require_text_match):
            if tab_attempts >= _CODEX_QUEUE_MAX_TAB_ATTEMPTS:
                return False
            tab_error = send_surface_key_fn(
                runtime,
                workspace_id=workspace_id,
                surface_id=surface_id,
                key="tab",
                emit_failure_event=False,
            )
            if tab_error is not None:
                return False
            tab_attempts += 1
            time.sleep(_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS)
            continue
        time.sleep(_CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS)
    return False
