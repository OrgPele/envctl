from __future__ import annotations

import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass
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
)
from envctl_engine.planning.plan_agent.terminal_screen import (
    _codex_queue_message_needs_tab,
    _codex_queue_screen_confirms_queued,
    _post_submit_screen_looks_accepted,
    _screen_excerpt,
    _screen_looks_ready,
)
from envctl_engine.planning.plan_agent.workflow_queue_support import (
    run_codex_workflow_queue,
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
LaunchTmuxCliBootstrapCommandsFn = Callable[..., tuple[str | None, ...] | list[str | None]]
WaitForTmuxCliReadyFn = Callable[..., AiCliReadyResult | None]
MaybeSubmitTmuxCodexGoalFn = Callable[..., str | None]
SubmitTmuxPromptWorkflowStepFn = Callable[..., str | None]
QueueTmuxCodexWorkflowStepsFn = Callable[..., str | None]
QueueFailureEventContextFn = Callable[[str], dict[str, object]]
WrapOmxInitialPromptForWorkflowFn = Callable[..., str]
SleepFn = Callable[[float], None]


@dataclass(frozen=True, slots=True)
class TmuxPromptBootstrapFlow:
    runtime: Any
    session_name: str
    window_name: str
    launch_config: PlanAgentLaunchConfig
    workflow: _PlanAgentWorkflow
    worktree: CreatedPlanWorktree
    transport: str
    wait_for_tmux_cli_ready: WaitForTmuxCliReadyFn
    format_ai_cli_ready_failure: FormatAiCliReadyFailureFn
    maybe_submit_tmux_codex_goal: MaybeSubmitTmuxCodexGoalFn
    workflow_step_prompt_text: WorkflowStepPromptTextFn
    wrap_initial_prompt: Callable[[str], str]
    submit_tmux_prompt_workflow_step: SubmitTmuxPromptWorkflowStepFn
    queue_tmux_codex_workflow_steps: QueueTmuxCodexWorkflowStepsFn
    queue_failure_event_context: QueueFailureEventContextFn
    queue_enabled: bool

    def run(self) -> str | None:
        ready_error = self._ready_error()
        if ready_error is not None:
            return ready_error
        goal_error = self._submit_goal()
        if goal_error is not None and goal_error != "codex_goal_ready_timeout":
            return goal_error
        if goal_error is None:
            ready_error = self._ready_error_after_goal()
            if ready_error is not None:
                return ready_error
        prompt_text, resolution_error = self.workflow_step_prompt_text(
            self.runtime,
            launch_config=self.launch_config,
            cli=self.launch_config.cli,
            step=self.workflow.steps[0],
            worktree=self.worktree,
        )
        if resolution_error is not None:
            return resolution_error
        submit_error = self.submit_tmux_prompt_workflow_step(
            self.runtime,
            session_name=self.session_name,
            window_name=self.window_name,
            prompt_text=self.wrap_initial_prompt(prompt_text),
            cli=self.launch_config.cli,
        )
        if submit_error is not None:
            return submit_error
        return self._queue_remaining_steps()

    def _ready_error(self) -> str | None:
        ready_result = self.wait_for_tmux_cli_ready(
            self.runtime,
            session_name=self.session_name,
            window_name=self.window_name,
            cli=self.launch_config.cli,
        )
        if ready_result is not None and not ready_result.ready:
            return self.format_ai_cli_ready_failure(ready_result)
        return None

    def _ready_error_after_goal(self) -> str | None:
        if not (self.launch_config.codex_goal_enable and self.launch_config.cli == "codex"):
            return None
        return self._ready_error()

    def _submit_goal(self) -> str | None:
        return self.maybe_submit_tmux_codex_goal(
            self.runtime,
            session_name=self.session_name,
            window_name=self.window_name,
            launch_config=self.launch_config,
            workflow=self.workflow,
            worktree=self.worktree,
            transport=self.transport,
        )

    def _queue_remaining_steps(self) -> str | None:
        queued_steps = self.workflow.steps[1:]
        if not (queued_steps and self.queue_enabled):
            return None
        queue_error_reason = self.queue_tmux_codex_workflow_steps(
            self.runtime,
            session_name=self.session_name,
            window_name=self.window_name,
            worktree=self.worktree,
            workflow=self.workflow,
            queued_steps=queued_steps,
            launch_config=self.launch_config,
            cli=self.launch_config.cli,
            transport=self.transport,
        )
        if queue_error_reason is None:
            return None
        self._emit_queue_fallback(queue_error_reason)
        return None

    def _emit_queue_fallback(self, queue_error_reason: str) -> None:
        failure_context = self.queue_failure_event_context(queue_error_reason)
        payload = {
            "session_name": self.session_name,
            "window_name": self.window_name,
            "worktree": self.worktree.name,
            "cli": self.launch_config.cli,
            "workflow_mode": self.workflow.mode,
            "codex_cycles": self.workflow.codex_cycles,
            "reason": queue_error_reason,
            "transport": self.transport,
            **failure_context,
        }
        self.runtime._emit("planning.agent_launch.workflow_queue_failed", **payload)
        self.runtime._emit("planning.agent_launch.workflow_fallback", **payload)


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


def run_existing_tmux_session_workflow(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
    wait_for_tmux_cli_ready_fn: WaitForTmuxCliReadyFn,
    format_ai_cli_ready_failure_fn: FormatAiCliReadyFailureFn,
    maybe_submit_tmux_codex_goal_fn: MaybeSubmitTmuxCodexGoalFn,
    workflow_step_prompt_text_fn: WorkflowStepPromptTextFn,
    wrap_omx_initial_prompt_for_workflow_fn: WrapOmxInitialPromptForWorkflowFn,
    submit_tmux_prompt_workflow_step_fn: SubmitTmuxPromptWorkflowStepFn,
    queue_tmux_codex_workflow_steps_fn: QueueTmuxCodexWorkflowStepsFn,
    queue_failure_event_context_fn: QueueFailureEventContextFn,
) -> str | None:
    return _run_tmux_prompt_bootstrap_flow(
        runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
        transport="omx",
        wait_for_tmux_cli_ready_fn=wait_for_tmux_cli_ready_fn,
        format_ai_cli_ready_failure_fn=format_ai_cli_ready_failure_fn,
        maybe_submit_tmux_codex_goal_fn=maybe_submit_tmux_codex_goal_fn,
        workflow_step_prompt_text_fn=workflow_step_prompt_text_fn,
        wrap_initial_prompt_fn=lambda text: wrap_omx_initial_prompt_for_workflow_fn(
            text,
            workflow=launch_config.omx_workflow,
        ),
        submit_tmux_prompt_workflow_step_fn=submit_tmux_prompt_workflow_step_fn,
        queue_tmux_codex_workflow_steps_fn=queue_tmux_codex_workflow_steps_fn,
        queue_failure_event_context_fn=queue_failure_event_context_fn,
        queue_enabled=(
            launch_config.cli == "codex"
            and (launch_config.transport != "omx" or workflow.codex_cycles > 0)
        ),
    )


def run_tmux_worktree_bootstrap(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
    launch_tmux_cli_bootstrap_commands_fn: LaunchTmuxCliBootstrapCommandsFn,
    wait_for_tmux_cli_ready_fn: WaitForTmuxCliReadyFn,
    format_ai_cli_ready_failure_fn: FormatAiCliReadyFailureFn,
    maybe_submit_tmux_codex_goal_fn: MaybeSubmitTmuxCodexGoalFn,
    workflow_step_prompt_text_fn: WorkflowStepPromptTextFn,
    submit_tmux_prompt_workflow_step_fn: SubmitTmuxPromptWorkflowStepFn,
    queue_tmux_codex_workflow_steps_fn: QueueTmuxCodexWorkflowStepsFn,
    queue_failure_event_context_fn: QueueFailureEventContextFn,
) -> str | None:
    send_errors = launch_tmux_cli_bootstrap_commands_fn(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cwd=worktree.root,
        cli_command=launch_config.cli_command,
    )
    for error in send_errors:
        if error is not None:
            return error
    return _run_tmux_prompt_bootstrap_flow(
        runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
        transport="tmux",
        wait_for_tmux_cli_ready_fn=wait_for_tmux_cli_ready_fn,
        format_ai_cli_ready_failure_fn=format_ai_cli_ready_failure_fn,
        maybe_submit_tmux_codex_goal_fn=maybe_submit_tmux_codex_goal_fn,
        workflow_step_prompt_text_fn=workflow_step_prompt_text_fn,
        wrap_initial_prompt_fn=lambda text: text,
        submit_tmux_prompt_workflow_step_fn=submit_tmux_prompt_workflow_step_fn,
        queue_tmux_codex_workflow_steps_fn=queue_tmux_codex_workflow_steps_fn,
        queue_failure_event_context_fn=queue_failure_event_context_fn,
        queue_enabled=launch_config.cli == "codex",
    )


def _run_tmux_prompt_bootstrap_flow(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
    transport: str,
    wait_for_tmux_cli_ready_fn: WaitForTmuxCliReadyFn,
    format_ai_cli_ready_failure_fn: FormatAiCliReadyFailureFn,
    maybe_submit_tmux_codex_goal_fn: MaybeSubmitTmuxCodexGoalFn,
    workflow_step_prompt_text_fn: WorkflowStepPromptTextFn,
    wrap_initial_prompt_fn: Callable[[str], str],
    submit_tmux_prompt_workflow_step_fn: SubmitTmuxPromptWorkflowStepFn,
    queue_tmux_codex_workflow_steps_fn: QueueTmuxCodexWorkflowStepsFn,
    queue_failure_event_context_fn: QueueFailureEventContextFn,
    queue_enabled: bool,
) -> str | None:
    return TmuxPromptBootstrapFlow(
        runtime=runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
        transport=transport,
        wait_for_tmux_cli_ready=wait_for_tmux_cli_ready_fn,
        format_ai_cli_ready_failure=format_ai_cli_ready_failure_fn,
        maybe_submit_tmux_codex_goal=maybe_submit_tmux_codex_goal_fn,
        workflow_step_prompt_text=workflow_step_prompt_text_fn,
        wrap_initial_prompt=wrap_initial_prompt_fn,
        submit_tmux_prompt_workflow_step=submit_tmux_prompt_workflow_step_fn,
        queue_tmux_codex_workflow_steps=queue_tmux_codex_workflow_steps_fn,
        queue_failure_event_context=queue_failure_event_context_fn,
        queue_enabled=queue_enabled,
    ).run()


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
