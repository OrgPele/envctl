from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.python.actions.ship_owner_test_support import github_pr_checks

def test_github_pr_checks_returns_failed_check_without_waiting_for_timeout(tmp_path: Path) -> None:
    calls = 0

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(
                [{"name": "pytest", "workflow": "Tests", "state": "FAILURE", "link": "https://ci.test/1"}]
            ),
            stderr="",
        )

    checks = github_pr_checks(
        tmp_path,
        timeout_seconds=30.0,
        poll_interval_seconds=0.01,
        run_command=fake_run,
    )

    assert checks["state"] == "checks_failed"
    assert checks["failing_checks"] == [
        {"name": "pytest", "workflow": "Tests", "state": "FAILURE", "link": "https://ci.test/1"}
    ]
    assert calls == 1


def test_github_pr_checks_adds_failed_check_log_excerpt(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:3] == ["/usr/bin/gh", "pr", "checks"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "name": "pytest",
                            "state": "FAILURE",
                            "workflow": "Tests",
                            "link": "https://github.com/acme/repo/actions/runs/12345/job/67890",
                        }
                    ]
                ),
                stderr="",
            )
        if args[:6] == ["/usr/bin/gh", "run", "view", "12345", "--job", "67890"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=(
                    "pytest\tRun pytest\t2026-05-25T20:00:00Z ================= FAILURES =================\n"
                    "pytest\tRun pytest\t2026-05-25T20:00:01Z FAILED tests/test_demo.py::test_demo - AssertionError\n"
                    "pytest\tRun pytest\t2026-05-25T20:00:02Z Error: Process completed with exit code 1.\n"
                ),
                stderr="",
            )
        raise AssertionError(args)

    checks = github_pr_checks(
        tmp_path,
        timeout_seconds=30.0,
        poll_interval_seconds=0.01,
        run_command=fake_run,
    )

    assert checks["state"] == "checks_failed"
    failing = checks["failing_checks"]
    assert failing == [
        {
            "name": "pytest",
            "state": "FAILURE",
            "workflow": "Tests",
            "link": "https://github.com/acme/repo/actions/runs/12345/job/67890",
            "failure_excerpt": (
                "================= FAILURES =================\n"
                "FAILED tests/test_demo.py::test_demo - AssertionError\n"
                "Error: Process completed with exit code 1."
            ),
            "failure_excerpt_truncated": False,
        }
    ]
    assert calls == [
        ["/usr/bin/gh", "pr", "checks", "feature/demo", "--json", "name,state,workflow,link"],
        ["/usr/bin/gh", "run", "view", "12345", "--job", "67890", "--log"],
    ]


def test_github_pr_checks_classifies_checkout_auth_failure_before_tests(tmp_path: Path) -> None:
    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[:3] == ["/usr/bin/gh", "pr", "checks"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps(
                    [
                        {
                            "name": "pytest",
                            "state": "FAILURE",
                            "workflow": "Tests",
                            "link": "https://github.com/acme/repo/actions/runs/12345/job/67890",
                        }
                    ]
                ),
                stderr="",
            )
        if args[:6] == ["/usr/bin/gh", "run", "view", "12345", "--job", "67890"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=(
                    "pytest\tCheckout repository\t2026-05-25T20:00:00Z ##[group]Run actions/checkout@v6\n"
                    "pytest\tCheckout repository\t2026-05-25T20:00:01Z git fetch --no-tags origin main\n"
                    "pytest\tCheckout repository\t2026-05-25T20:00:02Z remote: Your account is suspended. Please visit https://support.github.com for more information.\n"
                    "pytest\tCheckout repository\t2026-05-25T20:00:03Z ##[error]fatal: unable to access 'https://github.com/acme/repo/': The requested URL returned error: 403\n"
                    "pytest\tCheckout repository\t2026-05-25T20:00:04Z Error: Process completed with exit code 128.\n"
                ),
                stderr="",
            )
        raise AssertionError(args)

    checks = github_pr_checks(
        tmp_path,
        timeout_seconds=30.0,
        poll_interval_seconds=0.01,
        run_command=fake_run,
    )

    assert checks["state"] == "checks_failed"
    failing = checks["failing_checks"]
    assert failing == [
        {
            "name": "pytest",
            "state": "FAILURE",
            "workflow": "Tests",
            "link": "https://github.com/acme/repo/actions/runs/12345/job/67890",
            "failure_excerpt": (
                "##[group]Run actions/checkout@v6\n"
                "git fetch --no-tags origin main\n"
                "remote: Your account is suspended. Please visit https://support.github.com for more information.\n"
                "##[error]fatal: unable to access 'https://github.com/acme/repo/': The requested URL returned error: 403\n"
                "Error: Process completed with exit code 128."
            ),
            "failure_excerpt_truncated": False,
            "failure_kind": "github_checkout_auth",
            "failure_stage": "checkout",
            "failure_summary": "GitHub checkout/auth failed before tests ran.",
            "tests_executed": False,
        }
    ]


