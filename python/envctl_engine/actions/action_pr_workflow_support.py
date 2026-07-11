from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any, Callable

from envctl_engine.actions.action_git_state_support import ExistingPullRequest


ExistingPullRequestLookup = Callable[[Path, str], ExistingPullRequest | None]
PullRequestBaseUpdater = Callable[[Path, ExistingPullRequest, str], subprocess.CompletedProcess[str]]


def run_pr_workflow(
    context: Any,
    *,
    resolve_git_root_fn: Callable[[Path, Path], Path],
    git_available: bool,
    git_output_fn: Callable[[Path, list[str]], str],
    resolve_base_branch_fn: Callable[[Any, Path], str],
    existing_pull_request_fn: ExistingPullRequestLookup,
    update_pull_request_base_fn: PullRequestBaseUpdater,
    probe_dirty_worktree_fn: Callable[[Path, Path, str], Any],
    run_commit_action_fn: Callable[[Any], int],
    pr_title_fn: Callable[[Any, Path, str], str],
    pr_body_fn: Callable[[Any, Path, str, str], str],
    write_pr_body_file_fn: Callable[[str], Path],
    print_process_output_fn: Callable[[subprocess.CompletedProcess[str]], None],
    gh_path: str | None,
    run_process_fn: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> int:
    git_root = resolve_git_root_fn(context.project_root, context.repo_root)
    if not git_available:
        print("git is required for pr action")
        return 1

    head_branch = git_output_fn(git_root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip() or "unknown"
    if head_branch in {"HEAD", "unknown"}:
        print(f"Skipping {context.project_name} (detached HEAD).")
        return 0

    explicit_base = _explicit_pr_base(context)
    existing = existing_pull_request_fn(git_root, head_branch)
    if existing is not None:
        if explicit_base and existing.base_branch != explicit_base:
            if not _update_existing_pull_request_base(
                git_root=git_root,
                head_branch=head_branch,
                existing=existing,
                desired_base=explicit_base,
                existing_pull_request_fn=existing_pull_request_fn,
                update_pull_request_base_fn=update_pull_request_base_fn,
                print_process_output_fn=print_process_output_fn,
            ):
                return 1
        print(f"PR already exists: {existing.url}")
        return 0

    base_branch = resolve_base_branch_fn(context, git_root)
    if base_branch and head_branch == base_branch:
        print(
            f"Cannot open a pull request from {head_branch!r} into itself. Create or switch to a feature branch first."
        )
        return 1

    dirty_report = probe_dirty_worktree_fn(context.project_root, context.repo_root, context.project_name)
    if dirty_report.dirty:
        print(f"Dirty worktree detected for {context.project_name}; committing and pushing before PR creation.")
        commit_code = run_commit_action_fn(context)
        if commit_code != 0:
            return commit_code

    helper = context.repo_root / "utils" / "create-pr.sh"
    if helper.is_file() and os.access(helper, os.X_OK):
        return _run_create_pr_helper(
            context,
            helper=helper,
            git_root=git_root,
            head_branch=head_branch,
            base_branch=base_branch,
            existing_pull_request_fn=existing_pull_request_fn,
            print_process_output_fn=print_process_output_fn,
            run_process_fn=run_process_fn,
        )

    if gh_path is None:
        print("gh is required for pr action when utils/create-pr.sh is unavailable")
        return 1
    return _run_gh_pr_create(
        context,
        git_root=git_root,
        head_branch=head_branch,
        base_branch=base_branch,
        gh_path=gh_path,
        pr_title_fn=pr_title_fn,
        pr_body_fn=pr_body_fn,
        write_pr_body_file_fn=write_pr_body_file_fn,
        existing_pull_request_fn=existing_pull_request_fn,
        print_process_output_fn=print_process_output_fn,
        run_process_fn=run_process_fn,
    )


def _explicit_pr_base(context: Any) -> str:
    env = getattr(context, "env", {})
    try:
        return str(env.get("ENVCTL_PR_BASE", "")).strip()
    except AttributeError:
        return ""


def _update_existing_pull_request_base(
    *,
    git_root: Path,
    head_branch: str,
    existing: ExistingPullRequest,
    desired_base: str,
    existing_pull_request_fn: ExistingPullRequestLookup,
    update_pull_request_base_fn: PullRequestBaseUpdater,
    print_process_output_fn: Callable[[subprocess.CompletedProcess[str]], None],
) -> bool:
    updated = update_pull_request_base_fn(git_root, existing, desired_base)
    if updated.returncode != 0:
        refreshed = existing_pull_request_fn(git_root, head_branch)
        if _pull_request_targets(refreshed, desired_base):
            return True
        print_process_output_fn(updated)
        print(
            f"Unable to update existing PR {existing.url} from base "
            f"{existing.base_branch or '<unknown>'!r} to {desired_base!r}."
        )
        return False

    refreshed = existing_pull_request_fn(git_root, head_branch)
    if not _pull_request_targets(refreshed, desired_base):
        actual_base = refreshed.base_branch if refreshed is not None else "<unavailable>"
        print(
            f"Updated existing PR {existing.url}, but could not verify base {desired_base!r} "
            f"(reported {actual_base!r})."
        )
        return False
    print(f"Updated PR base to {desired_base}: {refreshed.url}")
    return True


def _pull_request_targets(pull_request: ExistingPullRequest | None, base_branch: str) -> bool:
    return pull_request is not None and pull_request.base_branch == base_branch


def _run_create_pr_helper(
    context: Any,
    *,
    helper: Path,
    git_root: Path,
    head_branch: str,
    base_branch: str,
    existing_pull_request_fn: ExistingPullRequestLookup,
    print_process_output_fn: Callable[[subprocess.CompletedProcess[str]], None],
    run_process_fn: Callable[..., subprocess.CompletedProcess[str]],
) -> int:
    command = [str(helper)]
    if base_branch:
        command.extend(["--base", base_branch])
    command.extend(["--head", head_branch, "--workdir", str(git_root)])
    created = run_process_fn(
        command,
        cwd=str(context.repo_root),
        text=True,
        capture_output=True,
        check=False,
    )
    if created.returncode != 0:
        if _recover_concurrent_pull_request(
            git_root=git_root,
            head_branch=head_branch,
            desired_base=base_branch,
            existing_pull_request_fn=existing_pull_request_fn,
        ):
            return 0
        print_process_output_fn(created)
        return 1
    print_process_output_fn(created)
    return 0


def _run_gh_pr_create(
    context: Any,
    *,
    git_root: Path,
    head_branch: str,
    base_branch: str,
    gh_path: str,
    pr_title_fn: Callable[[Any, Path, str], str],
    pr_body_fn: Callable[[Any, Path, str, str], str],
    write_pr_body_file_fn: Callable[[str], Path],
    existing_pull_request_fn: ExistingPullRequestLookup,
    print_process_output_fn: Callable[[subprocess.CompletedProcess[str]], None],
    run_process_fn: Callable[..., subprocess.CompletedProcess[str]],
) -> int:
    title = pr_title_fn(context, git_root, head_branch)
    body = pr_body_fn(context, git_root, head_branch, base_branch)
    body_file = write_pr_body_file_fn(body)
    args = [gh_path, "pr", "create", "--title", title, "--body-file", str(body_file), "--head", head_branch]
    if base_branch:
        args.extend(["--base", base_branch])
    try:
        created = run_process_fn(args, cwd=str(git_root), text=True, capture_output=True, check=False)
        if created.returncode != 0:
            if _recover_concurrent_pull_request(
                git_root=git_root,
                head_branch=head_branch,
                desired_base=base_branch,
                existing_pull_request_fn=existing_pull_request_fn,
            ):
                return 0
            print_process_output_fn(created)
            return 1
        print_process_output_fn(created)
        return 0
    finally:
        try:
            body_file.unlink()
        except OSError:
            pass


def _recover_concurrent_pull_request(
    *,
    git_root: Path,
    head_branch: str,
    desired_base: str,
    existing_pull_request_fn: ExistingPullRequestLookup,
) -> bool:
    existing = existing_pull_request_fn(git_root, head_branch)
    if not _pull_request_targets(existing, desired_base):
        return False
    print(f"PR already exists: {existing.url}")
    return True
