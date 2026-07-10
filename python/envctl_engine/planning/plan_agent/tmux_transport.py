from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Mapping

from envctl_engine.runtime.codex_tmux_support import (
    _attach_interactive,
    _completed_process_error_text as _tmux_completed_process_error_text,
    _run_probe as _run_tmux_probe,
    _tmux_session_exists,
)

from envctl_engine.planning.plan_agent.config import _cli_ready_delay_seconds, _guidance_attach_command
from envctl_engine.planning.plan_agent.constants import (
    _TMUX_WINDOW_READY_POLL_INTERVAL_SECONDS,
    _TMUX_WINDOW_READY_TIMEOUT_SECONDS,
)
from envctl_engine.planning.plan_agent.models import (
    AiCliReadyResult,
    CreatedPlanWorktree,
    PlanAgentAttachTarget,
    PlanAgentLaunchConfig,
    PlanAgentLaunchOutcome,
    PlanAgentLaunchResult,
    _PlanAgentWorkflow,
    _PlanAgentWorkflowStep,
)
from envctl_engine.planning.plan_agent.recovery import (
    _new_session_command_for_route,
    _persist_runtime_events_snapshot,
    _print_launch_summary,
    _queue_failure_event_context,
    _summarize_failed_launch_outcomes,
)
from envctl_engine.planning.plan_agent.terminal_screen import (
    _format_ai_cli_ready_failure,
    _screen_excerpt,
    _screen_looks_active,
    _screen_looks_ready,
)
from envctl_engine.planning.plan_agent.tmux_session import (
    _prompt_existing_tmux_session_action,
    _should_prompt_existing_tmux_session,
)
from envctl_engine.planning.plan_agent.workflow_runtime_support import (
    _codex_goal_text_for_worktree,
    _emit_codex_goal_event,
    _wrap_omx_initial_prompt_for_workflow,
)
from envctl_engine.planning.plan_agent.workflow_prompt_support import _workflow_step_prompt_text
from envctl_engine.planning.plan_agent.tmux_identity_support import (
    next_available_tmux_session_name as _next_available_tmux_session_name,
    tmux_session_name_for_worktree as _tmux_session_name_for_worktree,
    tmux_window_name_for_worktree as _tmux_window_name_for_worktree,
)
import envctl_engine.planning.plan_agent.tmux_workflow_submission_support as tmux_workflow_submission_support
import envctl_engine.planning.plan_agent.tmux_surface_support as tmux_surface_support
import envctl_engine.planning.plan_agent.tmux_attach_support as tmux_attach_support
import envctl_engine.planning.plan_agent.tmux_window_support as tmux_window_support
import envctl_engine.planning.plan_agent.tmux_health_support as tmux_health_support
import envctl_engine.planning.plan_agent.tmux_worktree_launch_support as tmux_worktree_launch_support
import envctl_engine.planning.plan_agent.tmux_launch_support as tmux_launch_support

_tmux_target = tmux_surface_support.tmux_target
_run_tmux_command = tmux_surface_support.run_tmux_command
_send_tmux_text = tmux_surface_support.send_tmux_text
_send_tmux_key = tmux_surface_support.send_tmux_key
_read_tmux_screen = tmux_surface_support.read_tmux_screen
_send_tmux_prompt = tmux_surface_support.send_tmux_prompt


def _launch_plan_agent_tmux_terminals(
    runtime: Any,
    *,
    route: object,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    base_payload: Mapping[str, object],
    prompt_on_existing: bool,
) -> PlanAgentLaunchResult:
    return tmux_launch_support.launch_tmux_terminals(
        runtime,
        route=route,
        launch_config=launch_config,
        workflow=workflow,
        created_worktrees=created_worktrees,
        base_payload=base_payload,
        prompt_on_existing=prompt_on_existing,
        should_prompt_existing_session_fn=_should_prompt_existing_tmux_session,
        prompt_existing_session_action_fn=_prompt_existing_tmux_session_action,
        find_existing_attach_target_fn=_find_existing_tmux_attach_target,
        new_session_command_for_route_fn=_new_session_command_for_route,
        tmux_session_name_for_worktree_fn=_tmux_session_name_for_worktree,
        next_available_tmux_session_name_fn=_next_available_tmux_session_name,
        tmux_window_name_for_worktree_fn=_tmux_window_name_for_worktree,
        launch_single_tmux_worktree_fn=_launch_single_tmux_worktree,
        guidance_attach_command_fn=_guidance_attach_command,
        summarize_failed_launch_outcomes_fn=_summarize_failed_launch_outcomes,
        print_launch_summary_fn=_print_launch_summary,
    )


