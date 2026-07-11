from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

from envctl_engine.actions.action_git_state_support import (
    ExistingPullRequest,
    existing_pr_url as lookup_existing_pr_url,
    existing_pull_request as lookup_existing_pull_request,
    update_pull_request_base as update_existing_pull_request_base,
)


def existing_pr_url(git_root: Path, branch: str) -> str:
    return lookup_existing_pr_url(
        git_root,
        branch,
        gh_path=shutil.which("gh"),
        run_process=subprocess.run,
    )


def existing_pull_request(git_root: Path, branch: str) -> ExistingPullRequest | None:
    return lookup_existing_pull_request(
        git_root,
        branch,
        gh_path=shutil.which("gh"),
        run_process=subprocess.run,
    )


def update_pull_request_base(
    git_root: Path,
    pull_request: ExistingPullRequest,
    base_branch: str,
) -> subprocess.CompletedProcess[str]:
    return update_existing_pull_request_base(
        git_root,
        pull_request,
        base_branch,
        gh_path=shutil.which("gh"),
        run_process=subprocess.run,
    )


__all__ = ["existing_pr_url", "existing_pull_request", "update_pull_request_base"]
