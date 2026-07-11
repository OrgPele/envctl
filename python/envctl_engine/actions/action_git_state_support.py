from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Callable

from envctl_engine.shared.git_branch_support import (
    PREFERRED_PR_BASE_BRANCHES,
    detect_preferred_default_branch,
)


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


@dataclass(frozen=True, slots=True)
class ExistingPullRequest:
    url: str
    base_branch: str


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
    return detect_preferred_default_branch(
        lambda args: git_output(git_root, list(args)),
        probe_remote_heads=True,
    )


def detect_pr_base_branch(git_root: Path, *, git_output: Callable[[Path, list[str]], str]) -> str:
    for branch in PREFERRED_PR_BASE_BRANCHES:
        for ref in (f"refs/remotes/origin/{branch}", f"refs/heads/{branch}"):
            if git_output(git_root, ["rev-parse", "--verify", ref]).strip():
                return branch
    return detect_default_branch(git_root, git_output=git_output)


def existing_pull_request(
    git_root: Path,
    branch: str,
    *,
    gh_path: str | None,
    run_process: Callable[..., subprocess.CompletedProcess[str]],
) -> ExistingPullRequest | None:
    branch_name = branch.strip()
    if not branch_name or branch_name in {"HEAD", "unknown"}:
        return None
    if gh_path is None:
        return None
    listed = run_process(
        [
            gh_path,
            "pr",
            "list",
            "--head",
            branch_name,
            "--state",
            "open",
            "--limit",
            "1",
            "--json",
            "url,baseRefName",
        ],
        cwd=str(git_root),
        text=True,
        capture_output=True,
        check=False,
    )
    if listed.returncode != 0:
        return None
    try:
        payload = json.loads(listed.stdout or "[]")
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        return None
    url = str(payload[0].get("url") or "").strip()
    if not url:
        return None
    return ExistingPullRequest(
        url=url,
        base_branch=str(payload[0].get("baseRefName") or "").strip(),
    )


def existing_pr_url(
    git_root: Path,
    branch: str,
    *,
    gh_path: str | None,
    run_process: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    existing = existing_pull_request(
        git_root,
        branch,
        gh_path=gh_path,
        run_process=run_process,
    )
    return existing.url if existing is not None else ""


def update_pull_request_base(
    git_root: Path,
    pull_request: ExistingPullRequest,
    base_branch: str,
    *,
    gh_path: str | None,
    run_process: Callable[..., subprocess.CompletedProcess[str]],
) -> subprocess.CompletedProcess[str]:
    branch = base_branch.strip()
    command = [*([gh_path] if gh_path else ["gh"]), "pr", "edit", pull_request.url, "--base", branch]
    if gh_path is None:
        return subprocess.CompletedProcess(
            command,
            127,
            stdout="",
            stderr=(
                "gh is required to update the existing pull request base. "
                f"Install or authenticate gh, then run: gh pr edit {pull_request.url} --base {branch}"
            ),
        )
    return run_process(
        command,
        cwd=str(git_root),
        text=True,
        capture_output=True,
        check=False,
    )


def run_git(
    git_root: Path,
    args: list[str],
    *,
    run_process: Callable[..., subprocess.CompletedProcess[str]],
) -> subprocess.CompletedProcess[str]:
    command = ["git", "-C", str(git_root), *args]
    options: dict[str, object] = {
        "text": True,
        "capture_output": True,
        "check": False,
    }
    if args[:1] == ["ls-remote"]:
        options["timeout"] = 10
        options["env"] = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        return run_process(command, **options)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            command,
            124,
            stdout=str(exc.stdout or ""),
            stderr="Timed out while querying remote branches.",
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
