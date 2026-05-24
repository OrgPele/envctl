from __future__ import annotations

import shlex
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.constants import (
    _CLI_READY_POLL_INTERVAL_SECONDS,
    _CODEX_QUEUE_MAX_TAB_ATTEMPTS,
    _CODEX_QUEUE_READY_POLL_INTERVAL_SECONDS,
    _CODEX_QUEUE_READY_TIMEOUT_SECONDS,
    _PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS,
    _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS,
)
from envctl_engine.planning.plan_agent.models import (
    AiCliReadyResult,
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
    _PlanAgentWorkflowStep,
    _QueueFailure,
)
from envctl_engine.planning.plan_agent.terminal_screen import (
    _codex_queue_message_needs_tab,
    _codex_queue_screen_confirms_queued,
    _post_submit_screen_looks_accepted,
    _screen_excerpt,
    _screen_looks_ready,
)


SendTmuxTextFn = Callable[..., str | None]
SendTmuxKeyFn = Callable[..., str | None]
SendTmuxPromptFn = Callable[..., str | None]
ReadTmuxScreenFn = Callable[..., str]
WorkflowStepPromptTextFn = Callable[..., tuple[str, str | None]]
QueueTmuxCodexMessageFn = Callable[..., bool]
CodexGoalTextForWorktreeFn = Callable[..., str]
SubmitTmuxCodexGoalFn = Callable[..., str | None]
EmitCodexGoalEventFn = Callable[..., None]
WaitForTmuxPromptAcceptedFn = Callable[..., AiCliReadyResult]
WaitForTmuxPromptReadyAfterGoalFn = Callable[..., bool]
FormatAiCliReadyFailureFn = Callable[[AiCliReadyResult], str]
SleepFn = Callable[[float], None]


def launch_tmux_cli_bootstrap_commands(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    cwd: Path,
    cli_command: str,
    failure_event: str = "planning.agent_launch.failed",
    send_tmux_text_fn: SendTmuxTextFn,
    send_tmux_key_fn: SendTmuxKeyFn,
) -> list[str | None]:
    typed_root = shlex.quote(str(cwd))
    emit_failure_event = failure_event == "planning.agent_launch.failed"
    return [
        send_tmux_text_fn(
            runtime,
            session_name=session_name,
            window_name=window_name,
            text=f"cd {typed_root}",
            emit_failure_event=emit_failure_event,
            failure_event=failure_event,
        ),
        send_tmux_key_fn(
            runtime,
            session_name=session_name,
            window_name=window_name,
            key="enter",
            emit_failure_event=emit_failure_event,
            failure_event=failure_event,
        ),
        send_tmux_text_fn(
            runtime,
            session_name=session_name,
            window_name=window_name,
            text=cli_command,
            emit_failure_event=emit_failure_event,
            failure_event=failure_event,
        ),
        send_tmux_key_fn(
            runtime,
            session_name=session_name,
            window_name=window_name,
            key="enter",
            emit_failure_event=emit_failure_event,
            failure_event=failure_event,
        ),
    ]


def wait_for_tmux_cli_ready(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    cli: str,
    timeout_seconds: float,
    read_tmux_screen_fn: ReadTmuxScreenFn,
) -> AiCliReadyResult:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli not in {"codex", "opencode"}:
        time.sleep(timeout_seconds)
        return AiCliReadyResult(ready=True, reason="unsupported_cli_assumed_ready")
    deadline = time.monotonic() + timeout_seconds
    last_screen = ""
    while time.monotonic() < deadline:
        last_screen = read_tmux_screen_fn(runtime, session_name=session_name, window_name=window_name)
        if _screen_looks_ready(normalized_cli, last_screen):
            return AiCliReadyResult(ready=True, reason="ready", screen_excerpt=_screen_excerpt(last_screen))
        time.sleep(_CLI_READY_POLL_INTERVAL_SECONDS)
    return AiCliReadyResult(
        ready=False,
        reason=f"{normalized_cli}_ready_timeout",
        screen_excerpt=_screen_excerpt(last_screen),
    )


