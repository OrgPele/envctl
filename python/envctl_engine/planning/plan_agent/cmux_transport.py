from __future__ import annotations

import threading
from pathlib import Path
import time  # noqa: F401  # Re-exported for legacy tests that patch cmux_transport.time.
from typing import Any

from envctl_engine.planning.plan_agent.config import (
    _cli_ready_delay_seconds,
    _missing_launch_commands,
    _uses_direct_submission,
    resolve_plan_agent_launch_config,
)
from envctl_engine.planning.plan_agent.models import (
    AgentTerminalLaunchResult,
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    PlanAgentLaunchOutcome,
    ReviewAgentLaunchReadiness,
    _PlanAgentWorkflow,
    _PlanAgentWorkflowStep,
)
from envctl_engine.planning.plan_agent.recovery import (
    _persist_runtime_events_snapshot,
    _print_launch_summary,
    _queue_failure_event_context,
)
from envctl_engine.planning.plan_agent.workflow import (
    _codex_goal_text_for_worktree,
    _emit_codex_goal_event,
    _review_original_plan_path,
    _review_prompt_arguments,
    _surface_respawn_command,
)
from envctl_engine.planning.plan_agent.workflow_build import (
    _build_plan_agent_workflow,
    _tab_title_for_worktree,
)
from envctl_engine.planning.plan_agent.workflow_prompt_support import (
    _resolve_preset_submission_text,
    _workflow_step_prompt_text,
)

import envctl_engine.planning.plan_agent.cmux_workspace_support as cmux_workspace_support
import envctl_engine.planning.plan_agent.cmux_surface_support as cmux_surface_support
import envctl_engine.planning.plan_agent.cmux_workflow_submission_support as cmux_workflow_submission_support
import envctl_engine.planning.plan_agent.cmux_goal_support as cmux_goal_support
import envctl_engine.planning.plan_agent.cmux_bootstrap_support as cmux_bootstrap_support
import envctl_engine.planning.plan_agent.cmux_worktree_launch_support as cmux_worktree_launch_support
import envctl_engine.planning.plan_agent.cmux_review_launch_support as cmux_review_launch_support


def review_agent_launch_readiness(runtime: Any) -> ReviewAgentLaunchReadiness:
    return cmux_review_launch_support.resolve_review_agent_launch_readiness(
        runtime,
        resolve_launch_config_fn=resolve_plan_agent_launch_config,
        missing_launch_commands_fn=_missing_launch_commands,
        default_target_workspace_title_fn=_default_target_workspace_title,
        missing_required_cmux_context_fn=_missing_required_cmux_context,
    )


def launch_review_agent_terminal(
    runtime: Any,
    *,
    repo_root: Path,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None = None,
) -> AgentTerminalLaunchResult:
    return cmux_review_launch_support.launch_cmux_review_agent_terminal(
        runtime,
        repo_root=repo_root,
        project_name=project_name,
        project_root=project_root,
        review_bundle_path=review_bundle_path,
        resolve_launch_config_fn=resolve_plan_agent_launch_config,
        missing_launch_commands_fn=_missing_launch_commands,
        ensure_workspace_id_fn=_ensure_workspace_id,
        missing_required_cmux_context_fn=_missing_required_cmux_context,
        create_surface_fn=_create_surface,
        start_background_review_surface_bootstrap_fn=_start_background_review_surface_bootstrap,
        print_launch_summary_fn=_print_launch_summary,
    )


def _launch_single_worktree(
    runtime: Any,
    *,
    workspace_id: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
    starter_surface_id: str | None = None,
) -> PlanAgentLaunchOutcome:
    return cmux_worktree_launch_support.launch_single_worktree(
        runtime,
        workspace_id=workspace_id,
        launch_config=launch_config,
        worktree=worktree,
        starter_surface_id=starter_surface_id,
        create_surface_fn=_create_surface,
        start_background_surface_bootstrap_fn=_start_background_surface_bootstrap,
    )


def _start_background_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
) -> None:
    cmux_bootstrap_support.start_background_surface_bootstrap(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        launch_config=launch_config,
        worktree=worktree,
        complete_surface_bootstrap_fn=_complete_surface_bootstrap,
        thread_factory=threading.Thread,
    )


def _start_background_review_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    repo_root: Path,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None,
) -> None:
    cmux_bootstrap_support.start_background_review_surface_bootstrap(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        launch_config=launch_config,
        repo_root=repo_root,
        project_name=project_name,
        project_root=project_root,
        review_bundle_path=review_bundle_path,
        complete_review_surface_bootstrap_fn=_complete_review_surface_bootstrap,
        thread_factory=threading.Thread,
    )


