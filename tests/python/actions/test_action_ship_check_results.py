from __future__ import annotations

from envctl_engine.actions.action_ship_checks import normalize_github_pr_checks as normalize_checks_from_owner
from envctl_engine.actions.action_ship_check_results import (
    normalize_github_pr_checks as normalize_checks_from_result_owner,
    target_status_checks,
)


def test_github_check_normalization_reports_failed_pending_and_passed_states() -> None:
    checks = [
        {"name": "pytest", "state": "FAILED"},
        {"name": "ruff", "state": "SUCCESS"},
        {"name": "build", "state": "QUEUED"},
    ]

    failed = normalize_checks_from_result_owner(checks, duration_seconds=1.25)
    assert failed["state"] == "checks_failed"
    assert failed["failing_checks"] == [{"name": "pytest", "state": "FAILED"}]
    assert failed["passed_checks"] == [{"name": "ruff", "state": "SUCCESS"}]
    assert failed["pending_checks"] == [{"name": "build", "state": "QUEUED"}]
    assert failed["duration_seconds"] == 1.25
    assert normalize_checks_from_owner(checks, duration_seconds=1.25) == failed

    pending = normalize_checks_from_result_owner([{"name": "pytest", "state": "PENDING"}], duration_seconds=0.5)
    assert pending["state"] == "checks_pending_timeout"

    passed = normalize_checks_from_result_owner([{"name": "ruff", "state": "SKIPPED"}], duration_seconds=0.25)
    assert passed["state"] == "checks_passed"
    assert passed["passed_checks"] == [{"name": "ruff", "state": "SKIPPED"}]

def test_ship_check_target_filter_matches_tests_workflow_case_insensitively() -> None:
    checks = [
        {"name": "pytest", "workflow": "TeStS", "state": "SUCCESS"},
        {"name": "Tests / integration", "workflow": "CI", "state": "SUCCESS"},
        {"name": "security", "workflow": "CodeQL", "state": "PENDING"},
        "malformed",
    ]

    assert target_status_checks(checks) == [
        {"name": "pytest", "workflow": "TeStS", "state": "SUCCESS"},
        {"name": "Tests / integration", "workflow": "CI", "state": "SUCCESS"},
    ]

def test_github_check_normalization_treats_completed_without_conclusion_as_pending() -> None:
    checks = normalize_checks_from_result_owner(
        [{"name": "pytest", "workflow": "Tests", "state": "COMPLETED"}],
        duration_seconds=0.25,
    )

    assert checks["state"] == "checks_pending_timeout"
    assert checks["passed_checks"] == []
    assert checks["pending_checks"] == [{"name": "pytest", "workflow": "Tests", "state": "COMPLETED"}]
