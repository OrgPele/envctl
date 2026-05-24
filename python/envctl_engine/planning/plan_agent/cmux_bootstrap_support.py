from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

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