def _launch_single_tmux_worktree(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
) -> PlanAgentLaunchOutcome:
    return tmux_worktree_launch_support.launch_single_tmux_worktree(
        runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
        ensure_tmux_window_fn=_ensure_tmux_window,
        run_tmux_worktree_bootstrap_fn=_run_tmux_worktree_bootstrap,
        persist_runtime_events_snapshot_fn=_persist_runtime_events_snapshot,
    )


def _enable_tmux_mouse_scrollback(runtime: Any, *, session_name: str) -> str | None:
    return tmux_window_support.enable_tmux_mouse_scrollback(
        runtime,
        session_name=session_name,
        run_tmux_probe_fn=_run_tmux_probe,
        completed_process_error_text_fn=_tmux_completed_process_error_text,
    )


def _wait_for_tmux_window_ready(runtime: Any, *, session_name: str, window_name: str) -> str | None:
    return tmux_window_support.wait_for_tmux_window_ready(
        runtime,
        session_name=session_name,
        window_name=window_name,
        tmux_window_exists_fn=_tmux_window_exists,
        monotonic_fn=time.monotonic,
        sleep_fn=time.sleep,
        timeout_seconds=_TMUX_WINDOW_READY_TIMEOUT_SECONDS,
        poll_interval_seconds=_TMUX_WINDOW_READY_POLL_INTERVAL_SECONDS,
    )


def _tmux_window_exists(runtime: Any, *, session_name: str, window_name: str) -> bool:
    return tmux_window_support.tmux_window_exists(
        runtime,
        session_name=session_name,
        window_name=window_name,
        run_tmux_probe_fn=_run_tmux_probe,
    )


def _resolve_tmux_attach_target(
    runtime: Any,
    *,
    repo_root: Path,
    session_name: str,
    window_name: str | None,
    attach_via: str,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    cli: str,
) -> PlanAgentAttachTarget | None:
    return tmux_attach_support.resolve_tmux_attach_target(
        runtime=runtime,
        repo_root=repo_root,
        session_name=session_name,
        window_name=window_name,
        attach_via=attach_via,
        created_worktrees=created_worktrees,
        cli=cli,
        find_existing_attach_target_fn=_find_existing_tmux_attach_target,
        tmux_session_exists_fn=_tmux_session_exists,
        tmux_window_exists_fn=_tmux_window_exists,
        guidance_attach_command_fn=_guidance_attach_command,
    )


def _find_existing_tmux_attach_target(
    runtime: Any,
    *,
    repo_root: Path,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
    cli: str,
) -> PlanAgentAttachTarget | None:
    return tmux_attach_support.find_existing_tmux_attach_target(
        runtime=runtime,
        repo_root=repo_root,
        created_worktrees=created_worktrees,
        cli=cli,
        session_name_for_worktree_fn=_tmux_session_name_for_worktree,
        window_name_for_worktree_fn=_tmux_window_name_for_worktree,
        tmux_session_exists_fn=_tmux_session_exists,
        run_tmux_probe_fn=_run_tmux_probe,
        existing_session_health_fn=_existing_tmux_session_health,
        format_ai_cli_ready_failure_fn=_format_ai_cli_ready_failure,
        guidance_attach_command_fn=_guidance_attach_command,
    )


