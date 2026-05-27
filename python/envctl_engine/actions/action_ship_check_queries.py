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

DEFAULT_GH_QUERY_TIMEOUT_SECONDS = 30.0
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
    completed, command_error = _run_gh_query(
        [gh_path, "pr", "view", branch, "--json", "headRefOid,statusCheckRollup,url"],
        git_root=git_root,
        run_command=run_command,
    )
    duration = round(monotonic() - started, 3)
    if command_error:
        return _pending_expected_head_result(
            duration_seconds=duration,
            expected_head_sha=expected_head_sha,
            actual_head_sha="",
            error=command_error,
            pr_url=pr_url,
        )
    if completed is None:
        return _pending_expected_head_result(
            duration_seconds=duration,
            expected_head_sha=expected_head_sha,
            actual_head_sha="",
            error="GitHub PR status is not available yet.",
            pr_url=pr_url,
        )
    if completed.returncode != 0:
        error = _completed_error_text(completed, fallback="GitHub PR status is not available yet.")
        return _pending_expected_head_result(
            duration_seconds=duration,
            expected_head_sha=expected_head_sha,
            actual_head_sha="",
            error=error,
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
            return _check_query_result(
                state="checks_pending_timeout",
                duration_seconds=duration,
                pending_checks=[
                    {
                        "name": "github_checks",
                        "state": "WAITING",
                        "expected_head_sha": expected_head_sha,
                    }
                ],
                error="GitHub has not reported target test check contexts for the pushed head commit yet.",
                expected_head_sha=expected_head_sha,
                pr_url=str(data.get("url") or pr_url),
            )
        return _check_query_result(
            state="no_checks_reported",
            duration_seconds=duration,
            expected_head_sha=expected_head_sha,
            pr_url=str(data.get("url") or pr_url),
        )

    normalized = normalize_github_pr_checks(target_checks, duration_seconds=duration)
    normalized["expected_head_sha"] = expected_head_sha
    normalized["actual_head_sha"] = actual_head_sha
    normalized["pr_url"] = str(data.get("url") or pr_url)
    return _with_failed_check_log_excerpts(
        normalized,
        git_root=git_root,
        gh_path=gh_path,
        run_command=run_command,
    )


def query_github_pr_checks(
    git_root: Path,
    *,
    gh_path: str,
    branch: str,
    started: float,
    run_command: RunCommand = subprocess.run,
    monotonic: MonotonicClock = time.monotonic,
) -> dict[str, object]:
    completed, command_error = _run_gh_query(
        [gh_path, "pr", "checks", branch, "--json", "name,state,workflow,link"],
        git_root=git_root,
        run_command=run_command,
    )
    duration = round(monotonic() - started, 3)
    if command_error:
        return _check_query_result(state="checks_pending_timeout", duration_seconds=duration, error=command_error)
    if completed is None:
        return _check_query_result(
            state="checks_pending_timeout",
            duration_seconds=duration,
            error="GitHub PR checks are not available yet.",
        )
    if completed.returncode != 0:
        error = _completed_error_text(completed, fallback="GitHub PR checks are not available yet.")
        if "no checks reported" in error.casefold():
            return _check_query_result(state="no_checks_reported", duration_seconds=duration, error=error)
        return _check_query_result(state="checks_pending_timeout", duration_seconds=duration, error=error)
    try:
        loaded = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        loaded = []
    checks = loaded if isinstance(loaded, list) else []
    target_checks = target_status_checks(checks)
    if not target_checks:
        return _check_query_result(
            state="no_checks_reported",
            duration_seconds=duration,
            error="GitHub has not reported target test check contexts for this branch.",
        )
    normalized = normalize_github_pr_checks(target_checks, duration_seconds=duration)
    return _with_failed_check_log_excerpts(
        normalized,
        git_root=git_root,
        gh_path=gh_path,
        run_command=run_command,
    )


def _pending_expected_head_result(
    *,
    duration_seconds: float,
    expected_head_sha: str,
    actual_head_sha: str,
    error: str,
    pr_url: str,
) -> dict[str, object]:
    return _check_query_result(
        state="checks_pending_timeout",
        duration_seconds=duration_seconds,
        pending_checks=[
            {
                "name": "github_head_ref",
                "state": "WAITING",
                "expected_head_sha": expected_head_sha,
                "actual_head_sha": actual_head_sha,
            }
        ],
        error=error,
        expected_head_sha=expected_head_sha,
        actual_head_sha=actual_head_sha,
        pr_url=pr_url,
    )


def _check_query_result(
    *,
    state: str,
    duration_seconds: float,
    failing_checks: list[object] | None = None,
    passed_checks: list[object] | None = None,
    pending_checks: list[object] | None = None,
    error: str = "",
    **extra: object,
) -> dict[str, object]:
    result: dict[str, object] = {
        "state": state,
        "failing_checks": failing_checks or [],
        "passed_checks": passed_checks or [],
        "pending_checks": pending_checks or [],
        "duration_seconds": duration_seconds,
    }
    result.update(extra)
    if error:
        result["error"] = error
    return result


def _mapping_check_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _run_gh_query(
    args: list[str],
    *,
    git_root: Path,
    run_command: RunCommand,
) -> tuple[subprocess.CompletedProcess[str] | None, str]:
    try:
        return (
            run_command(
                args,
                cwd=str(git_root),
                text=True,
                capture_output=True,
                check=False,
                timeout=DEFAULT_GH_QUERY_TIMEOUT_SECONDS,
            ),
            "",
        )
    except (OSError, subprocess.SubprocessError) as error:
        return None, str(error) or error.__class__.__name__


def _completed_error_text(completed: subprocess.CompletedProcess[str], *, fallback: str) -> str:
    return (completed.stderr or completed.stdout).strip() or fallback


def _with_failed_check_log_excerpts(
    result: dict[str, object],
    *,
    git_root: Path,
    gh_path: str,
    run_command: RunCommand,
) -> dict[str, object]:
    if result.get("state") != "checks_failed":
        return result
    result["failing_checks"] = failed_checks_with_log_excerpts(
        git_root,
        gh_path=gh_path,
        failing_checks=_mapping_check_list(result.get("failing_checks")),
        run_command=run_command,
    )
    return result


__all__ = [
    "DEFAULT_GH_QUERY_TIMEOUT_SECONDS",
    "MonotonicClock",
    "RunCommand",
    "query_expected_head_pr_checks",
    "query_github_pr_checks",
]
