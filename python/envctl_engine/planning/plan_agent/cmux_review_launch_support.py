from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any, Callable

from envctl_engine.planning.plan_agent.models import (
    AgentTerminalLaunchResult,
    PlanAgentLaunchConfig,
    ReviewAgentLaunchReadiness,
)


def resolve_review_agent_launch_readiness(
    runtime: Any,
    *,
    resolve_launch_config_fn: Callable[..., PlanAgentLaunchConfig],
    missing_launch_commands_fn: Callable[..., Iterable[str]],
    default_target_workspace_title_fn: Callable[..., str | None],
    missing_required_cmux_context_fn: Callable[..., bool],
) -> ReviewAgentLaunchReadiness:
    launch_config = resolve_launch_config_fn(runtime.config, getattr(runtime, "env", {}))
    if launch_config.transport == "superset":
        return ReviewAgentLaunchReadiness(
            ready=False,
            reason="unsupported_superset_review_tab",
            cli=launch_config.cli,
        )
    missing_commands = tuple(missing_launch_commands_fn(runtime, launch_config))
    if missing_commands:
        return ReviewAgentLaunchReadiness(
            ready=False,
            reason="missing_executables",
            cli=launch_config.cli,
            missing=missing_commands,
        )
    if launch_config.cmux_workspace:
        return ReviewAgentLaunchReadiness(ready=True, reason="ready", cli=launch_config.cli)
    if default_target_workspace_title_fn(runtime, launch_config, workspace_mode="reviews"):
        return ReviewAgentLaunchReadiness(ready=True, reason="ready", cli=launch_config.cli)
    reason = (
        "missing_cmux_context"
        if missing_required_cmux_context_fn(runtime, launch_config)
        else "workspace_unavailable"
    )
    return ReviewAgentLaunchReadiness(ready=False, reason=reason, cli=launch_config.cli)


def launch_cmux_review_agent_terminal(
    runtime: Any,
    *,
    repo_root: Path,
    project_name: str,
    project_root: Path,
    review_bundle_path: Path | None,
    resolve_launch_config_fn: Callable[..., PlanAgentLaunchConfig],
    missing_launch_commands_fn: Callable[..., Iterable[str]],
    ensure_workspace_id_fn: Callable[..., Any],
    missing_required_cmux_context_fn: Callable[..., bool],
    create_surface_fn: Callable[..., tuple[str | None, str | None]],
    start_background_review_surface_bootstrap_fn: Callable[..., None],
    print_launch_summary_fn: Callable[[str], None],
) -> AgentTerminalLaunchResult:
    launch_config = resolve_launch_config_fn(runtime.config, getattr(runtime, "env", {}))
    if launch_config.transport == "superset":
        runtime._emit(
            "dashboard.review_tab.failed",
            reason="unsupported_superset_review_tab",
            project=project_name,
            cli=launch_config.cli,
        )
        return AgentTerminalLaunchResult(status="failed", reason="unsupported_superset_review_tab")
    missing_commands = missing_launch_commands_fn(runtime, launch_config)
    if missing_commands:
        runtime._emit(
            "dashboard.review_tab.failed",
            reason="missing_executables",
            project=project_name,
            cli=launch_config.cli,
            missing=missing_commands,
        )
        return AgentTerminalLaunchResult(status="failed", reason="missing_executables")
    workspace_target = ensure_workspace_id_fn(
        runtime,
        launch_config,
        workspace_mode="reviews",
        event_prefix="dashboard.review_tab",
    )
    if workspace_target is None:
        reason = (
            "missing_cmux_context"
            if missing_required_cmux_context_fn(runtime, launch_config)
            else "workspace_unavailable"
        )
        runtime._emit(
            "dashboard.review_tab.failed",
            reason=reason,
            project=project_name,
            cli=launch_config.cli,
        )
        return AgentTerminalLaunchResult(status="failed", reason=reason)
    workspace_id = workspace_target.workspace_id
    surface_id, create_error = create_surface_fn(runtime, workspace_id=workspace_id)
    if create_error or surface_id is None:
        runtime._emit(
            "dashboard.review_tab.failed",
            reason="surface_create_failed",
            project=project_name,
            workspace_id=workspace_id,
            error=create_error,
            cli=launch_config.cli,
        )
        return AgentTerminalLaunchResult(status="failed", reason=create_error or "surface_create_failed")
    runtime._emit(
        "dashboard.review_tab.surface_created",
        project=project_name,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=launch_config.cli,
    )
    start_background_review_surface_bootstrap_fn(
        runtime,
        workspace_id=workspace_id,
        surface_id=surface_id,
        launch_config=launch_config,
        repo_root=repo_root,
        project_name=project_name,
        project_root=project_root,
        review_bundle_path=review_bundle_path,
    )
    runtime._emit(
        "dashboard.review_tab.launched",
        project=project_name,
        workspace_id=workspace_id,
        surface_id=surface_id,
        cli=launch_config.cli,
    )
    print_launch_summary_fn(f"Opened origin review tab for {project_name}.")
    return AgentTerminalLaunchResult(status="launched", reason="launched", surface_id=surface_id)
