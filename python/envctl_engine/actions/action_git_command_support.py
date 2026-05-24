from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from envctl_engine.actions.actions_analysis import default_review_command
from envctl_engine.actions.actions_git import default_commit_command, default_pr_command, default_ship_command
from envctl_engine.runtime.command_router import Route


def run_pr_action_with_owner(
    orchestrator: Any,
    route: Route,
    targets: list[object],
    *,
    extra_env: Mapping[str, str],
) -> int:
    return _run_git_project_action(
        orchestrator,
        route,
        targets,
        command_name="pr",
        env_key="ENVCTL_ACTION_PR_CMD",
        default_command_builder=default_pr_command,
        extra_env=extra_env,
    )


def run_commit_action_with_owner(
    orchestrator: Any,
    route: Route,
    targets: list[object],
    *,
    extra_env: Mapping[str, str],
) -> int:
    return _run_git_project_action(
        orchestrator,
        route,
        targets,
        command_name="commit",
        env_key="ENVCTL_ACTION_COMMIT_CMD",
        default_command_builder=default_commit_command,
        extra_env=extra_env,
    )


def run_ship_action_with_owner(
    orchestrator: Any,
    route: Route,
    targets: list[object],
    *,
    extra_env: Mapping[str, str],
) -> int:
    return _run_git_project_action(
        orchestrator,
        route,
        targets,
        command_name="ship",
        env_key="ENVCTL_ACTION_SHIP_CMD",
        default_command_builder=default_ship_command,
        extra_env=extra_env,
    )


def run_review_action_with_owner(
    orchestrator: Any,
    route: Route,
    targets: list[object],
    *,
    extra_env: Mapping[str, str],
) -> int:
    return _run_git_project_action(
        orchestrator,
        route,
        targets,
        command_name="review",
        env_key="ENVCTL_ACTION_ANALYZE_CMD",
        default_command_builder=default_review_command,
        extra_env=extra_env,
    )


def _run_git_project_action(
    orchestrator: Any,
    route: Route,
    targets: list[object],
    *,
    command_name: str,
    env_key: str,
    default_command_builder: Callable[[Path], list[str] | None],
    extra_env: Mapping[str, str],
) -> int:
    base_dir = orchestrator.runtime.config.base_dir
    return orchestrator.run_project_action(
        route,
        targets,
        command_name=command_name,
        env_key=env_key,
        default_command=default_command_builder(base_dir),
        default_cwd=base_dir,
        default_append_project_path=False,
        extra_env=extra_env,
    )