def _existing_tmux_session_looks_healthy(runtime: Any, *, session_name: str, window_name: str, cli: str) -> bool:
    return tmux_health_support.existing_tmux_session_looks_healthy(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cli=cli,
        existing_session_health_fn=_existing_tmux_session_health,
    )


def _existing_tmux_session_health(runtime: Any, *, session_name: str, window_name: str, cli: str) -> AiCliReadyResult:
    return tmux_health_support.existing_tmux_session_health(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cli=cli,
        read_tmux_screen_fn=_read_tmux_screen,
        screen_looks_ready_fn=_screen_looks_ready,
        screen_looks_active_fn=_screen_looks_active,
        screen_excerpt_fn=_screen_excerpt,
    )


def _run_tmux_existing_session_workflow(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
) -> str | None:
    return tmux_workflow_submission_support.run_existing_tmux_session_workflow(
        runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
        wait_for_tmux_cli_ready_fn=_wait_for_tmux_cli_ready,
        format_ai_cli_ready_failure_fn=_format_ai_cli_ready_failure,
        maybe_submit_tmux_codex_goal_fn=_maybe_submit_tmux_codex_goal,
        workflow_step_prompt_text_fn=_workflow_step_prompt_text,
        wrap_omx_initial_prompt_for_workflow_fn=_wrap_omx_initial_prompt_for_workflow,
        submit_tmux_prompt_workflow_step_fn=_submit_tmux_prompt_workflow_step,
        queue_tmux_codex_workflow_steps_fn=_queue_tmux_codex_workflow_steps,
        queue_failure_event_context_fn=_queue_failure_event_context,
    )


def _maybe_submit_tmux_codex_goal(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
    transport: str,
) -> str | None:
    return tmux_workflow_submission_support.maybe_submit_tmux_codex_goal(
        runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
        transport=transport,
        codex_goal_text_for_worktree_fn=_codex_goal_text_for_worktree,
        submit_tmux_codex_goal_fn=_submit_tmux_codex_goal,
        emit_codex_goal_event_fn=_emit_codex_goal_event,
    )


def _submit_tmux_codex_goal(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    goal_text: str,
) -> str | None:
    return tmux_workflow_submission_support.submit_tmux_codex_goal(
        runtime,
        session_name=session_name,
        window_name=window_name,
        goal_text=goal_text,
        submit_tmux_prompt_workflow_step_fn=_submit_tmux_prompt_workflow_step,
        wait_for_tmux_prompt_ready_after_goal_fn=_wait_for_tmux_prompt_ready_after_goal,
    )


def _wait_for_tmux_prompt_ready_after_goal(runtime: Any, *, session_name: str, window_name: str) -> bool:
    return tmux_workflow_submission_support.wait_for_tmux_prompt_ready_after_goal(
        runtime,
        session_name=session_name,
        window_name=window_name,
        read_tmux_screen_fn=_read_tmux_screen,
    )


def _launch_tmux_cli_bootstrap_commands(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    cwd: Path,
    cli_command: str,
    failure_event: str = "planning.agent_launch.failed",
) -> list[str | None]:
    return tmux_workflow_submission_support.launch_tmux_cli_bootstrap_commands(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cwd=cwd,
        cli_command=cli_command,
        failure_event=failure_event,
        send_tmux_text_fn=_send_tmux_text,
        send_tmux_key_fn=_send_tmux_key,
    )


def _wait_for_tmux_cli_ready(runtime: Any, *, session_name: str, window_name: str, cli: str) -> AiCliReadyResult:
    normalized_cli = str(cli).strip().lower()
    timeout_seconds = _cli_ready_delay_seconds(normalized_cli)
    return tmux_workflow_submission_support.wait_for_tmux_cli_ready(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cli=cli,
        timeout_seconds=timeout_seconds,
        read_tmux_screen_fn=_read_tmux_screen,
    )


