from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Mapping

from envctl_engine.planning.plan_agent.constants import _REVIEW_WORKTREE_PRESET
from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
)


BuildPlanAgentWorkflowFn = Callable[..., _PlanAgentWorkflow]
RunSurfaceBootstrapFn = Callable[..., str | None]
RunReviewSurfaceBootstrapFn = Callable[..., str | None]
PersistRuntimeEventsSnapshotFn = Callable[[Any], None]
CompleteSurfaceBootstrapFn = Callable[..., None]
CompleteReviewSurfaceBootstrapFn = Callable[..., None]
ThreadFactory = Callable[..., threading.Thread]
PrepareSurfaceFn = Callable[..., str | None]
TabTitleForWorktreeFn = Callable[[str], str]
SurfaceRespawnCommandFn = Callable[..., str]
LaunchCliBootstrapCommandsFn = Callable[..., tuple[str | None, ...] | list[str | None]]
WaitForCliReadyFn = Callable[..., Any]
MaybeSubmitSurfaceCodexGoalFn = Callable[..., str | None]
WorkflowStepPromptTextFn = Callable[..., tuple[str, str | None]]
SubmitPromptWorkflowStepFn = Callable[..., str | None]
QueueCodexWorkflowStepsFn = Callable[..., str | None]
QueueFailureEventContextFn = Callable[[str], Mapping[str, object]]
ReviewPromptArgumentsFn = Callable[..., Mapping[str, object]]
ReviewOriginalPlanPathFn = Callable[..., Path | None]
ResolvePresetSubmissionTextFn = Callable[..., tuple[str, str | None]]
UsesDirectSubmissionFn = Callable[..., bool]


def start_background_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
    complete_surface_bootstrap_fn: CompleteSurfaceBootstrapFn,
    thread_factory: ThreadFactory = threading.Thread,
) -> None:
    thread = thread_factory(
        target=complete_surface_bootstrap_fn,
        kwargs={
            "runtime": runtime,
            "workspace_id": workspace_id,
            "surface_id": surface_id,
            "launch_config": launch_config,
            "worktree": worktree,
        },
        name=f"envctl-plan-agent-{worktree.name}",
        daemon=False,
    )
    thread.start()


def start_background_review_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    repo_root: Path,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None,
    complete_review_surface_bootstrap_fn: CompleteReviewSurfaceBootstrapFn,
    thread_factory: ThreadFactory = threading.Thread,
) -> None:
    thread = thread_factory(
        target=complete_review_surface_bootstrap_fn,
        kwargs={
            "runtime": runtime,
            "workspace_id": workspace_id,
            "surface_id": surface_id,
            "launch_config": launch_config,
            "repo_root": repo_root,
            "project_name": project_name,
            "project_root": project_root,
            "review_bundle_path": review_bundle_path,
        },
        name=f"envctl-review-agent-{project_name}",
        daemon=False,
    )
    thread.start()


def complete_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
    build_plan_agent_workflow_fn: BuildPlanAgentWorkflowFn,
    run_surface_bootstrap_fn: RunSurfaceBootstrapFn,
    persist_runtime_events_snapshot_fn: PersistRuntimeEventsSnapshotFn,
) -> None:
    workflow = build_plan_agent_workflow_fn(
        cli=launch_config.cli,
        preset=launch_config.preset,
        codex_cycles=launch_config.codex_cycles,
        direct_prompt_enabled=launch_config.direct_prompt_enabled,
        browser_e2e_followup_enable=launch_config.browser_e2e_followup_enable,
        pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
    )
    try:
        error = run_surface_bootstrap_fn(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            launch_config=launch_config,
            worktree=worktree,
        )
        if error is None:
            runtime._emit(
                "planning.agent_launch.command_sent",
                workspace_id=workspace_id,
                surface_id=surface_id,
                worktree=worktree.name,
                preset=launch_config.preset,
                workflow_mode=workflow.mode,
                codex_cycles=workflow.codex_cycles,
            )
            return
        runtime._emit(
            "planning.agent_launch.failed",
            reason="bootstrap_failed",
            workspace_id=workspace_id,
            surface_id=surface_id,
            worktree=worktree.name,
            error=error,
        )
    finally:
        persist_runtime_events_snapshot_fn(runtime)


