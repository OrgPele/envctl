from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import time
from typing import Mapping

FAILING_CHECK_STATES = {"FAILURE", "FAILED", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}
PASSING_CHECK_STATES = {"SUCCESS", "PASSED", "COMPLETED", "NEUTRAL", "SKIPPED"}


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


__all__ = [
    "FAILING_CHECK_STATES",
    "PASSING_CHECK_STATES",
    "github_pr_checks",
    "normalize_github_pr_checks",
]
