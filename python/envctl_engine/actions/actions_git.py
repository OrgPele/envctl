from __future__ import annotations

from pathlib import Path
import shutil

from envctl_engine.actions.action_utils import detect_envctl_python


def default_pr_command(base_dir: Path) -> list[str] | None:
    return _default_git_action_command(base_dir, "pr")


def default_commit_command(base_dir: Path) -> list[str] | None:
    return _default_git_action_command(base_dir, "commit")


def default_ship_command(base_dir: Path) -> list[str] | None:
    return _default_git_action_command(base_dir, "ship")


def _default_git_action_command(base_dir: Path, action: str) -> list[str] | None:
    if (base_dir / "pyproject.toml").is_file() and shutil.which("uv"):
        return ["uv", "run", "--extra", "dev", "python", "-m", "envctl_engine.actions.actions_cli", action]
    python_bin = detect_envctl_python()
    if python_bin is None:
        return None
    return [python_bin, "-m", "envctl_engine.actions.actions_cli", action]
