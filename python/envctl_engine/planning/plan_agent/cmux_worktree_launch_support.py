from __future__ import annotations

from typing import Any, Callable

from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    PlanAgentLaunchOutcome,
)


def launch_single_worktree(
    runtime: Any,
    *,
    workspace_id: str,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
    starter_surface_id: str | None,
    create_surface_fn: Callable[..., tuple[str | None, str | None]],
    start_background_surface_bootstrap_fn: Callable[..., None],
) -> PlanAgentLaunchOutcome:
    surface_source = "starter_reused" if starter_surface_id else "new_surface"
    if starter_surface_id:
        surface_id = starter_surface_id
        create_error = None
    else:
        surface_id, create_error = create_surface_fn(runtime, workspace_id=workspace_id)
    if create_error or surface_id is None:
        runtime._emit(
            "planning.agent_launch.failed",
            reason="surface_create_failed",
            workspace_id=workspace_id,
            worktree=worktree.name,
            error=create_error,
        )
        return PlanAgentLaunchOutcome(
            worktree_name=worktree.name,
            worktree_root=worktree.root,
            surface_id=None,
            status="failed",
            reason=create_error or "surface_create_failed",
            workspace_id=workspace_id,
        )
    runtime._emit(
        "planning.agent_launch.surface_created",
        workspace_id=workspace_id,
        surface_id=surface_id,
        worktree=worktree.name,
        source=surface_source,
    )
    start_background_surface_bootstrap_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        launch_config=launch_config,
        worktree=worktree,
    )
    return PlanAgentLaunchOutcome(
        worktree_name=worktree.name,
        worktree_root=worktree.root,
        surface_id=surface_id,
        status="launched",
        workspace_id=workspace_id,
    )