def _submit_tmux_prompt_workflow_step(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    prompt_text: str,
    cli: str = "",
) -> str | None:
    return tmux_workflow_submission_support.submit_tmux_prompt_workflow_step(
        runtime,
        session_name=session_name,
        window_name=window_name,
        prompt_text=prompt_text,
        cli=cli,
        send_tmux_prompt_fn=_send_tmux_prompt,
        send_tmux_key_fn=_send_tmux_key,
        wait_for_tmux_prompt_accepted_fn=_wait_for_tmux_prompt_accepted,
        format_ai_cli_ready_failure_fn=_format_ai_cli_ready_failure,
    )


def _wait_for_tmux_prompt_accepted(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    cli: str,
    prompt_text: str,
) -> AiCliReadyResult:
    return tmux_workflow_submission_support.wait_for_tmux_prompt_accepted(
        runtime,
        session_name=session_name,
        window_name=window_name,
        cli=cli,
        prompt_text=prompt_text,
        read_tmux_screen_fn=_read_tmux_screen,
    )


def _run_tmux_worktree_bootstrap(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
) -> str | None:
    return tmux_workflow_submission_support.run_tmux_worktree_bootstrap(
        runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
        launch_tmux_cli_bootstrap_commands_fn=_launch_tmux_cli_bootstrap_commands,
        wait_for_tmux_cli_ready_fn=_wait_for_tmux_cli_ready,
        format_ai_cli_ready_failure_fn=_format_ai_cli_ready_failure,
        maybe_submit_tmux_codex_goal_fn=_maybe_submit_tmux_codex_goal,
        workflow_step_prompt_text_fn=_workflow_step_prompt_text,
        submit_tmux_prompt_workflow_step_fn=_submit_tmux_prompt_workflow_step,
        queue_tmux_codex_workflow_steps_fn=_queue_tmux_codex_workflow_steps,
        queue_failure_event_context_fn=_queue_failure_event_context,
    )


def _queue_tmux_codex_workflow_steps(
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
) -> str | None:
    return tmux_workflow_submission_support.queue_tmux_codex_workflow_steps(
        runtime,
        session_name=session_name,
        window_name=window_name,
        worktree=worktree,
        workflow=workflow,
        queued_steps=queued_steps,
        launch_config=launch_config,
        cli=cli,
        transport=transport,
        codex_goal_text_for_worktree_fn=_codex_goal_text_for_worktree,
        workflow_step_prompt_text_fn=_workflow_step_prompt_text,
        send_tmux_prompt_fn=_send_tmux_prompt,
        queue_tmux_codex_message_fn=_queue_tmux_codex_message,
    )


def _queue_tmux_codex_message(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    text: str,
    require_text_match: bool = True,
) -> bool:
    return tmux_workflow_submission_support.queue_tmux_codex_message(
        runtime,
        session_name=session_name,
        window_name=window_name,
        text=text,
        require_text_match=require_text_match,
        read_tmux_screen_fn=_read_tmux_screen,
        send_tmux_key_fn=_send_tmux_key,
    )


def attach_plan_agent_terminal(runtime: Any, attach_target: PlanAgentAttachTarget) -> int:
    if attach_target.attach_via == "switch-client":
        result = _run_tmux_probe(
            runtime,
            ("tmux", "switch-client", "-t", attach_target.session_name),
            cwd=attach_target.repo_root,
        )
        if result.returncode != 0:
            print(_tmux_completed_process_error_text(result), file=sys.stderr)
            return 1
        return 0
    return _attach_interactive(runtime, attach_target.attach_command, cwd=attach_target.repo_root)


def _ensure_tmux_window(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
) -> str | None:
    return tmux_window_support.ensure_tmux_window(
        runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        worktree=worktree,
        tmux_session_exists_fn=_tmux_session_exists,
        run_tmux_probe_fn=_run_tmux_probe,
        completed_process_error_text_fn=_tmux_completed_process_error_text,
        enable_mouse_scrollback_fn=_enable_tmux_mouse_scrollback,
        wait_for_window_ready_fn=_wait_for_tmux_window_ready,
    )


__all__ = tuple(name for name in globals() if not name.startswith("__"))
