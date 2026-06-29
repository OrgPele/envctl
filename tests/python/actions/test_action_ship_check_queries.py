from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, cast

from envctl_engine.actions import action_ship_check_queries


def test_github_pr_check_query_ignores_malformed_failing_check_payloads(tmp_path: Path, monkeypatch: Any) -> None:
    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(
                [
                    {"name": "pytest", "workflow": "Tests", "state": "FAILURE"},
                ]
            ),
            stderr="",
        )

    def fake_normalize(_checks: object, *, duration_seconds: float) -> dict[str, object]:
        return {
            "state": "checks_failed",
            "duration_seconds": duration_seconds,
            "failing_checks": [
                "unexpected-check-item",
                {"name": "pytest", "workflow": "Tests", "state": "FAILURE"},
            ],
            "passed_checks": [],
            "pending_checks": [],
        }

    monkeypatch.setattr(action_ship_check_queries, "normalize_github_pr_checks", fake_normalize)

    checks = action_ship_check_queries.query_github_pr_checks(
        tmp_path,
        gh_path="/usr/bin/gh",
        branch="feature/demo",
        started=0.0,
        run_command=fake_run,
        monotonic=lambda: 0.25,
    )

    assert checks["state"] == "checks_failed"
    assert checks["failing_checks"] == [{"name": "pytest", "workflow": "Tests", "state": "FAILURE"}]

def test_github_pr_check_query_reports_runner_timeouts_as_pending_status(tmp_path: Path) -> None:
    seen_timeout: list[float] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        timeout = cast(float, kwargs["timeout"])
        seen_timeout.append(timeout)
        raise subprocess.TimeoutExpired(args, timeout=timeout)

    checks = action_ship_check_queries.query_github_pr_checks(
        tmp_path,
        gh_path="gh-test",
        branch="feature/demo",
        started=0.0,
        run_command=fake_run,
        monotonic=lambda: 0.5,
    )

    assert checks == {
        "state": "checks_pending_timeout",
        "failing_checks": [],
        "passed_checks": [],
        "pending_checks": [],
        "duration_seconds": 0.5,
        "error": "Command '['gh-test', 'pr', 'checks', 'feature/demo', '--json', 'name,state,workflow,link']' "
        "timed out after 30.0 seconds",
    }
    assert seen_timeout == [30.0]

def test_expected_head_check_query_reports_runner_timeouts_as_pending_status(tmp_path: Path) -> None:
    seen_timeout: list[float] = []

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        timeout = cast(float, kwargs["timeout"])
        seen_timeout.append(timeout)
        raise subprocess.TimeoutExpired(args, timeout=timeout)

    checks = action_ship_check_queries.query_expected_head_pr_checks(
        tmp_path,
        gh_path="gh-test",
        branch="feature/demo",
        pr_url="https://github.com/acme/repo/pull/7",
        expected_head_sha="newsha",
        started=0.0,
        no_checks_grace_seconds=10.0,
        run_command=fake_run,
        monotonic=lambda: 0.5,
    )

    assert checks["state"] == "checks_pending_timeout"
    assert checks["duration_seconds"] == 0.5
    assert checks["expected_head_sha"] == "newsha"
    assert checks["pr_url"] == "https://github.com/acme/repo/pull/7"
    assert "timed out after 30.0 seconds" in str(checks["error"])
    assert seen_timeout == [30.0]

def test_github_pr_check_query_uses_fallback_message_when_cli_error_is_empty(tmp_path: Path) -> None:
    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")

    checks = action_ship_check_queries.query_github_pr_checks(
        tmp_path,
        gh_path="gh-test",
        branch="feature/demo",
        started=0.0,
        run_command=fake_run,
        monotonic=lambda: 0.5,
    )

    assert checks == {
        "state": "checks_pending_timeout",
        "failing_checks": [],
        "passed_checks": [],
        "pending_checks": [],
        "duration_seconds": 0.5,
        "error": "GitHub PR checks are not available yet.",
    }