def _complete_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
) -> None:
    cmux_bootstrap_support.complete_surface_bootstrap(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        launch_config=launch_config,
        worktree=worktree,
        build_plan_agent_workflow_fn=_build_plan_agent_workflow,
        run_surface_bootstrap_fn=_run_surface_bootstrap,
        persist_runtime_events_snapshot_fn=_persist_runtime_events_snapshot,
    )


def _complete_review_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    repo_root: Path,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None,
) -> None:
    cmux_bootstrap_support.complete_review_surface_bootstrap(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        launch_config=launch_config,
        repo_root=repo_root,
        project_name=project_name,
        project_root=project_root,
        review_bundle_path=review_bundle_path,
        run_review_surface_bootstrap_fn=_run_review_surface_bootstrap,
        persist_runtime_events_snapshot_fn=_persist_runtime_events_snapshot,
    )


def _run_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
) -> str | None:
    return cmux_bootstrap_support.run_surface_bootstrap(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        launch_config=launch_config,
        worktree=worktree,
        build_plan_agent_workflow_fn=_build_plan_agent_workflow,
        prepare_surface_fn=_prepare_surface,
        tab_title_for_worktree_fn=_tab_title_for_worktree,
        surface_respawn_command_fn=_surface_respawn_command,
        launch_cli_bootstrap_commands_fn=_launch_cli_bootstrap_commands,
        wait_for_cli_ready_fn=_wait_for_cli_ready,
        maybe_submit_surface_codex_goal_fn=_maybe_submit_surface_codex_goal,
        workflow_step_prompt_text_fn=_workflow_step_prompt_text,
        submit_direct_prompt_workflow_step_fn=_submit_direct_prompt_workflow_step,
        submit_prompt_workflow_step_fn=_submit_prompt_workflow_step,
        queue_codex_workflow_steps_fn=_queue_codex_workflow_steps,
        queue_failure_event_context_fn=_queue_failure_event_context,
    )


def _run_review_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    repo_root: Path,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None,
) -> str | None:
    return cmux_bootstrap_support.run_review_surface_bootstrap(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        launch_config=launch_config,
        repo_root=repo_root,
        project_name=project_name,
        project_root=project_root,
        review_bundle_path=review_bundle_path,
        prepare_surface_fn=_prepare_surface,
        tab_title_for_worktree_fn=_tab_title_for_worktree,
        launch_cli_bootstrap_commands_fn=_launch_cli_bootstrap_commands,
        wait_for_cli_ready_fn=_wait_for_cli_ready,
        review_prompt_arguments_fn=_review_prompt_arguments,
        review_original_plan_path_fn=_review_original_plan_path,
        resolve_preset_submission_text_fn=_resolve_preset_submission_text,
        uses_direct_submission_fn=_uses_direct_submission,
        submit_direct_prompt_workflow_step_fn=_submit_direct_prompt_workflow_step,
        submit_prompt_workflow_step_fn=_submit_prompt_workflow_step,
    )


def _maybe_submit_surface_codex_goal(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
) -> str | None:
    return cmux_goal_support.maybe_submit_surface_codex_goal(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
        codex_goal_text_for_worktree_fn=_codex_goal_text_for_worktree,
        submit_surface_codex_goal_fn=_submit_surface_codex_goal,
        emit_codex_goal_event_fn=_emit_codex_goal_event,
    )


def _submit_surface_codex_goal(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    goal_text: str,
) -> str | None:
    return cmux_goal_support.submit_surface_codex_goal(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        goal_text=goal_text,
        submit_direct_prompt_workflow_step_fn=_submit_direct_prompt_workflow_step,
        wait_for_surface_codex_goal_active_fn=_wait_for_surface_codex_goal_active,
        wait_for_codex_queue_ready_fn=_wait_for_codex_queue_ready,
    )


def _wait_for_surface_codex_goal_active(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    goal_text: str,
) -> bool:
    return cmux_goal_support.wait_for_surface_codex_goal_active(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        goal_text=goal_text,
        read_surface_screen_fn=_read_surface_screen,
    )


