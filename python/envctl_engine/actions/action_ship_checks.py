from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import time
from typing import Callable, Mapping

from envctl_engine.actions.action_ship_check_queries import (
    RunCommand,
    query_expected_head_pr_checks as _query_expected_head_pr_checks,
    query_github_pr_checks as _query_github_pr_checks,
)
from envctl_engine.actions.action_ship_check_results import (
    DEFAULT_CHECK_NAME_PREFIX,
    FAILING_CHECK_STATES,
    PASSING_CHECK_STATES,
    normalize_github_pr_checks,
)
from envctl_engine.actions.action_ship_failure_logs import (
    DEFAULT_FAILURE_EXCERPT_CHARS,
    DEFAULT_FAILURE_EXCERPT_LINES,
    failed_check_logs_are_retryable as _failed_check_logs_are_retryable,
    failed_checks_with_log_excerpts,
    failure_log_excerpt,
)

TERMINAL_SHIP_CHECK_STATES = {"checks_passed", "checks_failed", "gh_unavailable", "no_checks_reported"}
SHIP_NO_CHECKS_GRACE_ENV = "ENVCTL_SHIP_NO_CHECKS_GRACE_SECONDS"
DEFAULT_CHECK_TIMEOUT_SECONDS = 120.0
DEFAULT_CHECK_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_CHECK_PROGRESS_INTERVAL_SECONDS = 10.0
DEFAULT_NO_CHECKS_GRACE_SECONDS = 15.0
Clock = Callable[[], float]
Sleeper = Callable[[float], None]
GhPathResolver = Callable[[], str | None]


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
                env_name=SHIP_NO_CHECKS_GRACE_ENV,
                default=DEFAULT_NO_CHECKS_GRACE_SECONDS,
                minimum=0.0,
            ),
        )


@dataclass(frozen=True, slots=True)
class ShipCheckPoller:
    git_root: Path
    gh_path: str
    branch: str
    pr_url: str
    expected_head_sha: str | None
    timing: ShipCheckTiming
    started: float
    run_command: RunCommand
    monotonic: Clock
    sleep: Sleeper
    progress_callback: Callable[[str], None] | None = None

    def run(self) -> dict[str, object]:
        next_progress_at = self.timing.progress_interval_seconds
        while True:
            result = self._query()
            if _ship_check_result_is_terminal(result):
                return result

            elapsed = self.monotonic() - self.started
            next_progress_at = self._emit_progress_if_needed(
                result,
                elapsed_seconds=elapsed,
                next_progress_at=next_progress_at,
            )
            if elapsed >= self.timing.timeout_seconds:
                return self._timeout_result(result, elapsed_seconds=elapsed)
            self._sleep_until_next_poll(elapsed_seconds=elapsed)

    def _query(self) -> dict[str, object]:
        if self.expected_head_sha:
            return _query_expected_head_pr_checks(
                self.git_root,
                gh_path=self.gh_path,
                branch=self.branch,
                pr_url=self.pr_url,
                expected_head_sha=self.expected_head_sha,
                started=self.started,
                no_checks_grace_seconds=self.timing.no_checks_grace_seconds,
                run_command=self.run_command,
                monotonic=self.monotonic,
            )
        return _query_github_pr_checks(
            self.git_root,
            gh_path=self.gh_path,
            branch=self.branch,
            started=self.started,
            run_command=self.run_command,
            monotonic=self.monotonic,
        )

    def _emit_progress_if_needed(
        self,
        result: Mapping[str, object],
        *,
        elapsed_seconds: float,
        next_progress_at: float,
    ) -> float:
        if self.progress_callback is None or elapsed_seconds < next_progress_at:
            return next_progress_at

        self.progress_callback(
            _check_progress_message(
                result,
                elapsed_seconds=elapsed_seconds,
                timeout_seconds=self.timing.timeout_seconds,
            )
        )
        while next_progress_at <= elapsed_seconds:
            next_progress_at += self.timing.progress_interval_seconds
        return next_progress_at

    def _timeout_result(self, result: Mapping[str, object], *, elapsed_seconds: float) -> dict[str, object]:
        if result.get("state") == "checks_failed":
            return {
                **result,
                "duration_seconds": round(elapsed_seconds, 3),
                "timeout_seconds": self.timing.timeout_seconds,
                "failure_log_timeout": _failed_check_logs_are_retryable(result),
            }
        return {
            **result,
            "state": "checks_pending_timeout",
            "duration_seconds": round(elapsed_seconds, 3),
            "timeout_seconds": self.timing.timeout_seconds,
        }

    def _sleep_until_next_poll(self, *, elapsed_seconds: float) -> None:
        remaining_seconds = self.timing.timeout_seconds - elapsed_seconds
        if remaining_seconds <= 0:
            return
        self.sleep(min(self.timing.poll_interval_seconds, remaining_seconds))


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
    run_command: RunCommand | None = None,
    monotonic: Clock | None = None,
    sleep: Sleeper | None = None,
    gh_path_resolver: GhPathResolver | None = None,
) -> dict[str, object]:
    resolved_gh_path = (gh_path_resolver if gh_path_resolver is not None else _default_gh_path)()
    if resolved_gh_path is None:
        return {
            "state": "gh_unavailable",
            "failing_checks": [],
            "passed_checks": [],
            "pending_checks": [],
            "duration_seconds": 0.0,
        }
    resolved_monotonic = monotonic if monotonic is not None else time.monotonic
    started = resolved_monotonic()
    timing = ShipCheckTiming.from_inputs(
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        progress_interval_seconds=progress_interval_seconds,
        no_checks_grace_seconds=no_checks_grace_seconds,
    )
    return ShipCheckPoller(
        git_root=git_root,
        gh_path=resolved_gh_path,
        branch=branch,
        pr_url=pr_url,
        expected_head_sha=expected_head_sha,
        timing=timing,
        started=started,
        run_command=run_command if run_command is not None else subprocess.run,
        monotonic=resolved_monotonic,
        sleep=sleep if sleep is not None else time.sleep,
        progress_callback=progress_callback,
    ).run()


def _default_gh_path() -> str | None:
    return shutil.which("gh")


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
    "Clock",
    "DEFAULT_CHECK_NAME_PREFIX",
    "DEFAULT_CHECK_POLL_INTERVAL_SECONDS",
    "DEFAULT_CHECK_PROGRESS_INTERVAL_SECONDS",
    "DEFAULT_CHECK_TIMEOUT_SECONDS",
    "DEFAULT_FAILURE_EXCERPT_CHARS",
    "DEFAULT_FAILURE_EXCERPT_LINES",
    "DEFAULT_NO_CHECKS_GRACE_SECONDS",
    "FAILING_CHECK_STATES",
    "GhPathResolver",
    "PASSING_CHECK_STATES",
    "RunCommand",
    "ShipCheckPoller",
    "ShipCheckTiming",
    "SHIP_NO_CHECKS_GRACE_ENV",
    "Sleeper",
    "TERMINAL_SHIP_CHECK_STATES",
    "failed_checks_with_log_excerpts",
    "failure_log_excerpt",
    "github_pr_checks",
    "normalize_github_pr_checks",
]