def test_github_pr_check_query_uses_injected_runner_for_failed_check_logs(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:3] == ["gh-test", "pr", "checks"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "name": "pytest",
                            "workflow": "Tests",
                            "state": "FAILURE",
                            "link": "https://github.com/acme/repo/actions/runs/123/job/456",
                        }
                    ]
                ),
                stderr="",
            )
        if args[:6] == ["gh-test", "run", "view", "123", "--job", "456"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=(
                    "pytest\tRun pytest\t2026-05-25T20:00:00Z ================= FAILURES =================\n"
                    "pytest\tRun pytest\t2026-05-25T20:00:01Z FAILED tests/test_demo.py::test_demo - AssertionError\n"
                ),
                stderr="",
            )
        raise AssertionError(args)

    checks = action_ship_check_queries.query_github_pr_checks(
        tmp_path,
        gh_path="gh-test",
        branch="feature/demo",
        started=0.0,
        run_command=fake_run,
        monotonic=lambda: 0.5,
    )

    assert checks["state"] == "checks_failed"
    assert checks["failing_checks"] == [
        {
            "name": "pytest",
            "workflow": "Tests",
            "state": "FAILURE",
            "link": "https://github.com/acme/repo/actions/runs/123/job/456",
            "failure_excerpt": "================= FAILURES =================\n"
            "FAILED tests/test_demo.py::test_demo - AssertionError",
            "failure_excerpt_truncated": False,
        }
    ]
    assert calls == [
        ["gh-test", "pr", "checks", "feature/demo", "--json", "name,state,workflow,link"],
        ["gh-test", "run", "view", "123", "--job", "456", "--log"],
    ]

def test_github_pr_check_query_preserves_available_non_target_checks(tmp_path: Path) -> None:
    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(
                [
                    {"name": "lint", "workflow": "Ruff", "state": "SUCCESS", "link": "https://ci.test/lint"},
                    {"name": "deploy", "workflow": "Preview", "state": "SKIPPED"},
                ]
            ),
            stderr="",
        )

    checks = action_ship_check_queries.query_github_pr_checks(
        tmp_path,
        gh_path="gh-test",
        branch="feature/demo",
        started=0.0,
        run_command=fake_run,
        monotonic=lambda: 0.5,
    )

    assert checks["state"] == "no_checks_reported"
    assert checks["passed_checks"] == []
    assert checks["pr_checks"] == [
        {"name": "lint", "workflow": "Ruff", "state": "SUCCESS", "link": "https://ci.test/lint"},
        {"name": "deploy", "workflow": "Preview", "state": "SKIPPED"},
    ]

def test_expected_head_check_query_returns_full_pr_check_rollup_and_deployment_url(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:3] == ["gh-test", "pr", "view"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(
                    {
                        "headRefOid": "newsha",
                        "url": "https://github.com/acme/repo/pull/7",
                        "statusCheckRollup": [
                            {
                                "name": "pytest",
                                "workflowName": "Tests",
                                "status": "COMPLETED",
                                "conclusion": "SUCCESS",
                                "detailsUrl": "https://ci.test/pytest",
                            },
                            {
                                "name": "preview",
                                "workflowName": "Deploy",
                                "status": "COMPLETED",
                                "conclusion": "NEUTRAL",
                                "detailsUrl": "https://ci.test/deploy",
                            },
                        ],
                    }
                ),
                stderr="",
            )
        if args[:3] == ["gh-test", "api", "repos/acme/repo/deployments?ref=feature%2Fdemo&per_page=5"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps([{"id": 99}]), stderr="")
        if args[:3] == ["gh-test", "api", "repos/acme/repo/deployments/99/statuses?per_page=5"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps([{"environment_url": "https://preview.test/pr-7"}]),
                stderr="",
            )
        raise AssertionError(args)

    checks = action_ship_check_queries.query_expected_head_pr_checks(
        tmp_path,
        gh_path="gh-test",
        branch="feature/demo",
        pr_url="https://github.com/acme/repo/pull/7",
        expected_head_sha="newsha",
        started=0.0,
        no_checks_grace_seconds=10.0,
        run_command=fake_run,
        monotonic=lambda: 0.5,
    )

    assert checks["state"] == "checks_passed"
    assert checks["passed_checks"] == [{"name": "pytest", "workflow": "Tests", "state": "SUCCESS", "link": "https://ci.test/pytest"}]
    assert checks["pr_checks"] == [
        {"name": "pytest", "workflow": "Tests", "state": "SUCCESS", "link": "https://ci.test/pytest"},
        {"name": "preview", "workflow": "Deploy", "state": "NEUTRAL", "link": "https://ci.test/deploy"},
    ]
    assert checks["deployment_url"] == "https://preview.test/pr-7"
