from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Callable, Mapping, Sequence

from envctl_engine.actions.action_ship_failure_logs import (
    DEFAULT_FAILURE_EXCERPT_CHARS,
    DEFAULT_FAILURE_EXCERPT_LINES,
    failed_check_logs_are_retryable as _failed_check_logs_are_retryable,
    failed_checks_with_log_excerpts,
    failure_log_excerpt,
)

FAILING_CHECK_STATES = {"FAILURE", "FAILED", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}
PASSING_CHECK_STATES = {"SUCCESS", "PASSED", "NEUTRAL", "SKIPPED"}
TERMINAL_SHIP_CHECK_STATES = {"checks_passed", "checks_failed", "gh_unavailable", "no_checks_reported"}
DEFAULT_CHECK_TIMEOUT_SECONDS = 120.0
DEFAULT_CHECK_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_CHECK_PROGRESS_INTERVAL_SECONDS = 10.0
DEFAULT_NO_CHECKS_GRACE_SECONDS = 10.0
DEFAULT_CHECK_NAME_PREFIX = "tests"


def github_pr_checks(
    git_root: Path,
    *,
    branch: str,
    pr_url: str,
    expected_head_sha: str | None = None,
    timeout_seconds: float | None = None,
    poll_interval_seconds: float | None = None,
    progress_interval_seconds: float | None = None,
    no_checks_grace_seconds: float | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> dict[str, object]:
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
    progress_interval = (
        progress_interval_seconds
        if progress_interval_seconds is not None
        else _float_env("ENVCTL_SHIP_CHECK_PROGRESS_INTERVAL_SECONDS")
    )
    timeout = DEFAULT_CHECK_TIMEOUT_SECONDS if timeout is None else max(timeout, 0.0)
    poll_interval = DEFAULT_CHECK_POLL_INTERVAL_SECONDS if poll_interval is None else max(poll_interval, 0.1)
    progress_interval = (
        DEFAULT_CHECK_PROGRESS_INTERVAL_SECONDS if progress_interval is None else max(progress_interval, 0.1)
    )
    no_checks_grace = (
        no_checks_grace_seconds
        if no_checks_grace_seconds is not None
        else _float_env("ENVCTL_SHIP_NO_CHECKS_GRACE_SECONDS")
    )
    no_checks_grace = DEFAULT_NO_CHECKS_GRACE_SECONDS if no_checks_grace is None else max(no_checks_grace, 0.0)
    next_progress_at = progress_interval

    while True:
        result = (
            _query_expected_head_pr_checks(
                git_root,
                gh_path=gh_path,
                branch=branch,
                pr_url=pr_url,
                expected_head_sha=expected_head_sha,
                started=started,
                no_checks_grace_seconds=no_checks_grace,
            )
            if expected_head_sha
            else _query_github_pr_checks(git_root, gh_path=gh_path, branch=branch, started=started)
        )
        if _ship_check_result_is_terminal(result):
            return result
        elapsed = time.monotonic() - started
        if progress_callback is not None and elapsed >= next_progress_at:
            progress_callback(_check_progress_message(result, elapsed_seconds=elapsed, timeout_seconds=timeout))
            while next_progress_at <= elapsed:
                next_progress_at += progress_interval
        if elapsed >= timeout:
            if result.get("state") == "checks_failed":
                return {
                    **result,
                    "duration_seconds": round(elapsed, 3),
                    "timeout_seconds": timeout,
                    "failure_log_timeout": _failed_check_logs_are_retryable(result),
                }
            return {
                **result,
                "state": "checks_pending_timeout",
                "duration_seconds": round(elapsed, 3),
                "timeout_seconds": timeout,
            }
        time.sleep(min(poll_interval, max(timeout - elapsed, 0.1)))


def _ship_check_result_is_terminal(result: Mapping[str, object]) -> bool:
    state = str(result.get("state") or "")
    if state != "checks_failed":
        return state in TERMINAL_SHIP_CHECK_STATES
    return not _failed_check_logs_are_retryable(result)


def _check_progress_message(
    result: Mapping[str, object],
    *,
    elapsed_seconds: float,
    timeout_seconds: float,
) -> str:
    pending = _check_count(result.get("pending_checks"))
    passed = _check_count(result.get("passed_checks"))
    failed = _check_count(result.get("failing_checks"))
    return (
        f"ship: GitHub checks still running after {_format_seconds(elapsed_seconds)} "
        f"(pending={pending}, passed={passed}, failed={failed}, timeout={_format_seconds(timeout_seconds)})"
    )


def _check_count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _format_seconds(value: float) -> str:
    rounded = round(value)
    if abs(value - rounded) < 0.001:
        return f"{rounded}s"
    return f"{value:.1f}s"


def _query_expected_head_pr_checks(
    git_root: Path,
    *,
    gh_path: str,
    branch: str,
    pr_url: str,
    expected_head_sha: str,
    started: float,
    no_checks_grace_seconds: float,
) -> dict[str, object]:
    completed = subprocess.run(
        [gh_path, "pr", "view", branch, "--json", "headRefOid,statusCheckRollup,url"],
        cwd=str(git_root),
        text=True,
        capture_output=True,
        check=False,
    )
    duration = round(time.monotonic() - started, 3)
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
        [_normalize_status_rollup_check(item) for item in rollup if isinstance(item, Mapping)]
        if isinstance(rollup, list)
        else []
    )
    target_checks = _target_status_checks(checks)
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


