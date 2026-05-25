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
)
from envctl_engine.planning.plan_agent.terminal_screen import (
    _codex_queue_message_needs_tab,
    _codex_queue_screen_confirms_queued,
)
from envctl_engine.planning.plan_agent.workflow_queue_support import run_codex_workflow_queue


SendTmuxKeyFn = Callable[..., str | None]
SendTmuxPromptFn = Callable[..., str | None]
ReadTmuxScreenFn = Callable[..., str]
WorkflowStepPromptTextFn = Callable[..., tuple[str, str | None]]
QueueTmuxCodexMessageFn = Callable[..., bool]
CodexGoalTextForWorktreeFn = Callable[..., str]


def queue_tmux_codex_workflow_steps(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    worktree: CreatedPlanWorktree,
    workflow: _PlanAgentWorkflow,
    queued_steps: tuple[_PlanAgentWorkflowStep, ...],
    launch_config: PlanAgentLaunchConfig,
    cli: str,
    transport: str = "tmux",
    codex_goal_text_for_worktree_fn: CodexGoalTextForWorktreeFn,
    workflow_step_prompt_text_fn: WorkflowStepPromptTextFn,
    send_tmux_prompt_fn: SendTmuxPromptFn,
    queue_tmux_codex_message_fn: QueueTmuxCodexMessageFn,
) -> str | None:
    return run_codex_workflow_queue(
        runtime,
        worktree=worktree,
        workflow=workflow,
        queued_steps=queued_steps,
        launch_config=launch_config,
        cli=cli,
        transport=transport,
        event_context={"session_name": session_name, "window_name": window_name},
        codex_goal_text_for_worktree_fn=codex_goal_text_for_worktree_fn,
        workflow_step_prompt_text_fn=workflow_step_prompt_text_fn,
        send_text_fn=lambda text: send_tmux_prompt_fn(
            runtime,
            session_name=session_name,
            window_name=window_name,
            text=text,
        ),
        queue_message_fn=lambda text, *, require_text_match=True: queue_tmux_codex_message_fn(
            runtime,
            session_name=session_name,
            window_name=window_name,
            text=text,
            require_text_match=require_text_match,
        ),
    )


def queue_tmux_codex_message(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    text: str,
    require_text_match: bool = True,
    read_tmux_screen_fn: ReadTmuxScreenFn,
    send_tmux_key_fn: SendTmuxKeyFn,
) -> bool:
    deadline = time.monotonic() + _CODEX_QUEUE_READY_TIMEOUT_SECONDS
    tab_attempts = 0
    while time.monotonic() < deadline:
        screen = read_tmux_screen_fn(runtime, session_name=session_name, window_name=window_name)
        if tab_attempts > 0 and _codex_queue_screen_confirms_queued(
            screen,
            text,
            require_text_match=require_text_match,
        ):
            return True
        if _codex_queue_message_needs_tab(screen, text, require_text_match=require_text_match):
            if tab_attempts >= _CODEX_QUEUE_MAX_TAB_ATTEMPTS:
                return False
            tab_error = send_tmux_key_fn(
                runtime,
                session_name=session_name,
                window_name=window_name,
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
