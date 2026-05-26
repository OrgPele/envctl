from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time
from typing import Callable, Mapping

from envctl_engine.actions.action_ship_check_results import (
    normalize_github_pr_checks,
    normalize_status_rollup_check,
    target_status_checks,
)
from envctl_engine.actions.action_ship_failure_logs import failed_checks_with_log_excerpts

RunCommand = Callable[..., subprocess.CompletedProcess[str]]
MonotonicClock = Callable[[], float]


def query_expected_head_pr_checks(
    git_root: Path,
    *,
    gh_path: str,
    branch: str,
    pr_url: str,
    expected_head_sha: str,
    started: float,
    no_checks_grace_seconds: float,
    run_command: RunCommand = subprocess.run,
    monotonic: MonotonicClock = time.monotonic,
) -> dict[str, object]:
    completed = run_command(
        [gh_path, "pr", "view", branch, "--json", "headRefOid,statusCheckRollup,url"],
        cwd=str(git_root),
        text=True,
        capture_output=True,
        check=False,
    )
    duration = round(monotonic() - started, 3)
    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout).strip()
        return _pending_expected_head_result(
            duration_seconds=duration,
            expected_head_sha=expected_head_sha,
            actual_head_sha="",
            error=error or "GitHub PR status is not available yet.",
            pr_url=pr_url,
        )

    try:
        loaded = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        loaded = {}
    data = loaded if isinstance(loaded, Mapping) else {}
    actual_head_sha = str(data.get("headRefOid") or "").strip()
    if actual_head_sha != expected_head_sha:
        return _pending_expected_head_result(
            duration_seconds=duration,
            expected_head_sha=expected_head_sha,
            actual_head_sha=actual_head_sha,
            error="GitHub has not attached PR checks to the pushed head commit yet.",
            pr_url=str(data.get("url") or pr_url),
        )

    rollup = data.get("statusCheckRollup")
    checks = (
        [normalize_status_rollup_check(item) for item in rollup if isinstance(item, Mapping)]
        if isinstance(rollup, list)
        else []
    )
    target_checks = target_status_checks(checks)
    if not target_checks:
        if duration < no_checks_grace_seconds:
            return {
                "state": "checks_pending_timeout",
                "failing_checks": [],
                "passed_checks": [],
                "pending_checks": [
                    {
                        "name": "github_checks",
                        "state": "WAITING",
                        "expected_head_sha": expected_head_sha,
                    }
                ],
                "duration_seconds": duration,
                "expected_head_sha": expected_head_sha,
                "pr_url": str(data.get("url") or pr_url),
                "error": "GitHub has not reported target test check contexts for the pushed head commit yet.",
            }
        return {
            "state": "no_checks_reported",
            "failing_checks": [],
            "passed_checks": [],
            "pending_checks": [],
            "duration_seconds": duration,
            "expected_head_sha": expected_head_sha,
            "pr_url": str(data.get("url") or pr_url),
        }

    normalized = normalize_github_pr_checks(target_checks, duration_seconds=duration)
    normalized["expected_head_sha"] = expected_head_sha
    normalized["actual_head_sha"] = actual_head_sha
    normalized["pr_url"] = str(data.get("url") or pr_url)
    if normalized["state"] == "checks_failed":
        normalized["failing_checks"] = failed_checks_with_log_excerpts(
            git_root,
            gh_path=gh_path,
            failing_checks=normalized["failing_checks"],  # type: ignore[arg-type]
        )
    return normalized


def query_github_pr_checks(
    git_root: Path,
    *,
    gh_path: str,
    branch: str,
    started: float,
    run_command: RunCommand = subprocess.run,
    monotonic: MonotonicClock = time.monotonic,
) -> dict[str, object]:
    completed = run_command(
        [gh_path, "pr", "checks", branch, "--json", "name,state,workflow,link"],
        cwd=str(git_root),
        text=True,
        capture_output=True,
        check=False,
    )
    duration = round(monotonic() - started, 3)
    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout).strip()
        if "no checks reported" in error.casefold():
            return {
                "state": "no_checks_reported",
                "failing_checks": [],
                "passed_checks": [],
                "pending_checks": [],
                "duration_seconds": duration,
                "error": error,
            }
        return {
            "state": "checks_pending_timeout",
            "failing_checks": [],
            "passed_checks": [],
            "pending_checks": [],
            "duration_seconds": duration,
            "error": error,
        }
    try:
        loaded = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        loaded = []
    checks = loaded if isinstance(loaded, list) else []
    target_checks = target_status_checks(checks)
    if not target_checks:
        return {
            "state": "no_checks_reported",
            "failing_checks": [],
            "passed_checks": [],
            "pending_checks": [],
            "duration_seconds": duration,
            "error": "GitHub has not reported target test check contexts for this branch.",
        }
    normalized = normalize_github_pr_checks(target_checks, duration_seconds=duration)
    if normalized["state"] == "checks_failed":
        normalized["failing_checks"] = failed_checks_with_log_excerpts(
            git_root,
            gh_path=gh_path,
            failing_checks=normalized["failing_checks"],  # type: ignore[arg-type]
        )
    return normalized


def _pending_expected_head_result(
    *,
    duration_seconds: float,
    expected_head_sha: str,
    actual_head_sha: str,
    error: str,
    pr_url: str,
) -> dict[str, object]:
    return {
        "state": "checks_pending_timeout",
        "failing_checks": [],
        "passed_checks": [],
        "pending_checks": [
            {
                "name": "github_head_ref",
                "state": "WAITING",
                "expected_head_sha": expected_head_sha,
                "actual_head_sha": actual_head_sha,
            }
        ],
        "duration_seconds": duration_seconds,
        "expected_head_sha": expected_head_sha,
        "actual_head_sha": actual_head_sha,
        "pr_url": pr_url,
        "error": error,
    }


__all__ = [
    "MonotonicClock",
    "RunCommand",
    "query_expected_head_pr_checks",
    "query_github_pr_checks",
]
