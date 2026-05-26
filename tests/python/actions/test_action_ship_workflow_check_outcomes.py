from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from tests.python.actions.ship_workflow_test_support import ShipWorkflowResult, ship_workflow_fixture


def _run_existing_pr_with_check_result(check_result: dict[str, object]) -> ShipWorkflowResult:
    with ship_workflow_fixture() as fixture:
        return fixture.run(
            github_pr_checks=lambda _git_root, *, branch, pr_url, expected_head_sha: check_result
        )


def test_run_ship_workflow_prints_check_progress_to_stderr() -> None:
    with ship_workflow_fixture() as fixture:

        def github_pr_checks(
            _git_root: Path,
            *,
            branch: str,
            pr_url: str,
            expected_head_sha: str,
            progress_callback: Callable[[str], None],
        ) -> dict[str, object]:
            assert branch == "feature/demo"
            assert pr_url == "https://github.com/acme/repo/pull/7"
            assert expected_head_sha == "abc123"
            progress_callback("ship: GitHub checks still running after 10s")
            return {
                "state": "checks_passed",
                "passed_checks": [{"name": "pytest", "state": "SUCCESS"}],
                "failing_checks": [],
                "pending_checks": [],
                "duration_seconds": 10.0,
            }

        result = fixture.run(github_pr_checks=github_pr_checks)

    assert result.code == 0
    assert result.stderr.splitlines() == [
        "ship: PR already exists for Main: https://github.com/acme/repo/pull/7",
        "ship: GitHub checks still running after 10s",
    ]
    assert result.payload["status"] == "checks_passed"


def test_run_ship_workflow_fails_closed_for_unknown_check_state() -> None:
    result = _run_existing_pr_with_check_result(
        {
            "state": "unexpected_check_state",
            "failing_checks": [],
            "passed_checks": [],
            "pending_checks": [],
            "duration_seconds": 0.1,
        }
    )

    assert result.code == 1
    assert result.payload["status"] == "unexpected_check_state"
    assert result.payload["step_statuses"] == [
        "clean_no_changes",
        "pr_exists",
        "unexpected_check_state",
    ]
    assert result.payload["operation_statuses"]["checks"] == "unexpected_check_state"


def test_run_ship_workflow_fails_closed_when_check_payload_has_no_state() -> None:
    result = _run_existing_pr_with_check_result({})

    assert result.code == 1
    assert result.payload["status"] == "checks_unresolved"
    assert result.payload["step_statuses"] == ["clean_no_changes", "pr_exists", "checks_unresolved"]
    assert result.payload["operation_statuses"]["checks"] == "checks_unresolved"


def test_run_ship_workflow_returns_failure_with_pending_status_when_checks_timeout() -> None:
    result = _run_existing_pr_with_check_result(
        {
            "state": "checks_pending_timeout",
            "failing_checks": [],
            "passed_checks": [{"name": "ruff", "state": "SUCCESS"}],
            "pending_checks": [{"name": "pytest", "state": "QUEUED"}],
            "duration_seconds": 30.0,
            "timeout_seconds": 30.0,
        }
    )

    assert result.code == 1
    assert result.payload["status"] == "checks_pending_timeout"
    assert result.payload["operation_statuses"]["checks"] == "checks_pending_timeout"
    assert result.payload["checks_timeout_seconds"] == 30.0
    assert result.payload["pending_checks"] == [{"name": "pytest", "state": "QUEUED"}]


def test_run_ship_workflow_returns_failure_when_no_checks_are_reported() -> None:
    result = _run_existing_pr_with_check_result(
        {
            "state": "no_checks_reported",
            "failing_checks": [],
            "passed_checks": [],
            "pending_checks": [],
            "duration_seconds": 0.1,
        }
    )

    assert result.code == 1
    assert result.payload["status"] == "no_checks_reported"
    assert result.payload["operation_statuses"]["checks"] == "no_checks_reported"


def test_run_ship_workflow_returns_failure_when_github_cli_is_unavailable_for_checks() -> None:
    result = _run_existing_pr_with_check_result(
        {
            "state": "gh_unavailable",
            "failing_checks": [],
            "passed_checks": [],
            "pending_checks": [],
            "duration_seconds": 0.0,
        }
    )

    assert result.code == 1
    assert result.payload["status"] == "gh_unavailable"
    assert result.payload["operation_statuses"]["checks"] == "gh_unavailable"
