from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from envctl_engine.planning.plan_agent.models import (
    AiCliReadyResult,
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
)
from envctl_engine.planning.plan_agent.tmux_prompt_readiness_support import (
    wait_for_tmux_cli_ready,
    wait_for_tmux_prompt_accepted,
    wait_for_tmux_prompt_ready_after_goal,
)
from envctl_engine.planning.plan_agent.tmux_prompt_submission_support import (
    launch_tmux_cli_bootstrap_commands,
    maybe_submit_tmux_codex_goal,
    submit_tmux_codex_goal,
    submit_tmux_prompt_workflow_step,
)
from envctl_engine.planning.plan_agent.tmux_workflow_queue_support import (
    queue_tmux_codex_message,
    queue_tmux_codex_workflow_steps,
)

__all__ = [
    "TmuxPromptBootstrapFlow",
    "launch_tmux_cli_bootstrap_commands",
    "maybe_submit_tmux_codex_goal",
    "queue_tmux_codex_message",
    "queue_tmux_codex_workflow_steps",
    "run_existing_tmux_session_workflow",
    "run_tmux_worktree_bootstrap",
    "submit_tmux_codex_goal",
    "submit_tmux_prompt_workflow_step",
    "wait_for_tmux_cli_ready",
    "wait_for_tmux_prompt_accepted",
    "wait_for_tmux_prompt_ready_after_goal",
]


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
            launch_config.cli == "codex" and (launch_config.transport != "omx" or workflow.codex_cycles > 0)
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
