from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from envctl_engine.actions.action_git_state_support import ExistingPullRequest

ExistingPullRequestLookup = Callable[[Path, str], ExistingPullRequest | None]


class ShipPullRequestState(Protocol):
    git_root: Path
    branch: str
    pr_url: str
    pr_base_branch: str


def explicit_pr_base(context: Any) -> str:
    env = getattr(context, "env", {})
    try:
        return str(env.get("ENVCTL_PR_BASE", "")).strip()
    except AttributeError:
        return ""


def refresh_existing_pull_request(
    state: ShipPullRequestState,
    lookup: ExistingPullRequestLookup | None,
) -> None:
    if lookup is None:
        return
    existing = lookup(state.git_root, state.branch)
    if existing is None:
        return
    state.pr_url = existing.url
    state.pr_base_branch = existing.base_branch


def conflict_base_branch_override(context: Any, state: ShipPullRequestState) -> str:
    return explicit_pr_base(context) or state.pr_base_branch


__all__ = [
    "ExistingPullRequestLookup",
    "conflict_base_branch_override",
    "explicit_pr_base",
    "refresh_existing_pull_request",
]