def maybe_submit_tmux_codex_goal(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
    transport: str,
    codex_goal_text_for_worktree_fn: CodexGoalTextForWorktreeFn,
    submit_tmux_codex_goal_fn: SubmitTmuxCodexGoalFn,
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
    error = submit_tmux_codex_goal_fn(
        runtime,
        session_name=session_name,
        window_name=window_name,
        goal_text=goal_text,
    )
    if error is None:
        emit_codex_goal_event_fn(
            runtime,
            "planning.agent_launch.codex_goal_submitted",
            session_name=session_name,
            window_name=window_name,
            cli=launch_config.cli,
            workflow=workflow,
            transport=transport,
            worktree=worktree,
        )
        return None
    if error == "codex_goal_ready_timeout":
        emit_codex_goal_event_fn(
            runtime,
            "planning.agent_launch.codex_goal_fallback",
            session_name=session_name,
            window_name=window_name,
            cli=launch_config.cli,
            workflow=workflow,
            transport=transport,
            worktree=worktree,
            reason=error,
        )
        return error
    return error


def submit_tmux_codex_goal(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    goal_text: str,
    submit_tmux_prompt_workflow_step_fn: SendTmuxPromptFn,
    wait_for_tmux_prompt_ready_after_goal_fn: WaitForTmuxPromptReadyAfterGoalFn,
) -> str | None:
    submit_error = submit_tmux_prompt_workflow_step_fn(
        runtime,
        session_name=session_name,
        window_name=window_name,
        prompt_text=f"/goal {goal_text}",
        cli="codex",
    )
    if submit_error is not None:
        return submit_error
    if not wait_for_tmux_prompt_ready_after_goal_fn(runtime, session_name=session_name, window_name=window_name):
        return "codex_goal_ready_timeout"
    return None


def wait_for_tmux_prompt_ready_after_goal(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    read_tmux_screen_fn: ReadTmuxScreenFn,
) -> bool:
    deadline = time.monotonic() + _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        screen = read_tmux_screen_fn(runtime, session_name=session_name, window_name=window_name)
        if _screen_looks_ready("codex", screen):
            return True
        time.sleep(_PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS)
    return False


def submit_tmux_prompt_workflow_step(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    prompt_text: str,
    cli: str = "",
    send_tmux_prompt_fn: SendTmuxPromptFn,
    send_tmux_key_fn: SendTmuxKeyFn,
    wait_for_tmux_prompt_accepted_fn: WaitForTmuxPromptAcceptedFn,
    format_ai_cli_ready_failure_fn: FormatAiCliReadyFailureFn,
    sleep_fn: SleepFn = time.sleep,
) -> str | None:
    paste_error = send_tmux_prompt_fn(runtime, session_name=session_name, window_name=window_name, text=prompt_text)
    if paste_error is not None:
        return paste_error
    if str(cli).strip().lower() == "opencode":
        sleep_fn(1.0)
    enter_error = send_tmux_key_fn(runtime, session_name=session_name, window_name=window_name, key="enter")
    if enter_error is not None:
        return enter_error
    accepted = wait_for_tmux_prompt_accepted_fn(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cli=cli,
        prompt_text=prompt_text,
    )
    if not accepted.ready:
        return format_ai_cli_ready_failure_fn(accepted)
    return None


def wait_for_tmux_prompt_accepted(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    cli: str,
    prompt_text: str,
    read_tmux_screen_fn: ReadTmuxScreenFn,
) -> AiCliReadyResult:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli != "opencode":
        return AiCliReadyResult(ready=True, reason="post_submit_check_not_required")
    deadline = time.monotonic() + _PROMPT_SUBMIT_READY_TIMEOUT_SECONDS
    last_screen = ""
    while time.monotonic() < deadline:
        last_screen = read_tmux_screen_fn(runtime, session_name=session_name, window_name=window_name)
        if _post_submit_screen_looks_accepted(normalized_cli, last_screen, prompt_text):
            return AiCliReadyResult(ready=True, reason="prompt_accepted", screen_excerpt=_screen_excerpt(last_screen))
        time.sleep(_PROMPT_SUBMIT_READY_POLL_INTERVAL_SECONDS)
    return AiCliReadyResult(
        ready=False,
        reason="opencode_prompt_accept_timeout",
        screen_excerpt=_screen_excerpt(last_screen),
    )


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
    for step_index, step in enumerate(queued_steps):
        if launch_config.codex_goal_enable and step.requires_goal:
            goal_text = codex_goal_text_for_worktree_fn(
                worktree=worktree,
                preset=launch_config.preset,
                workflow_mode=workflow.mode,
                omx_workflow=launch_config.omx_workflow,
            )
            queued_goal_text = f"/goal {goal_text}"
            goal_send_error = send_tmux_prompt_fn(
                runtime,
                session_name=session_name,
                window_name=window_name,
                text=queued_goal_text,
            )
            if goal_send_error is not None:
                return _QueueFailure("queue_goal_send_failed", step_index=step_index, step_kind=step.kind)
            if not queue_tmux_codex_message_fn(
                runtime,
                session_name=session_name,
                window_name=window_name,
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
        send_error = send_tmux_prompt_fn(
            runtime,
            session_name=session_name,
            window_name=window_name,
            text=queued_text,
        )
        if send_error is not None:
            return _QueueFailure("queue_send_failed", step_index=step_index, step_kind=step.kind)
        if not queue_tmux_codex_message_fn(
            runtime,
            session_name=session_name,
            window_name=window_name,
            text=queued_text,
            require_text_match=False,
        ):
            return _QueueFailure("queue_not_ready", step_index=step_index, step_kind=step.kind)
    runtime._emit(
        "planning.agent_launch.workflow_queued",
        session_name=session_name,
        window_name=window_name,
        worktree=worktree.name,
        cli=cli,
        workflow_mode=workflow.mode,
        codex_cycles=workflow.codex_cycles,
        queued_steps=len(queued_steps),
        queued_steps_confirmed=len(queued_steps),
        transport=transport,
    )
    return None


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
