from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Mapping

FAILING_CHECK_STATES = {"FAILURE", "FAILED", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}
PASSING_CHECK_STATES = {"SUCCESS", "PASSED", "COMPLETED", "NEUTRAL", "SKIPPED"}
TERMINAL_SHIP_CHECK_STATES = {"checks_passed", "checks_failed", "gh_unavailable", "no_checks_reported"}
DEFAULT_CHECK_TIMEOUT_SECONDS = 900.0
DEFAULT_CHECK_POLL_INTERVAL_SECONDS = 10.0


def github_pr_checks(
    git_root: Path,
    *,
    branch: str,
    pr_url: str,
    timeout_seconds: float | None = None,
    poll_interval_seconds: float | None = None,
) -> dict[str, object]:
    del pr_url
    gh_path = shutil.which("gh")
    if gh_path is None:
        return {
            "state": "gh_unavailable",
            "failing_checks": [],
            "passed_checks": [],
            "pending_checks": [],
            "duration_seconds": 0.0,
        }
    started = time.monotonic()
    timeout = timeout_seconds if timeout_seconds is not None else _float_env("ENVCTL_SHIP_CHECK_TIMEOUT_SECONDS")
    poll_interval = (
        poll_interval_seconds
        if poll_interval_seconds is not None
        else _float_env("ENVCTL_SHIP_CHECK_POLL_INTERVAL_SECONDS")
    )
    timeout = DEFAULT_CHECK_TIMEOUT_SECONDS if timeout is None else max(timeout, 0.0)
    poll_interval = DEFAULT_CHECK_POLL_INTERVAL_SECONDS if poll_interval is None else max(poll_interval, 0.1)

    while True:
        result = _query_github_pr_checks(git_root, gh_path=gh_path, branch=branch, started=started)
        if result["state"] in TERMINAL_SHIP_CHECK_STATES:
            return result
        elapsed = time.monotonic() - started
        if elapsed >= timeout:
            return {
                **result,
                "state": "checks_pending_timeout",
                "duration_seconds": round(elapsed, 3),
                "timeout_seconds": timeout,
            }
        time.sleep(min(poll_interval, max(timeout - elapsed, 0.1)))


def _query_github_pr_checks(
    git_root: Path,
    *,
    gh_path: str,
    branch: str,
    started: float,
) -> dict[str, object]:
    completed = subprocess.run(
        [gh_path, "pr", "checks", branch, "--json", "name,state,workflow,link"],
        cwd=str(git_root),
        text=True,
        capture_output=True,
        check=False,
    )
    duration = round(time.monotonic() - started, 3)
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
    return normalize_github_pr_checks(checks, duration_seconds=duration)


def _float_env(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def normalize_github_pr_checks(
    checks: list[Mapping[str, object]],
    *,
    duration_seconds: float,
) -> dict[str, object]:
    failing = [check for check in checks if str(check.get("state", "")).upper() in FAILING_CHECK_STATES]
    passed = [check for check in checks if str(check.get("state", "")).upper() in PASSING_CHECK_STATES]
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
        "passed_checks": passed,
        "pending_checks": pending,
        "duration_seconds": duration_seconds,
    }


__all__ = [
    "DEFAULT_CHECK_POLL_INTERVAL_SECONDS",
    "DEFAULT_CHECK_TIMEOUT_SECONDS",
    "FAILING_CHECK_STATES",
    "PASSING_CHECK_STATES",
    "TERMINAL_SHIP_CHECK_STATES",
    "github_pr_checks",
    "normalize_github_pr_checks",
]
