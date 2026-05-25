from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Mapping

FAILING_CHECK_STATES = {"FAILURE", "FAILED", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}
PASSING_CHECK_STATES = {"SUCCESS", "PASSED", "COMPLETED", "NEUTRAL", "SKIPPED"}
TERMINAL_SHIP_CHECK_STATES = {"checks_passed", "checks_failed", "gh_unavailable", "no_checks_reported"}
DEFAULT_CHECK_TIMEOUT_SECONDS = 10.0
DEFAULT_CHECK_POLL_INTERVAL_SECONDS = 10.0
DEFAULT_NO_CHECKS_GRACE_SECONDS = 30.0
DEFAULT_FAILURE_EXCERPT_LINES = 80
DEFAULT_FAILURE_EXCERPT_CHARS = 12_000
_ACTION_JOB_URL_RE = re.compile(r"/actions/runs/(?P<run_id>\d+)/job/(?P<job_id>\d+)")
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_LOG_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s+")


def github_pr_checks(
    git_root: Path,
    *,
    branch: str,
    pr_url: str,
    expected_head_sha: str | None = None,
    timeout_seconds: float | None = None,
    poll_interval_seconds: float | None = None,
    no_checks_grace_seconds: float | None = None,
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
    timeout = DEFAULT_CHECK_TIMEOUT_SECONDS if timeout is None else max(timeout, 0.0)
    poll_interval = DEFAULT_CHECK_POLL_INTERVAL_SECONDS if poll_interval is None else max(poll_interval, 0.1)
    no_checks_grace = (
        no_checks_grace_seconds
        if no_checks_grace_seconds is not None
        else _float_env("ENVCTL_SHIP_NO_CHECKS_GRACE_SECONDS")
    )
    no_checks_grace = DEFAULT_NO_CHECKS_GRACE_SECONDS if no_checks_grace is None else max(no_checks_grace, 0.0)

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
    if not checks:
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
                "error": "GitHub has not reported check contexts for the pushed head commit yet.",
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

    normalized = normalize_github_pr_checks(checks, duration_seconds=duration)
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
    normalized = normalize_github_pr_checks(checks, duration_seconds=duration)
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


def failed_checks_with_log_excerpts(
    git_root: Path,
    *,
    gh_path: str,
    failing_checks: list[Mapping[str, object]],
) -> list[dict[str, object]]:
    enriched: list[dict[str, object]] = []
    for check in failing_checks:
        item = dict(check)
        link = str(item.get("link") or "").strip()
        ids = _github_actions_run_and_job_ids(link)
        if ids is None:
            enriched.append(item)
            continue
        run_id, job_id = ids
        completed = subprocess.run(
            [gh_path, "run", "view", run_id, "--job", job_id, "--log"],
            cwd=str(git_root),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            error = (completed.stderr or completed.stdout).strip()
            if error:
                item["failure_log_error"] = error
            enriched.append(item)
            continue
        excerpt, truncated = failure_log_excerpt(completed.stdout or "")
        if excerpt:
            item["failure_excerpt"] = excerpt
            item["failure_excerpt_truncated"] = truncated
        enriched.append(item)
    return enriched


def _github_actions_run_and_job_ids(link: str) -> tuple[str, str] | None:
    match = _ACTION_JOB_URL_RE.search(link)
    if match is None:
        return None
    return match.group("run_id"), match.group("job_id")


def failure_log_excerpt(log_text: str) -> tuple[str, bool]:
    lines = [_clean_log_line(line) for line in log_text.splitlines()]
    lines = [line for line in lines if line.strip()]
    if not lines:
        return "", False

    start = _failure_excerpt_start(lines)
    selected = lines[start : start + DEFAULT_FAILURE_EXCERPT_LINES]
    truncated = start > 0 or start + len(selected) < len(lines)
    excerpt = "\n".join(selected)
    if len(excerpt) > DEFAULT_FAILURE_EXCERPT_CHARS:
        excerpt = excerpt[:DEFAULT_FAILURE_EXCERPT_CHARS].rstrip()
        truncated = True
    return excerpt, truncated


def _failure_excerpt_start(lines: list[str]) -> int:
    for index, line in enumerate(lines):
        normalized = line.casefold()
        if "failures" in normalized and "=" in line:
            return index
    for index, line in enumerate(lines):
        if line.startswith("FAILED ") or "##[error]" in line:
            return index
    return max(len(lines) - DEFAULT_FAILURE_EXCERPT_LINES, 0)


def _clean_log_line(line: str) -> str:
    stripped = _ANSI_RE.sub("", line.rstrip())
    parts = stripped.split("\t", 3)
    if len(parts) == 4 and parts[2].endswith("Z") and "T" in parts[2]:
        return parts[3].strip()
    if len(parts) == 3:
        return _LOG_TIMESTAMP_RE.sub("", parts[2]).strip()
    return stripped.strip()


__all__ = [
    "DEFAULT_CHECK_POLL_INTERVAL_SECONDS",
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
