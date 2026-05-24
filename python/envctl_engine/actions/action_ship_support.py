from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Callable

from envctl_engine.actions.action_ship_check_support import github_pr_checks
from envctl_engine.actions.action_ship_conflict_support import (
    GitOutput,
    ResolveBaseBranch,
    ResolveBaseRef,
    RunGit,
    existing_merge_conflict_report,
    parse_merge_tree_conflicts,
    predicted_merge_conflict_report,
    unmerged_stage_entries,
)
from envctl_engine.actions.action_ship_result_support import (
    parse_ship_json_output,
    print_ship_result,
    ship_payload,
    ship_protected_paths,
)


def run_ship_workflow(
    context: Any,
    *,
    resolve_git_root: Callable[[Path, Path], Path],
    git_available: bool,
    git_output: GitOutput,
    run_git: RunGit,
    resolve_base_branch: ResolveBaseBranch,
    resolve_base_ref: ResolveBaseRef,
    run_commit_action: Callable[[Any], int],
    run_pr_action: Callable[[Any], int],
    probe_dirty_worktree: Callable[..., Any],
    existing_pr_url: Callable[[Path, str], str],
    partition_envctl_protected_paths: Callable[[str], Any],
    ordered_unique_paths: Callable[..., list[str]],
    github_pr_checks: Callable[[Path], dict[str, object]] | None = None,
) -> int:
    git_root = resolve_git_root(context.project_root, context.repo_root)
    json_output = parse_ship_json_output(context)
    started = time.monotonic()
    if not git_available:
        payload = ship_payload(
            context=context,
            git_root=git_root,
            branch="",
            status="git_unavailable",
            started=started,
        )
        return print_ship_result(payload, json_output=json_output, ok=False)

    branch = git_output(git_root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if not branch or branch == "HEAD":
        payload = ship_payload(
            context=context,
            git_root=git_root,
            branch=branch or "HEAD",
            status="detached_head",
            started=started,
        )
        return print_ship_result(payload, json_output=json_output, ok=True)

    existing_conflicts = existing_merge_conflict_report(git_root, branch=branch, git_output=git_output)
    if existing_conflicts.get("state") == "conflicts":
        payload = ship_payload(
            context=context,
            git_root=git_root,
            branch=branch,
            status="merge_conflicts",
            started=started,
            merge_conflicts=existing_conflicts,
            step_statuses=["merge_conflicts"],
        )
        return print_ship_result(payload, json_output=json_output, ok=False)

    before_sha = git_output(git_root, ["rev-parse", "HEAD"]).strip()
    protected_paths = ship_protected_paths(
        git_root,
        git_output=git_output,
        partition_envctl_protected_paths=partition_envctl_protected_paths,
        ordered_unique_paths=ordered_unique_paths,
    )
    pre_commit_dirty = probe_dirty_worktree(
        context.project_root,
        context.repo_root,
        project_name=context.project_name,
    ).dirty
    step_statuses: list[str] = []
    existing_url = existing_pr_url(git_root, branch)

    commit_code = run_commit_action(context)
    after_sha = git_output(git_root, ["rev-parse", "HEAD"]).strip()
    committed = bool(after_sha and before_sha and after_sha != before_sha) or bool(
        pre_commit_dirty and commit_code == 0
    )
    step_statuses.append("committed_pushed" if committed else "clean_no_changes")
    if commit_code != 0:
        payload = ship_payload(
            context=context,
            git_root=git_root,
            branch=branch,
            status="commit_failed",
            started=started,
            commit_sha=after_sha,
            committed=committed,
            protected_paths=protected_paths,
            step_statuses=step_statuses,
        )
        return print_ship_result(payload, json_output=json_output, ok=False)

    pr_url = existing_url
    pr_created = False
    if not pr_url:
        pr_code = run_pr_action(context)
        if pr_code != 0:
            payload = ship_payload(
                context=context,
                git_root=git_root,
                branch=branch,
                status="pr_failed",
                started=started,
                commit_sha=after_sha,
                committed=committed,
                protected_paths=protected_paths,
                step_statuses=step_statuses,
            )
            return print_ship_result(payload, json_output=json_output, ok=False)
        pr_url = existing_pr_url(git_root, branch)
        pr_created = bool(pr_url)
        step_statuses.append("pr_created" if pr_created else "pr_unresolved")
    else:
        step_statuses.append("pr_exists")

    merge_conflicts = predicted_merge_conflict_report(
        context,
        git_root,
        branch=branch,
        resolve_base_branch=resolve_base_branch,
        resolve_base_ref=resolve_base_ref,
        run_git=run_git,
        git_output=git_output,
    )
    if merge_conflicts.get("state") == "conflicts":
        step_statuses.append("merge_conflicts")
        payload = ship_payload(
            context=context,
            git_root=git_root,
            branch=branch,
            status="merge_conflicts",
            started=started,
            commit_sha=after_sha,
            committed=committed,
            pushed=committed,
            pr_url=pr_url,
            pr_created=pr_created,
            protected_paths=protected_paths,
            checks={"state": "merge_conflicts", "failing_checks": [], "pending_checks": []},
            step_statuses=step_statuses,
            merge_conflicts=merge_conflicts,
        )
        return print_ship_result(payload, json_output=json_output, ok=False)

    checks_fn = github_pr_checks or globals()["github_pr_checks"]
    checks = checks_fn(git_root, branch=branch, pr_url=pr_url)  # type: ignore[call-arg]
    status = str(checks.get("state") or ("pr_created" if pr_created else "pr_exists"))
    if status:
        step_statuses.append(status)
    payload = ship_payload(
        context=context,
        git_root=git_root,
        branch=branch,
        status=status,
        started=started,
        commit_sha=after_sha,
        committed=committed,
        pushed=committed,
        pr_url=pr_url,
        pr_created=pr_created,
        protected_paths=protected_paths,
        checks=checks,
        step_statuses=step_statuses,
        merge_conflicts=merge_conflicts,
    )
    ok = status not in {"checks_failed", "commit_failed", "pr_failed"}
    return print_ship_result(payload, json_output=json_output, ok=ok)


_parse_json_output = parse_ship_json_output


__all__ = [
    "GitOutput",
    "ResolveBaseBranch",
    "ResolveBaseRef",
    "RunGit",
    "_parse_json_output",
    "existing_merge_conflict_report",
    "github_pr_checks",
    "parse_merge_tree_conflicts",
    "predicted_merge_conflict_report",
    "print_ship_result",
    "run_ship_workflow",
    "ship_payload",
    "ship_protected_paths",
    "unmerged_stage_entries",
]
