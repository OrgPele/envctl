from __future__ import annotations

from pathlib import Path

from envctl_engine.actions.action_utils import detect_repo_python


def default_pr_command(base_dir: Path) -> list[str] | None:
    python_bin = detect_repo_python(base_dir)
    if python_bin is None:
        return None
    return [python_bin, "-m", "envctl_engine.actions.actions_cli", "pr"]


def default_commit_command(base_dir: Path) -> list[str] | None:
    python_bin = detect_repo_python(base_dir)
    if python_bin is None:
        return None
    return [python_bin, "-m", "envctl_engine.actions.actions_cli", "commit"]
