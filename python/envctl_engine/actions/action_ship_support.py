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
    failing_states = {"FAILURE", "FAILED", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}
    passing_states = {"SUCCESS", "PASSED", "COMPLETED", "NEUTRAL", "SKIPPED"}
    failing = [check for check in checks if str(check.get("state", "")).upper() in failing_states]
    pending = [check for check in checks if str(check.get("state", "")).upper() not in failing_states | passing_states]
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
        "duration_seconds": duration,
    }


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
