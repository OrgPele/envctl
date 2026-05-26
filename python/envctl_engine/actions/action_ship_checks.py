from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import time
from typing import Callable, Mapping

from envctl_engine.actions.action_ship_check_results import (
    DEFAULT_CHECK_NAME_PREFIX,
    FAILING_CHECK_STATES,
    PASSING_CHECK_STATES,
    normalize_github_pr_checks,
    normalize_status_rollup_check as _normalize_status_rollup_check,
    target_status_checks as _target_status_checks,
)
from envctl_engine.actions.action_ship_failure_logs import (
    DEFAULT_FAILURE_EXCERPT_CHARS,
    DEFAULT_FAILURE_EXCERPT_LINES,
    failed_check_logs_are_retryable as _failed_check_logs_are_retryable,
    failed_checks_with_log_excerpts,
    failure_log_excerpt,
)

TERMINAL_SHIP_CHECK_STATES = {"checks_passed", "checks_failed", "gh_unavailable", "no_checks_reported"}
DEFAULT_CHECK_TIMEOUT_SECONDS = 120.0
DEFAULT_CHECK_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_CHECK_PROGRESS_INTERVAL_SECONDS = 10.0
DEFAULT_NO_CHECKS_GRACE_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class ShipCheckTiming:
    timeout_seconds: float = DEFAULT_CHECK_TIMEOUT_SECONDS
    poll_interval_seconds: float = DEFAULT_CHECK_POLL_INTERVAL_SECONDS
    progress_interval_seconds: float = DEFAULT_CHECK_PROGRESS_INTERVAL_SECONDS
    no_checks_grace_seconds: float = DEFAULT_NO_CHECKS_GRACE_SECONDS

    @classmethod
    def from_inputs(
        cls,
        *,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        progress_interval_seconds: float | None = None,
        no_checks_grace_seconds: float | None = None,
    ) -> ShipCheckTiming:
        return cls(
            timeout_seconds=_resolved_timing_value(
                explicit=timeout_seconds,
                env_name="ENVCTL_SHIP_CHECK_TIMEOUT_SECONDS",
                default=DEFAULT_CHECK_TIMEOUT_SECONDS,
                minimum=0.0,
            ),
            poll_interval_seconds=_resolved_timing_value(
                explicit=poll_interval_seconds,
                env_name="ENVCTL_SHIP_CHECK_POLL_INTERVAL_SECONDS",
                default=DEFAULT_CHECK_POLL_INTERVAL_SECONDS,
                minimum=0.1,
            ),
            progress_interval_seconds=_resolved_timing_value(
                explicit=progress_interval_seconds,
                env_name="ENVCTL_SHIP_CHECK_PROGRESS_INTERVAL_SECONDS",
                default=DEFAULT_CHECK_PROGRESS_INTERVAL_SECONDS,
                minimum=0.1,
            ),
            no_checks_grace_seconds=_resolved_timing_value(
                explicit=no_checks_grace_seconds,
                env_name="ENVCTL_SHIP_NO_CHECKS_GRACE_SECONDS",
                default=DEFAULT_NO_CHECKS_GRACE_SECONDS,
                minimum=0.0,
            ),
        )


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
    timing = ShipCheckTiming.from_inputs(
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        progress_interval_seconds=progress_interval_seconds,
        no_checks_grace_seconds=no_checks_grace_seconds,
    )
    next_progress_at = timing.progress_interval_seconds

    while True:
        result = (
            _query_expected_head_pr_checks(
                git_root,
                gh_path=gh_path,
                branch=branch,
                pr_url=pr_url,
                expected_head_sha=expected_head_sha,
                started=started,
                no_checks_grace_seconds=timing.no_checks_grace_seconds,
            )
            if expected_head_sha
            else _query_github_pr_checks(git_root, gh_path=gh_path, branch=branch, started=started)
        )
        if _ship_check_result_is_terminal(result):
            return result
        elapsed = time.monotonic() - started
        if progress_callback is not None and elapsed >= next_progress_at:
            progress_callback(
                _check_progress_message(
                    result,
                    elapsed_seconds=elapsed,
                    timeout_seconds=timing.timeout_seconds,
                )
            )
            while next_progress_at <= elapsed:
                next_progress_at += timing.progress_interval_seconds
        if elapsed >= timing.timeout_seconds:
            if result.get("state") == "checks_failed":
                return {
                    **result,
                    "duration_seconds": round(elapsed, 3),
                    "timeout_seconds": timing.timeout_seconds,
                    "failure_log_timeout": _failed_check_logs_are_retryable(result),
                }
            return {
                **result,
                "state": "checks_pending_timeout",
                "duration_seconds": round(elapsed, 3),
                "timeout_seconds": timing.timeout_seconds,
            }
        time.sleep(min(timing.poll_interval_seconds, max(timing.timeout_seconds - elapsed, 0.1)))


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


def _resolved_timing_value(*, explicit: float | None, env_name: str, default: float, minimum: float) -> float:
    value = explicit if explicit is not None else _float_env(env_name)
    if value is None or not math.isfinite(value):
        return default
    return max(value, minimum)


def _float_env(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


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
    "ShipCheckTiming",
    "TERMINAL_SHIP_CHECK_STATES",
    "failed_checks_with_log_excerpts",
    "failure_log_excerpt",
    "github_pr_checks",
    "normalize_github_pr_checks",
]
