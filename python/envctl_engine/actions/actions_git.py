from __future__ import annotations

from pathlib import Path

from envctl_engine.actions.action_utils import detect_envctl_python


def default_pr_command(base_dir: Path) -> list[str] | None:
    _ = base_dir
    python_bin = detect_envctl_python()
    if python_bin is None:
        return None
    return [python_bin, "-m", "envctl_engine.actions.actions_cli", "pr"]


def default_commit_command(base_dir: Path) -> list[str] | None:
    _ = base_dir
    python_bin = detect_envctl_python()
    if python_bin is None:
        return None
    return [python_bin, "-m", "envctl_engine.actions.actions_cli", "commit"]
