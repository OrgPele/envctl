from __future__ import annotations

import json
from pathlib import Path
import sys
import time
from typing import Any, Callable, Mapping

GitOutput = Callable[[Path, list[str]], str]


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


def emit_ship_progress(message: str) -> None:
    print(message, file=sys.stderr)


def emit_ship_commit_progress(*, project_name: str, commit_sha: str) -> None:
    sha_suffix = f" ({commit_sha})." if commit_sha else "."
    emit_ship_progress(f"ship: add succeeded for {project_name}.")
    emit_ship_progress(f"ship: commit succeeded for {project_name}{sha_suffix}")
    emit_ship_progress(f"ship: push succeeded for {project_name}.")


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
    operation_statuses = ship_operation_statuses(
        status=status,
        committed=committed,
        pushed=pushed,
        pr_url=pr_url,
        pr_created=pr_created,
        checks_state=str(checks_payload.get("state", "") or ""),
        merge_conflicts=merge_conflicts,
    )
    return {
        "contract_version": "envctl.ship.v1",
        "project": context.project_name,
        "project_root": str(context.project_root.resolve()),
        "repo_root": str(context.repo_root.resolve()),
        "git_root": str(git_root.resolve()),
        "branch": branch,
        "status": status,
        "step_statuses": step_statuses or [],
        "operation_statuses": operation_statuses,
        "commit_sha": commit_sha,
        "committed": committed,
        "pushed": pushed,
        "pr_url": pr_url,
        "pr_created": pr_created,
        "checks_state": checks_payload.get("state", ""),
        "passed_checks": checks_payload.get("passed_checks", []),
        "failing_checks": checks_payload.get("failing_checks", []),
        "pending_checks": checks_payload.get("pending_checks", []),
        "checks_error": checks_payload.get("error", ""),
        "checks_expected_head_sha": checks_payload.get("expected_head_sha", ""),
        "checks_actual_head_sha": checks_payload.get("actual_head_sha", ""),
        "checks_timeout_seconds": checks_payload.get("timeout_seconds", 0.0),
        "merge_conflicts": dict(merge_conflicts or {}),
        "monitor_duration_seconds": checks_payload.get("duration_seconds", 0.0),
        "duration_seconds": round(time.monotonic() - started, 3),
        "protected_local_artifacts_skipped": protected_paths or [],
    }


def ship_operation_statuses(
    *,
    status: str,
    committed: bool,
    pushed: bool,
    pr_url: str,
    pr_created: bool,
    checks_state: str,
    merge_conflicts: Mapping[str, object] | None,
) -> dict[str, str]:
    return {
        "commit": _commit_status(status=status, committed=committed),
        "push": _push_status(status=status, committed=committed, pushed=pushed),
        "pr": _pr_status(status=status, pr_url=pr_url, pr_created=pr_created),
        "merge_conflicts": _merge_conflict_status(status=status, merge_conflicts=merge_conflicts),
        "checks": checks_state or _checks_status(status),
    }


def _commit_status(*, status: str, committed: bool) -> str:
    if status == "commit_failed":
        return "failed"
    if status in {"git_unavailable", "detached_head"}:
        return "not_run"
    return "success" if committed else "no_changes"


def _push_status(*, status: str, committed: bool, pushed: bool) -> str:
    if status == "commit_failed":
        return "failed"
    if status in {"git_unavailable", "detached_head"}:
        return "not_run"
    if pushed:
        return "success"
    return "not_needed" if not committed else "unknown"


def _pr_status(*, status: str, pr_url: str, pr_created: bool) -> str:
    if status == "pr_failed":
        return "failed"
    if status in {"git_unavailable", "detached_head", "commit_failed"}:
        return "not_run"
    if pr_created:
        return "created"
    if pr_url:
        return "existing"
    return "unresolved"


def _merge_conflict_status(*, status: str, merge_conflicts: Mapping[str, object] | None) -> str:
    if status == "merge_conflicts" or dict(merge_conflicts or {}).get("state") == "conflicts":
        return "conflicts"
    if status in {"git_unavailable", "detached_head", "commit_failed", "pr_failed"}:
        return "not_checked"
    return "none"


def _checks_status(status: str) -> str:
    if status in {"checks_passed", "checks_failed", "checks_pending_timeout", "gh_unavailable", "no_checks_reported"}:
        return status
    return "not_run"


def print_ship_result(payload: Mapping[str, object], *, json_output: bool, ok: bool) -> int:
    if json_output:
        print(json.dumps(dict(payload), indent=2, sort_keys=True))
    else:
        status = str(payload.get("status") or "ship_complete")
        pr_url = str(payload.get("pr_url") or "").strip()
        pr_state = str(dict(payload.get("operation_statuses") or {}).get("pr") or "")
        pr_suffix = f" pr={pr_state}" if pr_state else ""
        print(f"ship: {status}{pr_suffix}" + (f" {pr_url}" if pr_url else ""))
    return 0 if ok else 1


def parse_ship_json_output(context: Any) -> bool:
    env = getattr(context, "env", {})
    human = str(env.get("ENVCTL_ACTION_HUMAN", "")).strip().lower()
    if human in {"1", "true", "yes", "on"}:
        return False
    return True


__all__ = [
    "emit_ship_commit_progress",
    "emit_ship_progress",
    "GitOutput",
    "parse_ship_json_output",
    "print_ship_result",
    "ship_payload",
    "ship_operation_statuses",
    "ship_protected_paths",
]
