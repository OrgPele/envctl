from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path


def worktree_branch_name(*, feature: str, iteration: str) -> str:
    return f"{feature}-{iteration}"


def worktree_branch_exists(*, branch_name: str, git_command_output: Callable[[list[str]], str]) -> bool:
    normalized = branch_name.strip()
    if not normalized:
        return False
    return bool(git_command_output(["rev-parse", "--verify", f"refs/heads/{normalized}"]).strip())


def worktree_start_point(
    *,
    provenance: dict[str, object],
    git_command_output: Callable[[list[str]], str],
) -> str | None:
    for key in ("source_ref", "source_branch"):
        candidate = str(provenance.get(key, "")).strip()
        if candidate and git_command_output(["rev-parse", "--verify", candidate]).strip():
            return candidate
    head_commit = git_command_output(["rev-parse", "HEAD"]).strip()
    return head_commit or None


def run_worktree_add(
    *,
    repo_root: Path,
    feature: str,
    iteration: str,
    target: Path,
    env: Mapping[str, str],
    git_hooks_disabled: bool,
    branch_exists: Callable[[str], bool],
    start_point: Callable[[], str | None],
    run: Callable[..., object],
) -> object:
    branch_name = worktree_branch_name(feature=feature, iteration=iteration)
    selected_start_point = start_point()
    branch_flag = "-B" if branch_exists(branch_name) else "-b"
    command = ["git"]
    if git_hooks_disabled:
        command.extend(["-c", "core.hooksPath=/dev/null"])
    command.extend(
        [
            "-C",
            str(repo_root),
            "worktree",
            "add",
            branch_flag,
            branch_name,
            str(target),
        ]
    )
    if selected_start_point:
        command.append(selected_start_point)
    return run(
        command,
        cwd=repo_root,
        env=env,
        timeout=120.0,
    )