def complete_review_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    repo_root: Path,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None,
    run_review_surface_bootstrap_fn: RunReviewSurfaceBootstrapFn,
    persist_runtime_events_snapshot_fn: PersistRuntimeEventsSnapshotFn,
) -> None:
    try:
        error = run_review_surface_bootstrap_fn(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            launch_config=launch_config,
            repo_root=repo_root,
            project_name=project_name,
            project_root=project_root,
            review_bundle_path=review_bundle_path,
        )
        if error is None:
            runtime._emit(
                "dashboard.review_tab.command_sent",
                workspace_id=workspace_id,
                surface_id=surface_id,
                project=project_name,
                cli=launch_config.cli,
                preset=_REVIEW_WORKTREE_PRESET,
            )
            return
        runtime._emit(
            "dashboard.review_tab.failed",
            reason="bootstrap_failed",
            workspace_id=workspace_id,
            surface_id=surface_id,
            project=project_name,
            cli=launch_config.cli,
            error=error,
        )
    finally:
        persist_runtime_events_snapshot_fn(runtime)


def run_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
    build_plan_agent_workflow_fn: BuildPlanAgentWorkflowFn,
    prepare_surface_fn: PrepareSurfaceFn,
    tab_title_for_worktree_fn: TabTitleForWorktreeFn,
    surface_respawn_command_fn: SurfaceRespawnCommandFn,
    launch_cli_bootstrap_commands_fn: LaunchCliBootstrapCommandsFn,
    wait_for_cli_ready_fn: WaitForCliReadyFn,
    maybe_submit_surface_codex_goal_fn: MaybeSubmitSurfaceCodexGoalFn,
    workflow_step_prompt_text_fn: WorkflowStepPromptTextFn,
    submit_direct_prompt_workflow_step_fn: SubmitPromptWorkflowStepFn,
    submit_prompt_workflow_step_fn: SubmitPromptWorkflowStepFn,
    queue_codex_workflow_steps_fn: QueueCodexWorkflowStepsFn,
    queue_failure_event_context_fn: QueueFailureEventContextFn,
) -> str | None:
    workflow = build_plan_agent_workflow_fn(
        cli=launch_config.cli,
        preset=launch_config.preset,
        codex_cycles=launch_config.codex_cycles,
        direct_prompt_enabled=launch_config.direct_prompt_enabled,
        browser_e2e_followup_enable=launch_config.browser_e2e_followup_enable,
        pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
    )
    error = prepare_surface_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        tab_title=tab_title_for_worktree_fn(worktree.name),
        shell_command=surface_respawn_command_fn(launch_config, worktree),
    )
    if error is not None:
        return error
    send_errors = launch_cli_bootstrap_commands_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cwd=worktree.root,
        cli_command=launch_config.cli_command,
    )
    for send_error in send_errors:
        if send_error is not None:
            return send_error
    wait_for_cli_ready_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=launch_config.cli,
    )
    goal_error = maybe_submit_surface_codex_goal_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
    )
    if goal_error is not None:
        return goal_error
    if launch_config.codex_goal_enable and launch_config.cli == "codex":
        wait_for_cli_ready_fn(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            cli=launch_config.cli,
        )
    initial_step = workflow.steps[0]
    prompt_text, resolution_error = workflow_step_prompt_text_fn(
        runtime,
        launch_config=launch_config,
        cli=launch_config.cli,
        step=initial_step,
        worktree=worktree,
    )
    if resolution_error is not None:
        return resolution_error
    if initial_step.kind == "submit_direct_prompt":
        submit_error = submit_direct_prompt_workflow_step_fn(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            prompt_text=prompt_text,
        )
    else:
        submit_error = submit_prompt_workflow_step_fn(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            cli=launch_config.cli,
            prompt_text=prompt_text,
        )
    if submit_error is not None:
        return submit_error
    queued_steps = workflow.steps[1:]
    if queued_steps and launch_config.cli == "codex":
        queue_error_reason = queue_codex_workflow_steps_fn(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            worktree=worktree,
            workflow=workflow,
            queued_steps=queued_steps,
            launch_config=launch_config,
            cli=launch_config.cli,
        )
        if queue_error_reason is not None:
            failure_context = queue_failure_event_context_fn(queue_error_reason)
            runtime._emit(
                "planning.agent_launch.workflow_queue_failed",
                workspace_id=workspace_id,
                surface_id=surface_id,
                worktree=worktree.name,
                cli=launch_config.cli,
                workflow_mode=workflow.mode,
                codex_cycles=workflow.codex_cycles,
                reason=queue_error_reason,
                transport="cmux",
                **failure_context,
            )
            runtime._emit(
                "planning.agent_launch.workflow_fallback",
                workspace_id=workspace_id,
                surface_id=surface_id,
                worktree=worktree.name,
                cli=launch_config.cli,
                workflow_mode=workflow.mode,
                codex_cycles=workflow.codex_cycles,
                reason=queue_error_reason,
                transport="cmux",
                **failure_context,
            )
            return None
    return None


