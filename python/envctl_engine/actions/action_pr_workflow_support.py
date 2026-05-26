from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Any, Callable


def run_pr_workflow(
    context: Any,
    *,
    resolve_git_root_fn: Callable[[Path, Path], Path],
    git_available: bool,
    git_output_fn: Callable[[Path, list[str]], str],
    resolve_base_branch_fn: Callable[[Any, Path], str],
    existing_pr_url_fn: Callable[[Path, str], str],
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
    base_branch = resolve_base_branch_fn(context, git_root)

    existing_url = existing_pr_url_fn(git_root, head_branch)
    if existing_url:
        print(f"PR already exists: {existing_url}")
        return 0

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
        print_process_output_fn=print_process_output_fn,
        run_process_fn=run_process_fn,
    )


def _run_create_pr_helper(
    context: Any,
    *,
    helper: Path,
    git_root: Path,
    head_branch: str,
    base_branch: str,
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
    print_process_output_fn(created)
    if created.returncode != 0:
        return 1
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
        print_process_output_fn(created)
        if created.returncode != 0:
            return 1
        return 0
    finally:
        try:
            body_file.unlink()
        except OSError:
            pass
