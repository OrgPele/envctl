from __future__ import annotations

from typing import Mapping, Sequence

FAILING_CHECK_STATES = {"FAILURE", "FAILED", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}
PASSING_CHECK_STATES = {"SUCCESS", "PASSED", "NEUTRAL", "SKIPPED"}
DEFAULT_CHECK_NAME_PREFIX = "tests"


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


def normalize_status_rollup_check(check: Mapping[str, object]) -> dict[str, object]:
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


def target_status_checks(checks: Sequence[object]) -> list[Mapping[str, object]]:
    return [
        check
        for check in checks
        if isinstance(check, Mapping) and _status_check_matches_default_target(check)
    ]


def status_check_display_name(check: Mapping[str, object]) -> str:
    workflow = str(check.get("workflow") or check.get("workflowName") or "").strip()
    name = str(check.get("name") or check.get("context") or "").strip()
    if workflow and name:
        return f"{workflow} / {name}"
    return workflow or name


def _normalized_check_state(check: Mapping[str, object]) -> str:
    return str(check.get("state", "")).strip().upper()


def _status_check_matches_default_target(check: Mapping[str, object]) -> bool:
    return status_check_display_name(check).casefold().startswith(DEFAULT_CHECK_NAME_PREFIX)


__all__ = [
    "DEFAULT_CHECK_NAME_PREFIX",
    "FAILING_CHECK_STATES",
    "PASSING_CHECK_STATES",
    "normalize_github_pr_checks",
    "normalize_status_rollup_check",
    "status_check_display_name",
    "target_status_checks",
]
