from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Callable


@dataclass(frozen=True, slots=True)
class DirtyWorktreeReport:
    project_name: str
    project_root: Path
    git_root: Path
    staged: bool
    unstaged: bool
    untracked: bool

    @property
    def dirty(self) -> bool:
        return self.staged or self.unstaged or self.untracked


def resolve_git_root(project_root: Path, repo_root: Path) -> Path:
    for candidate in (project_root, repo_root):
        if (candidate / ".git").exists():
            return candidate
    return project_root


def probe_dirty_worktree(
    project_root: Path,
    repo_root: Path,
    *,
    project_name: str = "",
    git_output: Callable[[Path, list[str]], str],
) -> DirtyWorktreeReport:
    git_root = resolve_git_root(project_root, repo_root)
    status_output = git_output(git_root, ["status", "--porcelain", "--untracked-files=all"])
    staged, unstaged, untracked = classify_dirty_porcelain(status_output)
    resolved_name = project_name.strip() or project_root.name or git_root.name or "project"
    return DirtyWorktreeReport(
        project_name=resolved_name,
        project_root=project_root,
        git_root=git_root,
        staged=staged,
        unstaged=unstaged,
        untracked=untracked,
    )


def classify_dirty_porcelain(status_output: str) -> tuple[bool, bool, bool]:
    staged = False
    unstaged = False
    untracked = False
    for raw_line in str(status_output or "").splitlines():
        line = raw_line.rstrip("\n")
        if not line:
            continue
        if line.startswith("??"):
            untracked = True
            continue
        if len(line) < 2:
            continue
        index_status = line[0]
        worktree_status = line[1]
        if index_status not in {" ", "?"}:
            staged = True
        if worktree_status not in {" ", "?"}:
            unstaged = True
    return staged, unstaged, untracked


def detect_default_branch(git_root: Path, *, git_output: Callable[[Path, list[str]], str]) -> str:
    origin_default = _origin_default_branch(git_root, git_output=git_output)
    if origin_default:
        return origin_default
    for candidate in ("main", "master"):
        if git_output(git_root, ["rev-parse", "--verify", candidate]).strip():
            return candidate
    return "main"


def _origin_default_branch(git_root: Path, *, git_output: Callable[[Path, list[str]], str]) -> str:
    ref = git_output(git_root, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"]).strip()
    if ref.startswith("origin/"):
        return ref.split("origin/", 1)[1]
    remote_head = git_output(git_root, ["ls-remote", "--symref", "origin", "HEAD"])
    for line in remote_head.splitlines():
        prefix = "ref: refs/heads/"
        if line.startswith(prefix) and line.rstrip().endswith("\tHEAD"):
            return line[len(prefix) :].split("\t", 1)[0].strip()
    return ""


def detect_pr_base_branch(git_root: Path, *, git_output: Callable[[Path, list[str]], str]) -> str:
    for candidate in ("dev", "main", "master"):
        for ref in (f"origin/{candidate}", candidate):
            if git_output(git_root, ["rev-parse", "--verify", ref]).strip():
                return candidate

    remote_heads = git_output(
        git_root,
        [
            "ls-remote",
            "--heads",
            "origin",
            "refs/heads/dev",
            "refs/heads/main",
            "refs/heads/master",
        ],
    )
    remote_branches = {
        line.rsplit("refs/heads/", 1)[1].strip()
        for line in remote_heads.splitlines()
        if "refs/heads/" in line
    }
    for candidate in ("dev", "main", "master"):
        if candidate in remote_branches:
            return candidate
    return _origin_default_branch(git_root, git_output=git_output) or "master"


def existing_pr_url(
    git_root: Path,
    branch: str,
    *,
    gh_path: str | None,
    run_process: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    branch_name = branch.strip()
    if not branch_name or branch_name in {"HEAD", "unknown"}:
        return ""
    if gh_path is None:
        return ""
    listed = run_process(
        [gh_path, "pr", "list", "--head", branch_name, "--state", "open", "--json", "url", "--jq", ".[0].url"],
        cwd=str(git_root),
        text=True,
        capture_output=True,
        check=False,
    )
    if listed.returncode != 0:
        return ""
    return listed.stdout.strip()


def run_git(
    git_root: Path,
    args: list[str],
    *,
    run_process: Callable[..., subprocess.CompletedProcess[str]],
) -> subprocess.CompletedProcess[str]:
    return run_process(
        ["git", "-C", str(git_root), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def git_output(
    git_root: Path,
    args: list[str],
    *,
    run_git_fn: Callable[[Path, list[str]], subprocess.CompletedProcess[str]],
) -> str:
    result = run_git_fn(git_root, args)
    if result.returncode != 0:
        return ""
    return result.stdout


def print_process_output(result: subprocess.CompletedProcess[str]) -> None:
    stdout = str(result.stdout or "").strip()
    stderr = str(result.stderr or "").strip()
    if stdout:
        print(stdout)
    if result.returncode != 0 and stderr:
        print(stderr)


def print_error(prefix: str, result: subprocess.CompletedProcess[str]) -> None:
    output = result.stderr or result.stdout or f"exit:{result.returncode}"
    print(f"{prefix}: {output}")
