from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any, Callable, Mapping

GitOutput = Callable[[Path, list[str]], str]
RunGit = Callable[[Path, list[str]], subprocess.CompletedProcess[str]]
ResolveBaseBranch = Callable[[Any, Path], str]
ResolveBaseRef = Callable[[Path, str], str]

FAILING_CHECK_STATES = {"FAILURE", "FAILED", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}
PASSING_CHECK_STATES = {"SUCCESS", "PASSED", "COMPLETED", "NEUTRAL", "SKIPPED"}


def ship_protected_paths(
    git_root: Path,
    *,
    git_output: GitOutput,
    partition_envctl_protected_paths: Callable[[str], Any],
    ordered_unique_paths: Callable[..., list[str]],
) -> list[str]:
    status_output = git_output(git_root, ["status", "--porcelain", "--untracked-files=all"])
    partition = partition_envctl_protected_paths(status_output)
    return ordered_unique_paths(partition.protected_staged_paths, partition.protected_skipped_paths)


def ship_payload(
    *,
    context: Any,
    git_root: Path,
    branch: str,
    status: str,
    started: float,
    commit_sha: str = "",
    committed: bool = False,
    pushed: bool = False,
    pr_url: str = "",
    pr_created: bool = False,
    protected_paths: list[str] | None = None,
    checks: Mapping[str, object] | None = None,
    step_statuses: list[str] | None = None,
    merge_conflicts: Mapping[str, object] | None = None,
) -> dict[str, object]:
    checks_payload = dict(checks or {})
    return {
        "contract_version": "envctl.ship.v1",
        "project": context.project_name,
        "project_root": str(context.project_root.resolve()),
        "repo_root": str(context.repo_root.resolve()),
        "git_root": str(git_root.resolve()),
        "branch": branch,
        "status": status,
        "step_statuses": step_statuses or [],
        "commit_sha": commit_sha,
        "committed": committed,
        "pushed": pushed,
        "pr_url": pr_url,
        "pr_created": pr_created,
        "checks_state": checks_payload.get("state", ""),
        "failing_checks": checks_payload.get("failing_checks", []),
        "pending_checks": checks_payload.get("pending_checks", []),
        "merge_conflicts": dict(merge_conflicts or {}),
        "monitor_duration_seconds": checks_payload.get("duration_seconds", 0.0),
        "duration_seconds": round(time.monotonic() - started, 3),
        "protected_local_artifacts_skipped": protected_paths or [],
    }


def print_ship_result(payload: Mapping[str, object], *, json_output: bool, ok: bool) -> int:
    if json_output:
        print(json.dumps(dict(payload), indent=2, sort_keys=True))
    else:
        status = str(payload.get("status") or "ship_complete")
        pr_url = str(payload.get("pr_url") or "").strip()
        print(f"ship: {status}" + (f" {pr_url}" if pr_url else ""))
    return 0 if ok else 1


