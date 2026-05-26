from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import (
    AiCliReadyResult,
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
)
from envctl_engine.planning.plan_agent.workflow_bootstrap_commands import CliBootstrapCommandTyper


SendTmuxTextFn = Callable[..., str | None]
SendTmuxKeyFn = Callable[..., str | None]
SendTmuxPromptFn = Callable[..., str | None]
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
    emit_failure_event = failure_event == "planning.agent_launch.failed"
    return CliBootstrapCommandTyper(
        send_text=lambda text: send_tmux_text_fn(
            runtime,
            session_name=session_name,
            window_name=window_name,
            text=text,
            emit_failure_event=emit_failure_event,
            failure_event=failure_event,
        ),
        send_key=lambda key: send_tmux_key_fn(
            runtime,
            session_name=session_name,
            window_name=window_name,
            key=key,
            emit_failure_event=emit_failure_event,
            failure_event=failure_event,
        ),
    ).type_bootstrap_commands(cwd=cwd, cli_command=cli_command)


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