def _normalize_status_rollup_check(check: Mapping[str, object]) -> dict[str, object]:
    name = str(check.get("name") or check.get("context") or "check").strip()
    status = str(check.get("status") or check.get("state") or "").strip().upper()
    conclusion = str(check.get("conclusion") or "").strip().upper()
    state = conclusion if status == "COMPLETED" and conclusion else status
    link = str(check.get("detailsUrl") or check.get("targetUrl") or check.get("link") or "").strip()
    workflow = str(check.get("workflowName") or check.get("workflow") or "").strip()
    normalized: dict[str, object] = {"name": name, "state": state}
    if workflow:
        normalized["workflow"] = workflow
    if link:
        normalized["link"] = link
    return normalized


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
    target_checks = _target_status_checks(checks)
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


def _float_env(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def normalize_github_pr_checks(
    checks: Sequence[Mapping[str, object]],
    *,
    duration_seconds: float,
) -> dict[str, object]:
    failing: list[Mapping[str, object]] = []
    passed: list[Mapping[str, object]] = []
    pending: list[Mapping[str, object]] = []
    for check in checks:
        state = _normalized_check_state(check)
        if state in FAILING_CHECK_STATES:
            failing.append(check)
        elif state in PASSING_CHECK_STATES:
            passed.append(check)
        else:
            pending.append(check)
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


def _normalized_check_state(check: Mapping[str, object]) -> str:
    return str(check.get("state", "")).strip().upper()


def _target_status_checks(checks: Sequence[object]) -> list[Mapping[str, object]]:
    return [
        check
        for check in checks
        if isinstance(check, Mapping) and _status_check_matches_default_target(check)
    ]


def _status_check_matches_default_target(check: Mapping[str, object]) -> bool:
    return _status_check_display_name(check).casefold().startswith(DEFAULT_CHECK_NAME_PREFIX)


def _status_check_display_name(check: Mapping[str, object]) -> str:
    workflow = str(check.get("workflow") or check.get("workflowName") or "").strip()
    name = str(check.get("name") or check.get("context") or "").strip()
    if workflow and name:
        return f"{workflow} / {name}"
    return workflow or name


__all__ = [
    "DEFAULT_CHECK_NAME_PREFIX",
    "DEFAULT_CHECK_POLL_INTERVAL_SECONDS",
    "DEFAULT_CHECK_PROGRESS_INTERVAL_SECONDS",
    "DEFAULT_CHECK_TIMEOUT_SECONDS",
    "DEFAULT_FAILURE_EXCERPT_CHARS",
    "DEFAULT_FAILURE_EXCERPT_LINES",
    "DEFAULT_NO_CHECKS_GRACE_SECONDS",
    "FAILING_CHECK_STATES",
    "PASSING_CHECK_STATES",
    "TERMINAL_SHIP_CHECK_STATES",
    "failed_checks_with_log_excerpts",
    "failure_log_excerpt",
    "github_pr_checks",
    "normalize_github_pr_checks",
]