def test_github_pr_checks_retries_failed_check_logs_until_github_makes_them_available(tmp_path: Path) -> None:
    clock = {"now": 0.0}
    calls: list[list[str]] = []
    rollups = [
        {
            "headRefOid": "newsha",
            "url": "https://github.com/acme/repo/pull/7",
            "statusCheckRollup": [
                {
                    "name": "pytest",
                    "workflowName": "Tests",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                    "detailsUrl": "https://github.com/acme/repo/actions/runs/12345/job/67890",
                },
                {
                    "name": "build & shipability",
                    "workflowName": "Tests",
                    "status": "IN_PROGRESS",
                    "conclusion": "",
                    "detailsUrl": "https://github.com/acme/repo/actions/runs/12345/job/67891",
                },
            ],
        },
        {
            "headRefOid": "newsha",
            "url": "https://github.com/acme/repo/pull/7",
            "statusCheckRollup": [
                {
                    "name": "pytest",
                    "workflowName": "Tests",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                    "detailsUrl": "https://github.com/acme/repo/actions/runs/12345/job/67890",
                },
                {
                    "name": "build & shipability",
                    "workflowName": "Tests",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                    "detailsUrl": "https://github.com/acme/repo/actions/runs/12345/job/67891",
                },
            ],
        },
    ]
    log_calls = 0

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal log_calls
        calls.append(args)
        if args[:4] == ["/usr/bin/gh", "pr", "view", "feature/demo"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(rollups.pop(0)), stderr="")
        if args[:6] == ["/usr/bin/gh", "run", "view", "12345", "--job", "67890"]:
            log_calls += 1
            if log_calls == 1:
                return subprocess.CompletedProcess(
                    args=args,
                    returncode=1,
                    stdout="",
                    stderr="run 12345 is still in progress; logs will be available when it is complete",
                )
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=(
                    "pytest\tRun pytest\t2026-05-25T20:00:00Z ================= FAILURES =================\n"
                    "pytest\tRun pytest\t2026-05-25T20:00:01Z FAILED tests/test_demo.py::test_demo - AssertionError\n"
                ),
                stderr="",
            )
        if args[:2] == ["/usr/bin/gh", "api"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="[]", stderr="")
        raise AssertionError(args)

    def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds

    checks = github_pr_checks(
        tmp_path,
        expected_head_sha="newsha",
        timeout_seconds=120.0,
        poll_interval_seconds=10.0,
        run_command=fake_run,
        monotonic=lambda: clock["now"],
        sleep=fake_sleep,
    )

    assert checks["state"] == "checks_failed"
    assert checks["pending_checks"] == []
    assert checks["passed_checks"] == [
        {
            "name": "build & shipability",
            "workflow": "Tests",
            "state": "SUCCESS",
            "link": "https://github.com/acme/repo/actions/runs/12345/job/67891",
        }
    ]
    assert checks["failing_checks"] == [
        {
            "name": "pytest",
            "workflow": "Tests",
            "state": "FAILURE",
            "link": "https://github.com/acme/repo/actions/runs/12345/job/67890",
            "failure_excerpt": (
                "================= FAILURES =================\nFAILED tests/test_demo.py::test_demo - AssertionError"
            ),
            "failure_excerpt_truncated": False,
        }
    ]
    assert log_calls == 2
