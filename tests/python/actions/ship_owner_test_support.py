from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from envctl_engine.actions import action_ship_checks


@dataclass
class ShipContext:
    project_name: str
    project_root: Path
    repo_root: Path
    env: dict[str, str]


def fake_gh_path() -> str | None:
    return "/usr/bin/gh"


def no_sleep(_seconds: float) -> None:
    return None


def github_pr_checks(git_root: Path, **overrides: Any) -> dict[str, object]:
    kwargs: dict[str, Any] = {
        "branch": "feature/demo",
        "pr_url": "https://github.com/acme/repo/pull/7",
        "gh_path_resolver": fake_gh_path,
    }
    kwargs.update(overrides)
    return action_ship_checks.github_pr_checks(git_root, **kwargs)
