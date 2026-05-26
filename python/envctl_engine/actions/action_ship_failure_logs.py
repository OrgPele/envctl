from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Callable, Mapping

DEFAULT_FAILURE_EXCERPT_LINES = 80
DEFAULT_FAILURE_EXCERPT_CHARS = 12_000
DEFAULT_FAILURE_LOG_COMMAND_TIMEOUT_SECONDS = 30.0
RunCommand = Callable[..., subprocess.CompletedProcess[str]]
_ACTION_JOB_URL_RE = re.compile(r"/actions/runs/(?P<run_id>\d+)/job/(?P<job_id>\d+)")
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_LOG_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s+")
_CHECKOUT_CONTEXT_FRAGMENTS = (
    "actions/checkout",
    "checkout repository",
    "git fetch",
    "/usr/bin/git",
)
_CHECKOUT_AUTH_FAILURE_FRAGMENTS = (
    "account is suspended",
    "authentication failed",
    "could not read username",
    "permission denied",
    "repository not found",
    "requested url returned error: 403",
    "support.github.com",
)
_CHECKOUT_FAILURE_FRAGMENTS = (
    "exit code 128",
    "fatal: repository",
    "fatal: unable to access",
)


@dataclass(frozen=True, slots=True)
class _FailureLogFetch:
    text: str = ""
    error: str = ""


def failed_check_logs_are_retryable(result: Mapping[str, object]) -> bool:
    failing_checks = result.get("failing_checks")
    if not isinstance(failing_checks, list):
        return False

    for raw_check in failing_checks:
        if not isinstance(raw_check, Mapping):
            continue
        if str(raw_check.get("failure_excerpt") or "").strip():
            continue
        link = str(raw_check.get("link") or "").strip()
        if _github_actions_run_and_job_ids(link) is None:
            continue
        error = str(raw_check.get("failure_log_error") or "").strip()
        if not error or _failure_log_error_is_retryable(error):
            return True
    return False


def failed_checks_with_log_excerpts(
    git_root: Path,
    *,
    gh_path: str,
    failing_checks: list[Mapping[str, object]],
    run_command: RunCommand = subprocess.run,
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
        fetched = _fetch_failure_log(
            git_root,
            gh_path=gh_path,
            run_id=run_id,
            job_id=job_id,
            run_command=run_command,
        )
        if fetched.error:
            item["failure_log_error"] = fetched.error
            enriched.append(item)
            continue
        excerpt, truncated = failure_log_excerpt(fetched.text)
        if excerpt:
            item["failure_excerpt"] = excerpt
            item["failure_excerpt_truncated"] = truncated
        item.update(classify_failure_log(fetched.text))
        enriched.append(item)
    return enriched


def _fetch_failure_log(
    git_root: Path,
    *,
    gh_path: str,
    run_id: str,
    job_id: str,
    run_command: RunCommand,
) -> _FailureLogFetch:
    try:
        completed = run_command(
            [gh_path, "run", "view", run_id, "--job", job_id, "--log"],
            cwd=str(git_root),
            text=True,
            capture_output=True,
            check=False,
            timeout=DEFAULT_FAILURE_LOG_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return _FailureLogFetch(error=str(error) or error.__class__.__name__)
    if completed.returncode != 0:
        error = (completed.stderr or completed.stdout).strip()
        if not error:
            error = f"GitHub Actions log command failed with exit code {completed.returncode}."
        return _FailureLogFetch(error=error)
    return _FailureLogFetch(text=completed.stdout or "")


def classify_failure_log(log_text: str) -> dict[str, object]:
    lines = [_clean_log_line(line) for line in log_text.splitlines()]
    lines = [line for line in lines if line.strip()]
    if not lines:
        return {}

    checkout_start = _checkout_failure_start(lines)
    if checkout_start is None:
        return {}

    window = _classification_window(lines, checkout_start)
    if _contains_any(window, _CHECKOUT_AUTH_FAILURE_FRAGMENTS):
        return {
            "failure_kind": "github_checkout_auth",
            "failure_stage": "checkout",
            "failure_summary": "GitHub checkout/auth failed before tests ran.",
            "tests_executed": False,
        }
    return {
        "failure_kind": "github_checkout",
        "failure_stage": "checkout",
        "failure_summary": "GitHub checkout failed before tests ran.",
        "tests_executed": False,
    }


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


def _failure_log_error_is_retryable(error: str) -> bool:
    normalized = error.casefold()
    return any(
        fragment in normalized
        for fragment in (
            "still in progress",
            "logs will be available",
            "log will be available",
            "not yet available",
        )
    )


def _github_actions_run_and_job_ids(link: str) -> tuple[str, str] | None:
    match = _ACTION_JOB_URL_RE.search(link)
    if match is None:
        return None
    return match.group("run_id"), match.group("job_id")


def _failure_excerpt_start(lines: list[str]) -> int:
    checkout_start = _checkout_failure_start(lines)
    if checkout_start is not None:
        return checkout_start
    for index, line in enumerate(lines):
        normalized = line.casefold()
        if "failures" in normalized and "=" in line:
            return index
    for index, line in enumerate(lines):
        if line.startswith("FAILED ") or "##[error]" in line:
            return index
    return max(len(lines) - DEFAULT_FAILURE_EXCERPT_LINES, 0)


def _checkout_failure_start(lines: list[str]) -> int | None:
    failure_fragments = _CHECKOUT_AUTH_FAILURE_FRAGMENTS + _CHECKOUT_FAILURE_FRAGMENTS
    for index, line in enumerate(lines):
        normalized = line.casefold()
        if not _contains_any(normalized, failure_fragments):
            continue

        window_start = max(index - 8, 0)
        window_end = min(index + 4, len(lines))
        window = "\n".join(lines[window_start:window_end]).casefold()
        if not _contains_any(window, _CHECKOUT_CONTEXT_FRAGMENTS):
            continue

        for context_index in range(window_start, index + 1):
            if _contains_any(lines[context_index].casefold(), _CHECKOUT_CONTEXT_FRAGMENTS):
                return context_index
        return max(index - 2, 0)
    return None


def _classification_window(lines: list[str], start: int) -> str:
    return "\n".join(lines[start : min(start + 24, len(lines))]).casefold()


def _contains_any(value: str, fragments: tuple[str, ...]) -> bool:
    return any(fragment in value for fragment in fragments)


def _clean_log_line(line: str) -> str:
    stripped = _ANSI_RE.sub("", line.rstrip())
    parts = stripped.split("\t", 3)
    if len(parts) == 4 and parts[2].endswith("Z") and "T" in parts[2]:
        return parts[3].strip()
    if len(parts) == 3:
        return _LOG_TIMESTAMP_RE.sub("", parts[2]).strip()
    return stripped.strip()


__all__ = [
    "DEFAULT_FAILURE_EXCERPT_CHARS",
    "DEFAULT_FAILURE_EXCERPT_LINES",
    "DEFAULT_FAILURE_LOG_COMMAND_TIMEOUT_SECONDS",
    "RunCommand",
    "classify_failure_log",
    "failed_check_logs_are_retryable",
    "failed_checks_with_log_excerpts",
    "failure_log_excerpt",
]
