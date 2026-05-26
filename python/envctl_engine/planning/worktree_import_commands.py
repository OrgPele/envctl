from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping


@dataclass(frozen=True, slots=True)
class ImportedBranchRef:
    remote: str
    branch: str
    remote_ref: str
    local_branch: str
    slug: str
    project_name: str


class WorktreeImportError(RuntimeError):
    pass


_DETACHED_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
_INVALID_REF_CHARS_RE = re.compile(r"[\s~^:?*\\[\]\\\\]")


def normalize_import_branch_ref(raw: str, *, remote: str = "origin") -> ImportedBranchRef:
    value = str(raw or "").strip()
    if not value:
        raise ValueError("Missing branch for --import.")
    if value.startswith("refs/remotes/"):
        prefix = f"refs/remotes/{remote}/"
        if not value.startswith(prefix):
            raise ValueError("--import only supports origin remote branches in this release.")
        value = value[len(prefix) :]
    elif value.startswith("refs/heads/"):
        value = value[len("refs/heads/") :]
    elif "/" in value and value.split("/", 1)[0] != remote and value.startswith("refs/"):
        raise ValueError("--import only supports branch names or origin remote refs.")
    elif value.startswith(f"{remote}/"):
        value = value[len(remote) + 1 :]
    elif re.match(r"^[A-Za-z0-9_.-]+/", value) and value.split("/", 1)[0] != remote:
        # Treat feature/foo as a branch, but reject other remote-looking short refs when
        # the left side is exactly a configured remote name in future releases.
        pass

    branch = value.strip("/")
    if not branch or branch in {".", ".."}:
        raise ValueError("Invalid branch for --import.")
    if branch.startswith("/") or branch.endswith("/") or "//" in branch or ".." in branch:
        raise ValueError("Invalid branch for --import.")
    if branch.endswith(".lock") or "@{" in branch or _INVALID_REF_CHARS_RE.search(branch):
        raise ValueError("Invalid branch for --import.")
    if _DETACHED_SHA_RE.fullmatch(branch):
        raise ValueError("--import requires a remote branch name, not a detached commit SHA.")

    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip(".-").lower()
    slug = re.sub(r"-+", "-", slug) or "branch"
    return ImportedBranchRef(
        remote=remote,
        branch=branch,
        remote_ref=f"{remote}/{branch}",
        local_branch=branch,
        slug=slug,
        project_name=f"imported-{slug}",
    )


def build_import_fetch_command(*, repo_root: Path, ref: ImportedBranchRef) -> list[str]:
    return [
        "git",
        "-C",
        str(repo_root),
        "fetch",
        ref.remote,
        f"refs/heads/{ref.branch}:refs/remotes/{ref.remote}/{ref.branch}",
    ]


def build_import_worktree_add_command(
    *,
    repo_root: Path,
    target: Path,
    ref: ImportedBranchRef,
    git_hooks_disabled: bool,
) -> list[str]:
    command = ["git"]
    if git_hooks_disabled:
        command.extend(["-c", "core.hooksPath=/dev/null"])
    command.extend(
        [
            "-C",
            str(repo_root),
            "worktree",
            "add",
            "--track",
            "-b",
            ref.local_branch,
            str(target),
            ref.remote_ref,
        ]
    )
    return command


def build_existing_branch_worktree_add_command(
    *,
    repo_root: Path,
    target: Path,
    ref: ImportedBranchRef,
    git_hooks_disabled: bool,
) -> list[str]:
    command = ["git"]
    if git_hooks_disabled:
        command.extend(["-c", "core.hooksPath=/dev/null"])
    command.extend(
        [
            "-C",
            str(repo_root),
            "worktree",
            "add",
            str(target),
            ref.local_branch,
        ]
    )
    return command


def set_import_branch_upstream_command(*, repo_root: Path, ref: ImportedBranchRef) -> list[str]:
    return [
        "git",
        "-C",
        str(repo_root),
        "branch",
        "--set-upstream-to",
        ref.remote_ref,
        ref.local_branch,
    ]


def build_import_update_command(*, worktree_root: Path, ref: ImportedBranchRef) -> list[str]:
    return ["git", "-C", str(worktree_root), "merge", "--ff-only", ref.remote_ref]


def branch_exists_command(*, repo_root: Path, ref: ImportedBranchRef) -> list[str]:
    return ["git", "-C", str(repo_root), "show-ref", "--verify", f"refs/heads/{ref.local_branch}"]


def current_branch_command(*, worktree_root: Path) -> list[str]:
    return ["git", "-C", str(worktree_root), "rev-parse", "--abbrev-ref", "HEAD"]


def worktree_list_command(*, repo_root: Path) -> list[str]:
    return ["git", "-C", str(repo_root), "worktree", "list", "--porcelain"]


def find_worktree_for_branch(porcelain: str, *, ref: ImportedBranchRef) -> Path | None:
    current_path: Path | None = None
    for line in str(porcelain or "").splitlines():
        if line.startswith("worktree "):
            current_path = Path(line.split(" ", 1)[1])
            continue
        if line == f"branch refs/heads/{ref.local_branch}" and current_path is not None:
            return current_path
    return None


def run_import_command(
    command: list[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    run: Callable[..., object],
    timeout: float = 120.0,
) -> object:
    return run(command, cwd=cwd, env=env, timeout=timeout)
