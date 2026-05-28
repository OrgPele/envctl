from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Protocol


class ImportedBranchProjectLike(Protocol):
    name: str
    root: Path


@dataclass(frozen=True, slots=True)
class ImportedBranchRef:
    remote: str
    branch: str
    remote_ref: str
    remote_ref_path: str


_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def normalize_import_branch_ref(raw: str) -> ImportedBranchRef:
    value = str(raw or "").strip().replace("\\", "/")
    if value.startswith("refs/remotes/origin/"):
        branch = value.removeprefix("refs/remotes/origin/")
    elif value.startswith("origin/"):
        branch = value.removeprefix("origin/")
    elif value.startswith("refs/") or value.startswith("upstream/"):
        raise ValueError(f"Unsupported import remote/ref: {raw}")
    else:
        branch = value

    _validate_branch(branch, raw=raw)
    return ImportedBranchRef(
        remote="origin",
        branch=branch,
        remote_ref=f"origin/{branch}",
        remote_ref_path=f"refs/remotes/origin/{branch}",
    )


def imported_branch_slug(branch: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", branch.strip()).strip("-").lower()
    return slug or "imported-branch"


def build_fetch_remote_branch_command(*, repo_root: Path, branch_ref: ImportedBranchRef) -> list[str]:
    return [
        "git",
        "-C",
        str(repo_root),
        "fetch",
        branch_ref.remote,
        f"{branch_ref.branch}:{branch_ref.remote_ref_path}",
    ]


def build_import_worktree_add_command(
    *,
    repo_root: Path,
    target: Path,
    branch_ref: ImportedBranchRef,
    git_hooks_disabled: bool,
    local_branch_exists: bool = False,
) -> list[str]:
    command = ["git"]
    if git_hooks_disabled:
        command.extend(["-c", "core.hooksPath=/dev/null"])
    command.extend(["-C", str(repo_root), "worktree", "add"])
    if local_branch_exists:
        command.extend([str(target), branch_ref.branch])
        return command
    command.extend(["--track", "-b", branch_ref.branch, str(target), branch_ref.remote_ref])
    return command


def build_update_imported_worktree_command(*, worktree_root: Path, branch_ref: ImportedBranchRef) -> list[str]:
    return ["git", "-C", str(worktree_root), "merge", "--ff-only", branch_ref.remote_ref]


def list_importable_origin_branches(
    *,
    repo_root: Path,
    trees_dir_name: str = "trees",
    discovered_projects: Iterable[ImportedBranchProjectLike] = (),
    git_output: Callable[[list[str]], str] | None = None,
) -> list[str]:
    run_git = git_output or _git_output
    try:
        remote_refs = run_git(
            ["git", "-C", str(repo_root), "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]
        )
    except subprocess.CalledProcessError:
        return []
    try:
        worktree_output = run_git(["git", "-C", str(repo_root), "worktree", "list", "--porcelain"])
    except subprocess.CalledProcessError:
        worktree_output = ""
    try:
        current_branch = run_git(["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", "HEAD"]).strip()
    except subprocess.CalledProcessError:
        current_branch = ""
    checked_out_branches = _checked_out_worktree_branches(worktree_output)
    if current_branch and current_branch != "HEAD":
        checked_out_branches.add(current_branch)

    trees_root = repo_root / str(trees_dir_name).strip().rstrip("/")
    discovered = list(discovered_projects)
    represented_names = {str(getattr(project, "name", "")).strip() for project in discovered}
    represented_roots = {
        Path(getattr(project, "root")).resolve()
        for project in discovered
        if getattr(project, "root", None)
    }
    importable: list[str] = []
    seen: set[str] = set()
    for line in remote_refs.splitlines():
        remote_ref = line.strip()
        if not remote_ref or remote_ref == "origin/HEAD" or not remote_ref.startswith("origin/"):
            continue
        branch = remote_ref.removeprefix("origin/")
        try:
            normalize_import_branch_ref(branch)
        except ValueError:
            continue
        target = (trees_root / "imported" / imported_branch_slug(branch)).resolve()
        if branch in checked_out_branches:
            continue
        if target.is_dir() or target in represented_roots:
            continue
        if branch in represented_names or imported_branch_slug(branch) in represented_names:
            continue
        if branch not in seen:
            importable.append(branch)
            seen.add(branch)
    return importable


def _validate_branch(branch: str, *, raw: str) -> None:
    if not branch:
        raise ValueError("Import branch is required.")
    if branch.startswith("/") or branch.endswith("/") or "//" in branch:
        raise ValueError(f"Invalid import branch: {raw}")
    parts = branch.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"Invalid import branch: {raw}")
    if any(token in branch for token in ("*", "?", "[", "]", "~", "^", ":", "\\")):
        raise ValueError(f"Invalid import branch: {raw}")
    if branch.endswith(".lock") or "@{" in branch:
        raise ValueError(f"Invalid import branch: {raw}")
    if _SHA_RE.fullmatch(branch):
        raise ValueError("Import requires a remote branch name, not a detached commit SHA.")


def _checked_out_worktree_branches(porcelain: str) -> set[str]:
    branches: set[str] = set()
    for line in porcelain.splitlines():
        value = line.strip()
        if not value.startswith("branch "):
            continue
        branch_ref = value.removeprefix("branch ").strip()
        if branch_ref.startswith("refs/heads/"):
            branches.add(branch_ref.removeprefix("refs/heads/"))
    return branches


def _git_output(command: list[str]) -> str:
    return subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL)
