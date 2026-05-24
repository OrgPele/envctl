from __future__ import annotations

import json
from pathlib import Path
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


__all__ = [
    "GitOutput",
    "parse_ship_json_output",
    "print_ship_result",
    "ship_payload",
    "ship_protected_paths",
]