def run_review_surface_bootstrap(
    runtime: Any,
    *,
    workspace_id: str,
    surface_id: str,
    launch_config: PlanAgentLaunchConfig,
    repo_root: Path,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None,
    prepare_surface_fn: PrepareSurfaceFn,
    tab_title_for_worktree_fn: TabTitleForWorktreeFn,
    launch_cli_bootstrap_commands_fn: LaunchCliBootstrapCommandsFn,
    wait_for_cli_ready_fn: WaitForCliReadyFn,
    review_prompt_arguments_fn: ReviewPromptArgumentsFn,
    review_original_plan_path_fn: ReviewOriginalPlanPathFn,
    resolve_preset_submission_text_fn: ResolvePresetSubmissionTextFn,
    uses_direct_submission_fn: UsesDirectSubmissionFn,
    submit_direct_prompt_workflow_step_fn: SubmitPromptWorkflowStepFn,
    submit_prompt_workflow_step_fn: SubmitPromptWorkflowStepFn,
) -> str | None:
    error = prepare_surface_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        tab_title=tab_title_for_worktree_fn(project_name),
        shell_command=launch_config.shell,
        failure_event="dashboard.review_tab.failed",
    )
    if error is not None:
        return error
    send_errors = launch_cli_bootstrap_commands_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cwd=repo_root,
        cli_command=launch_config.cli_command,
        failure_event="dashboard.review_tab.failed",
    )
    for send_error in send_errors:
        if send_error is not None:
            return send_error
    wait_for_cli_ready_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=launch_config.cli,
    )
    review_arguments = review_prompt_arguments_fn(
        project_name=project_name,
        project_root=project_root,
        review_bundle_path=review_bundle_path,
        original_plan_path=review_original_plan_path_fn(project_name, project_root, repo_root=repo_root),
    )
    prompt_text, resolution_error = resolve_preset_submission_text_fn(
        runtime,
        launch_config=launch_config,
        cli=launch_config.cli,
        preset=_REVIEW_WORKTREE_PRESET,
        arguments=review_arguments,
    )
    if resolution_error is not None:
        return resolution_error
    if uses_direct_submission_fn(cli=launch_config.cli, direct_prompt_enabled=launch_config.direct_prompt_enabled):
        return submit_direct_prompt_workflow_step_fn(
            runtime,
            workspace_id=workspace_id,
            surface_id=surface_id,
            prompt_text=prompt_text,
            failure_event="dashboard.review_tab.failed",
        )
    return submit_prompt_workflow_step_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=launch_config.cli,
        prompt_text=prompt_text,
        failure_event="dashboard.review_tab.failed",
    )