def parse_ship_json_output(context: Any) -> bool:
    raw = str(getattr(context, "env", {}).get("ENVCTL_ACTION_JSON", "")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def existing_merge_conflict_report(git_root: Path, *, branch: str, git_output: GitOutput) -> dict[str, object]:
    paths = [path for path in git_output(git_root, ["diff", "--name-only", "--diff-filter=U"]).splitlines() if path]
    if not paths:
        return {
            "state": "clean",
            "type": "unmerged_index",
            "base_ref": "",
            "head_ref": branch or "HEAD",
            "merge_base": "",
            "conflicting_files": [],
            "resolution_steps": [],
            "messages": [],
        }
    stage_entries = unmerged_stage_entries(git_root, git_output=git_output)
    files: list[dict[str, object]] = []
    for path in paths:
        entries = stage_entries.get(path, [])
        stages = sorted({str(entry.get("stage", "")) for entry in entries if entry.get("stage")})
        files.append(
            {
                "path": path,
                "kind": "unmerged_index",
                "stages": stages,
                "stage_entries": entries,
                "messages": [f"Unmerged index entries exist for {path}."],
            }
        )
    return {
        "state": "conflicts",
        "type": "unmerged_index",
        "base_ref": "",
        "head_ref": branch or "HEAD",
        "merge_base": "",
        "conflicting_files": files,
        "resolution_steps": [
            "Open each conflicting file and resolve conflict markers.",
            "git add <resolved-file>",
            "rerun envctl ship --project <name> --json",
        ],
        "messages": ["The worktree already has unresolved merge conflicts."],
    }


def predicted_merge_conflict_report(
    context: Any,
    git_root: Path,
    *,
    branch: str,
    resolve_base_branch: ResolveBaseBranch,
    resolve_base_ref: ResolveBaseRef,
    run_git: RunGit,
    git_output: GitOutput,
) -> dict[str, object]:
    del branch
    base_branch = resolve_base_branch(context, git_root)
    base_ref = resolve_base_ref(git_root, base_branch)
    if not base_ref:
        return {
            "state": "unknown",
            "type": "predicted_merge",
            "base_branch": base_branch,
            "base_ref": "",
            "head_ref": "HEAD",
            "merge_base": "",
            "conflicting_files": [],
            "resolution_steps": [],
            "messages": [f"Unable to resolve PR base branch '{base_branch}' for conflict prediction."],
        }
    merge_base = git_output(git_root, ["merge-base", "HEAD", base_ref]).strip()
    completed = run_git(git_root, ["merge-tree", "--write-tree", "--messages", "--name-only", "HEAD", base_ref])
    if completed.returncode == 0:
        return {
            "state": "clean",
            "type": "predicted_merge",
            "base_branch": base_branch,
            "base_ref": base_ref,
            "head_ref": "HEAD",
            "merge_base": merge_base,
            "conflicting_files": [],
            "resolution_steps": [],
            "messages": [],
        }
    if completed.returncode == 1:
        conflict_files = parse_merge_tree_conflicts(completed.stdout)
        return {
            "state": "conflicts",
            "type": "predicted_merge",
            "base_branch": base_branch,
            "base_ref": base_ref,
            "head_ref": "HEAD",
            "merge_base": merge_base,
            "conflicting_files": conflict_files,
            "resolution_steps": [
                f"git fetch origin {base_branch}",
                f"git merge {base_ref}",
                "Resolve each file listed in merge_conflicts.conflicting_files.",
                "git add <resolved-file>",
                "rerun envctl ship --project <name> --json",
            ],
            "messages": [line for line in completed.stdout.splitlines() if line.strip().startswith("CONFLICT")],
        }
    return {
        "state": "unknown",
        "type": "predicted_merge",
        "base_branch": base_branch,
        "base_ref": base_ref,
        "head_ref": "HEAD",
        "merge_base": merge_base,
        "conflicting_files": [],
        "resolution_steps": [],
        "messages": [(completed.stderr or completed.stdout).strip()],
    }


def unmerged_stage_entries(git_root: Path, *, git_output: GitOutput) -> dict[str, list[dict[str, str]]]:
    entries: dict[str, list[dict[str, str]]] = {}
    for line in git_output(git_root, ["ls-files", "-u"]).splitlines():
        left, sep, path = line.partition("\t")
        if not sep or not path:
            continue
        parts = left.split()
        if len(parts) < 3:
            continue
        entry = {"mode": parts[0], "object": parts[1], "stage": parts[2], "path": path}
        entries.setdefault(path, []).append(entry)
    return entries


def parse_merge_tree_conflicts(output: str) -> list[dict[str, object]]:
    lines = output.splitlines()
    path_lines: list[str] = []
    message_lines: list[str] = []
    reading_paths = False
    for index, line in enumerate(lines):
        if index == 0:
            reading_paths = True
            continue
        if reading_paths and not line.strip():
            reading_paths = False
            continue
        if reading_paths:
            path_lines.append(line.strip())
        elif line.strip():
            message_lines.append(line.strip())
    files: list[dict[str, object]] = []
    for path in path_lines:
        messages = [line for line in message_lines if path in line]
        messages = sorted(messages, key=lambda line: 0 if line.startswith("CONFLICT") else 1)
        files.append(
            {
                "path": path,
                "kind": "predicted_merge",
                "messages": messages or list(message_lines),
            }
        )
    return files


def github_pr_checks(git_root: Path, *, branch: str, pr_url: str) -> dict[str, object]:
    del pr_url
    gh_path = shutil.which("gh")
    if gh_path is None:
        return {
            "state": "gh_unavailable",
            "failing_checks": [],
            "pending_checks": [],
            "duration_seconds": 0.0,
        }
    started = time.monotonic()
    completed = subprocess.run(
        [gh_path, "pr", "checks", branch, "--json", "name,state,workflow,link"],
        cwd=str(git_root),
        text=True,
        capture_output=True,
        check=False,
    )
    duration = round(time.monotonic() - started, 3)
    if completed.returncode != 0:
        return {
            "state": "checks_pending_timeout",
            "failing_checks": [],
            "pending_checks": [],
            "duration_seconds": duration,
            "error": (completed.stderr or completed.stdout).strip(),
        }
    try:
        loaded = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        loaded = []
    checks = loaded if isinstance(loaded, list) else []
    return normalize_github_pr_checks(checks, duration_seconds=duration)


def normalize_github_pr_checks(
    checks: list[Mapping[str, object]],
    *,
    duration_seconds: float,
) -> dict[str, object]:
    failing = [check for check in checks if str(check.get("state", "")).upper() in FAILING_CHECK_STATES]
    pending = [
        check
        for check in checks
        if str(check.get("state", "")).upper() not in FAILING_CHECK_STATES | PASSING_CHECK_STATES
    ]
    if failing:
        state = "checks_failed"
    elif pending:
        state = "checks_pending_timeout"
    else:
        state = "checks_passed"
    return {
        "state": state,
        "failing_checks": failing,
        "pending_checks": pending,
        "duration_seconds": duration_seconds,
    }


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
    "normalize_github_pr_checks",
    "parse_merge_tree_conflicts",
    "predicted_merge_conflict_report",
    "print_ship_result",
    "run_ship_workflow",
    "ship_payload",
    "ship_protected_paths",
    "unmerged_stage_entries",
]
