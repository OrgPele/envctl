from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


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