def _submit_prompt_workflow_step(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cli: str,
    prompt_text: str,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    return cmux_workflow_submission_support.submit_prompt_workflow_step(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=cli,
        prompt_text=prompt_text,
        failure_event=failure_event,
        send_prompt_text_fn=_send_prompt_text,
        send_surface_key_fn=_send_surface_key,
        wait_for_prompt_picker_ready_fn=_wait_for_prompt_picker_ready,
        wait_for_prompt_submit_ready_fn=_wait_for_prompt_submit_ready,
    )


def _submit_direct_prompt_workflow_step(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    prompt_text: str,
    failure_event: str = "planning.agent_launch.failed",
) -> str | None:
    return cmux_workflow_submission_support.submit_direct_prompt_workflow_step(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        prompt_text=prompt_text,
        failure_event=failure_event,
        paste_surface_text_fn=_paste_surface_text,
        send_surface_key_fn=_send_surface_key,
    )


def _queue_codex_workflow_steps(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    worktree: CreatedPlanWorktree,
    workflow: _PlanAgentWorkflow,
    queued_steps: tuple[_PlanAgentWorkflowStep, ...],
    launch_config: PlanAgentLaunchConfig,
    cli: str,
) -> str | None:
    return cmux_workflow_submission_support.queue_codex_workflow_steps(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        worktree=worktree,
        workflow=workflow,
        queued_steps=queued_steps,
        launch_config=launch_config,
        cli=cli,
        workflow_step_prompt_text_fn=_workflow_step_prompt_text,
        codex_goal_text_for_worktree_fn=_codex_goal_text_for_worktree,
        paste_surface_text_fn=_paste_surface_text,
        queue_codex_message_fn=_queue_codex_message,
    )


def _wait_for_codex_queue_ready(runtime: Any, *, workspace_id: str, surface_id: str) -> bool:
    return cmux_workflow_submission_support.wait_for_codex_queue_ready(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        read_surface_screen_fn=_read_surface_screen,
    )


def _queue_codex_message(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    text: str,
    require_text_match: bool = True,
) -> bool:
    return cmux_workflow_submission_support.queue_codex_message(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        text=text,
        require_text_match=require_text_match,
        read_surface_screen_fn=_read_surface_screen,
        send_surface_key_fn=_send_surface_key,
    )


def _launch_cli_bootstrap_commands(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    cwd: Path,
    cli_command: str,
    failure_event: str = "planning.agent_launch.failed",
) -> list[str | None]:
    return cmux_workflow_submission_support.launch_cli_bootstrap_commands(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cwd=cwd,
        cli_command=cli_command,
        send_surface_text_fn=_send_surface_text,
        send_surface_key_fn=_send_surface_key,
        failure_event=failure_event,
    )


def _wait_for_cli_ready(runtime: Any, *, workspace_id: str, surface_id: str, cli: str) -> None:
    cmux_surface_support.wait_for_cli_ready(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=cli,
        cli_ready_delay_seconds=_cli_ready_delay_seconds(str(cli).strip().lower()),
    )


_surface_id_from_output = cmux_workspace_support.surface_id_from_output
_resolve_workspace_id = cmux_workspace_support.resolve_workspace_id
_ensure_workspace_id = cmux_workspace_support.ensure_workspace_id
_default_target_workspace_title = cmux_workspace_support.default_target_workspace_title
_default_workspace_target = cmux_workspace_support.default_workspace_target
_missing_required_cmux_context = cmux_workspace_support.missing_required_cmux_context
_current_workspace_title = cmux_workspace_support.current_workspace_title
_current_workspace_ref = cmux_workspace_support.current_workspace_ref
_identify_workspace_ref = cmux_workspace_support.identify_workspace_ref
_workspace_ref_from_identify_output = cmux_workspace_support.workspace_ref_from_identify_output
_resolve_configured_workspace_id = cmux_workspace_support.resolve_configured_workspace_id
_ensure_configured_workspace_id = cmux_workspace_support.ensure_configured_workspace_id
_looks_like_workspace_handle = cmux_workspace_support.looks_like_workspace_handle
_resolve_workspace_ref_by_title = cmux_workspace_support.resolve_workspace_ref_by_title
_list_workspaces = cmux_workspace_support.list_workspaces
_workspace_entries_from_list_output = cmux_workspace_support.workspace_entries_from_list_output
_surface_ids_from_list_output = cmux_workspace_support.surface_ids_from_list_output
_list_workspace_surfaces = cmux_workspace_support.list_workspace_surfaces
_starter_surface_for_new_workspace = cmux_workspace_support.starter_surface_for_new_workspace
_create_named_workspace = cmux_workspace_support.create_named_workspace
_workspace_ref_from_command_output = cmux_workspace_support.workspace_ref_from_command_output

_create_surface = cmux_surface_support.create_surface
_send_surface_text = cmux_surface_support.send_surface_text
_paste_surface_text = cmux_surface_support.paste_surface_text
_send_prompt_text = cmux_surface_support.send_prompt_text
_send_surface_key = cmux_surface_support.send_surface_key
_run_cmux_command = cmux_surface_support.run_cmux_command
_completed_process_error_text = cmux_surface_support.completed_process_error_text
_read_surface_screen = cmux_surface_support.read_surface_screen
_wait_for_prompt_submit_ready = cmux_surface_support.wait_for_prompt_submit_ready
_wait_for_prompt_picker_ready = cmux_surface_support.wait_for_prompt_picker_ready
_prepare_surface = cmux_surface_support.prepare_surface


__all__ = tuple(name for name in globals() if not name.startswith("__"))
