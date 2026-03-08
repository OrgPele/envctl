from __future__ import annotations

import os
import sys
from pathlib import Path

from envctl_engine.actions.project_action_domain import (
    ActionProjectContext,
    run_analyze_action as _domain_run_analyze_action,
    run_commit_action as _domain_run_commit_action,
    run_pr_action as _domain_run_pr_action,
)


def _build_context(*, repo_root: Path, project_root: Path, project_name: str) -> ActionProjectContext:
    return ActionProjectContext(
        repo_root=repo_root.resolve(),
        project_root=project_root.resolve(),
        project_name=project_name,
        env=dict(os.environ),
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    command = argv[0] if argv else os.environ.get("ENVCTL_ACTION_COMMAND", "")
    command = command.strip().lower()
    if not command:
        print("Action command not provided.")
        return 1

    repo_root = Path(os.environ.get("ENVCTL_ACTION_REPO_ROOT", Path.cwd())).resolve()
    project_root = Path(os.environ.get("ENVCTL_ACTION_PROJECT_ROOT", repo_root)).resolve()
    project_name = os.environ.get("ENVCTL_ACTION_PROJECT", project_root.name)
    context = _build_context(repo_root=repo_root, project_root=project_root, project_name=project_name)

    if command == "pr":
        return _domain_run_pr_action(context)
    if command == "commit":
        return _domain_run_commit_action(context)
    if command == "analyze":
        return _domain_run_analyze_action(context)

    print(f"Unsupported action command: {command}")
    return 1


# Compatibility wrappers retained for direct tests.
def _run_commit_action(project_root: Path, project_name: str) -> int:
    context = _build_context(repo_root=Path(project_root), project_root=Path(project_root), project_name=project_name)
    return _domain_run_commit_action(context)


# Compatibility wrappers retained for direct tests.
def _run_pr_action(project_root: Path, repo_root: Path, project_name: str) -> int:
    context = _build_context(repo_root=Path(repo_root), project_root=Path(project_root), project_name=project_name)
    return _domain_run_pr_action(context)


# Compatibility wrappers retained for direct tests.
def _run_analyze_action(project_root: Path, repo_root: Path, project_name: str) -> int:
    context = _build_context(repo_root=Path(repo_root), project_root=Path(project_root), project_name=project_name)
    return _domain_run_analyze_action(context)


if __name__ == "__main__":
    raise SystemExit(main())
