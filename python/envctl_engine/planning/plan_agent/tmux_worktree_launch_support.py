from __future__ import annotations

from typing import Any, Callable

from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    PlanAgentLaunchOutcome,
    _PlanAgentWorkflow,
)


def launch_single_tmux_worktree(
    runtime: Any,
    *,
    session_name: str,
    window_name: str,
    launch_config: PlanAgentLaunchConfig,
    workflow: _PlanAgentWorkflow,
    worktree: CreatedPlanWorktree,
    ensure_tmux_window_fn: Callable[..., str | None],
    run_tmux_worktree_bootstrap_fn: Callable[..., str | None],
    persist_runtime_events_snapshot_fn: Callable[[Any], None],
) -> PlanAgentLaunchOutcome:
    create_error = ensure_tmux_window_fn(
        runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        worktree=worktree,
    )
    if create_error is not None:
        runtime._emit(
            "planning.agent_launch.failed",
            reason="window_create_failed",
            session_name=session_name,
            window_name=window_name,
            worktree=worktree.name,
            error=create_error,
            transport="tmux",
        )
        return PlanAgentLaunchOutcome(
            worktree_name=worktree.name,
            worktree_root=worktree.root,
            surface_id=None,
            status="failed",
            reason=create_error,
        )
    runtime._emit(
        "planning.agent_launch.surface_created",
        session_name=session_name,
        window_name=window_name,
        worktree=worktree.name,
        source="tmux_window",
        transport="tmux",
    )
    error = run_tmux_worktree_bootstrap_fn(
        runtime,
        session_name=session_name,
        window_name=window_name,
        launch_config=launch_config,
        workflow=workflow,
        worktree=worktree,
    )
    if error is not None:
        runtime._emit(
            "planning.agent_launch.failed",
            reason="bootstrap_failed",
            session_name=session_name,
            window_name=window_name,
            worktree=worktree.name,
            error=error,
            transport="tmux",
        )
        return PlanAgentLaunchOutcome(
            worktree_name=worktree.name,
            worktree_root=worktree.root,
            surface_id=None,
            status="failed",
            reason=error,
        )
    runtime._emit(
        "planning.agent_launch.command_sent",
        session_name=session_name,
        window_name=window_name,
        worktree=worktree.name,
        preset=launch_config.preset,
        workflow_mode=workflow.mode,
        codex_cycles=workflow.codex_cycles,
        transport="tmux",
    )
    persist_runtime_events_snapshot_fn(runtime)
    return PlanAgentLaunchOutcome(
        worktree_name=worktree.name,
        worktree_root=worktree.root,
        surface_id=None,
        status="launched",
    )
