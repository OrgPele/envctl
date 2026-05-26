from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
    _PlanAgentWorkflowStep,
)
from envctl_engine.planning.plan_agent.workflow_queue_interaction import (
    CodexQueueMessageInteractor,
    Clock,
    Sleeper,
    wait_until_codex_queue_ready,
)
from envctl_engine.planning.plan_agent.workflow_bootstrap_commands import CliBootstrapCommandTyper
from envctl_engine.planning.plan_agent.workflow_queue_support import (
    run_codex_workflow_queue,
)


SendPromptTextFn = Callable[..., str | None]
SendSurfaceKeyFn = Callable[..., str | None]
PasteSurfaceTextFn = Callable[..., str | None]
ReadSurfaceScreenFn = Callable[..., str]
WaitForPromptReadyFn = Callable[..., None]
WorkflowStepPromptTextFn = Callable[..., tuple[str, str | None]]
QueueCodexMessageFn = Callable[..., bool]
CodexGoalTextForWorktreeFn = Callable[..., str]


def launch_cli_bootstrap_commands(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cwd: Path,
    cli_command: str,
    send_surface_text_fn: SendPromptTextFn,
    send_surface_key_fn: SendSurfaceKeyFn,
    failure_event: str = "planning.agent_launch.failed",
) -> list[str | None]:
    return CliBootstrapCommandTyper(
        send_text=lambda text: send_surface_text_fn(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            text=text,
            failure_event=failure_event,
        ),
        send_key=lambda key: send_surface_key_fn(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            key=key,
            failure_event=failure_event,
        ),
    ).type_bootstrap_commands(cwd=cwd, cli_command=cli_command)


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
    return run_codex_workflow_queue(
        runtime,
        worktree=worktree,
        workflow=workflow,
        queued_steps=queued_steps,
        launch_config=launch_config,
        cli=cli,
        transport="cmux",
        event_context={"workspace_id": workspace_id, "surface_id": surface_id},
        codex_goal_text_for_worktree_fn=codex_goal_text_for_worktree_fn,
        workflow_step_prompt_text_fn=workflow_step_prompt_text_fn,
        send_text_fn=lambda text: paste_surface_text_fn(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            text=text,
            emit_failure_event=False,
        ),
        queue_message_fn=lambda text, *, require_text_match=True: queue_codex_message_fn(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            text=text,
            require_text_match=require_text_match,
        ),
    )


def wait_for_codex_queue_ready(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    read_surface_screen_fn: ReadSurfaceScreenFn,
    monotonic: Clock | None = None,
    sleep: Sleeper | None = None,
) -> bool:
    wait_kwargs: dict[str, Any] = {}
    if monotonic is not None:
        wait_kwargs["monotonic"] = monotonic
    if sleep is not None:
        wait_kwargs["sleep"] = sleep
    return wait_until_codex_queue_ready(
        read_screen=lambda: read_surface_screen_fn(runtime, workspace_id=workspace_id, surface_id=surface_id),
        **wait_kwargs,
    )


def queue_codex_message(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    text: str,
    require_text_match: bool = True,
    read_surface_screen_fn: ReadSurfaceScreenFn,
    send_surface_key_fn: SendSurfaceKeyFn,
    monotonic: Clock | None = None,
    sleep: Sleeper | None = None,
) -> bool:
    interactor_kwargs: dict[str, Any] = {}
    if monotonic is not None:
        interactor_kwargs["monotonic"] = monotonic
    if sleep is not None:
        interactor_kwargs["sleep"] = sleep
    return CodexQueueMessageInteractor(
        read_screen=lambda: read_surface_screen_fn(runtime, workspace_id=workspace_id, surface_id=surface_id),
        send_key=lambda key: send_surface_key_fn(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            key=key,
            emit_failure_event=False,
        ),
        prompt_picker_enabled=True,
        **interactor_kwargs,
    ).queue_message(text, require_text_match=require_text_match)
