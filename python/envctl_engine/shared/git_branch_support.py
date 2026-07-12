from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass


PREFERRED_PR_BASE_BRANCHES = ("dev", "main", "master")


@dataclass(frozen=True, slots=True)
class _RemoteBranchInventory:
    preferred_heads: frozenset[str]
    default_branch: str | None
    reachable: bool


def detect_preferred_default_branch(
    git_output: Callable[[Sequence[str]], str],
    *,
    probe_remote_heads: bool = False,
) -> str:
    """Resolve the PR base contract before consulting a repository's remote HEAD."""

    tracked_remote_branches: set[str] = set()
    for branch in PREFERRED_PR_BASE_BRANCHES:
        if git_output(("rev-parse", "--verify", f"refs/remotes/origin/{branch}")).strip():
            tracked_remote_branches.add(branch)

    remote_inventory = _remote_branch_inventory(git_output) if probe_remote_heads else None
    # A successful live inventory is authoritative over local tracking refs,
    # including when none of the preferred branches exist. When the probe is
    # unavailable or times out, retain the offline tracking-ref fallback.
    available_branches = (
        remote_inventory.preferred_heads
        if remote_inventory is not None and remote_inventory.reachable
        else tracked_remote_branches
    )
    for branch in PREFERRED_PR_BASE_BRANCHES:
        if branch in available_branches:
            return branch
    if remote_inventory is not None and remote_inventory.reachable and remote_inventory.default_branch:
        return remote_inventory.default_branch

    remote_head = git_output(("symbolic-ref", "--short", "refs/remotes/origin/HEAD")).strip()
    if remote_head.startswith("origin/"):
        return remote_head.removeprefix("origin/")
    for branch in PREFERRED_PR_BASE_BRANCHES:
        if git_output(("rev-parse", "--verify", f"refs/heads/{branch}")).strip():
            return branch
    return "main"


def _remote_branch_inventory(
    git_output: Callable[[Sequence[str]], str],
) -> _RemoteBranchInventory:
    output = git_output(
        (
            "ls-remote",
            "--symref",
            "origin",
            "HEAD",
            *(f"refs/heads/{branch}" for branch in PREFERRED_PR_BASE_BRANCHES),
        )
    )
    heads: set[str] = set()
    default_branch: str | None = None
    for raw_line in output.splitlines():
        fields = raw_line.split()
        if len(fields) == 3 and fields[0] == "ref:" and fields[2] == "HEAD":
            ref = fields[1]
            if ref.startswith("refs/heads/"):
                default_branch = ref.removeprefix("refs/heads/") or None
            continue
        if len(fields) != 2 or not fields[1].startswith("refs/heads/"):
            continue
        branch = fields[1].removeprefix("refs/heads/")
        if branch in PREFERRED_PR_BASE_BRANCHES:
            heads.add(branch)
    return _RemoteBranchInventory(
        preferred_heads=frozenset(heads),
        default_branch=default_branch,
        reachable=bool(output.strip()),
    )


__all__ = ["PREFERRED_PR_BASE_BRANCHES", "detect_preferred_default_branch"]
