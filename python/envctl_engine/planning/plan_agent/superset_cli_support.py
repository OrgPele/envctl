from __future__ import annotations

from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree, PlanAgentLaunchConfig
from envctl_engine.planning.plan_agent.superset_desktop_support import superset_completed_process_error_text
from envctl_engine.planning.plan_agent.workflow_build import _tab_title_for_worktree
from envctl_engine.runtime.runtime_context import resolve_process_runtime


def git_branch_name(runtime: Any, cwd: Path) -> tuple[str, str | None]:
    result = resolve_process_runtime(runtime).run(
        ["git", "-C", str(cwd), "branch", "--show-current"],
        cwd=cwd,
        env=getattr(runtime, "env", {}),
        timeout=10.0,
    )
    if getattr(result, "returncode", 1) != 0:
        return "", "git_branch_unavailable"
    branch = str(getattr(result, "stdout", "") or "").strip()
    if not branch:
        return "", "git_branch_unavailable"
    return branch, None


def superset_workspace_name(worktree: CreatedPlanWorktree) -> str:
    return _tab_title_for_worktree(worktree.name)


def open_superset_workspace(
    runtime: Any,
    *,
    launch_config: PlanAgentLaunchConfig,
    worktree: CreatedPlanWorktree,
    workspace_id: str,
) -> str | None:
    command = ["superset", "workspaces", "open", workspace_id]
    runtime._emit(
        "planning.agent_launch.superset_open",
        transport="superset",
        worktree=worktree.name,
        project=launch_config.superset_project or None,
        workspace_id=workspace_id,
        command_kind="open",
    )
    result = resolve_process_runtime(runtime).run(
        command,
        cwd=Path(worktree.root),
        env=getattr(runtime, "env", {}),
        timeout=30.0,
    )
    if getattr(result, "returncode", 1) == 0:
        return None
    error = superset_completed_process_error_text(result)
    runtime._emit(
        "planning.agent_launch.superset_open_failed",
        reason="superset_open_failed",
        transport="superset",
        worktree=worktree.name,
        project=launch_config.superset_project or None,
        workspace_id=workspace_id,
        error=error,
    )
    return error


__all__ = tuple(name for name in globals() if not name.startswith("_"))
