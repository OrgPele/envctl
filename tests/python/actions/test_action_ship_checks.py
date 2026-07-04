from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from envctl_engine.actions import action_ship_checks
from tests.python.actions.ship_owner_test_support import github_pr_checks, no_sleep


def test_github_pr_checks_polls_until_pending_checks_finish(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    outputs = [
        [{"name": "pytest", "workflow": "Tests", "state": "PENDING", "link": "https://ci.test/1"}],
        [{"name": "pytest", "workflow": "Tests", "state": "SUCCESS", "link": "https://ci.test/1"}],
    ]

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(outputs.pop(0)), stderr="")

    checks = github_pr_checks(
        tmp_path,
        timeout_seconds=5.0,
        poll_interval_seconds=0.01,
        run_command=fake_run,
        sleep=no_sleep,
    )

    assert checks["state"] == "checks_passed"
    assert checks["pending_checks"] == []
    assert len(calls) == 2

def test_github_pr_checks_does_not_sleep_past_remaining_timeout(tmp_path: Path) -> None:
    clock_values = iter([0.0, 0.9, 0.95, 1.1, 1.1])
    sleep_calls: list[float] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(
                [{"name": "pytest", "workflow": "Tests", "state": "PENDING", "link": "https://ci.test/1"}]
            ),
            stderr="",
        )

    checks = github_pr_checks(
        tmp_path,
        timeout_seconds=1.0,
        poll_interval_seconds=5.0,
        run_command=fake_run,
        monotonic=lambda: next(clock_values),
        sleep=sleep_calls.append,
    )

    assert checks["state"] == "checks_pending_timeout"
    assert len(sleep_calls) == 1
    assert abs(sleep_calls[0] - 0.05) < 0.001

def test_github_pr_checks_reports_unavailable_gh_without_running_checks(tmp_path: Path) -> None:
    def fail_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("ship check runner should not be called when gh is unavailable")

    checks = github_pr_checks(
        tmp_path,
        run_command=fail_run,
        gh_path_resolver=lambda: None,
    )

    assert checks == {
        "state": "gh_unavailable",
        "failing_checks": [],
        "passed_checks": [],
        "pending_checks": [],
        "duration_seconds": 0.0,
    }

def test_github_pr_checks_default_timeout_is_two_minute_wait_window() -> None:
    assert action_ship_checks.DEFAULT_CHECK_TIMEOUT_SECONDS == 120.0

def test_github_pr_checks_default_no_checks_grace_is_fifteen_seconds() -> None:
    assert action_ship_checks.DEFAULT_NO_CHECKS_GRACE_SECONDS == 15.0

def test_github_pr_checks_default_polling_is_more_responsive_than_progress_heartbeat() -> None:
    assert action_ship_checks.DEFAULT_CHECK_POLL_INTERVAL_SECONDS == 5.0
    assert action_ship_checks.DEFAULT_CHECK_PROGRESS_INTERVAL_SECONDS == 10.0

def test_ship_check_timing_uses_explicit_values_before_env_and_clamps_minimums(monkeypatch: Any) -> None:
    monkeypatch.setenv("ENVCTL_SHIP_CHECK_TIMEOUT_SECONDS", "90")
    monkeypatch.setenv("ENVCTL_SHIP_CHECK_POLL_INTERVAL_SECONDS", "0.01")
    monkeypatch.setenv("ENVCTL_SHIP_CHECK_PROGRESS_INTERVAL_SECONDS", "bad")
    monkeypatch.setenv("ENVCTL_SHIP_NO_CHECKS_GRACE_SECONDS", "-2")

    timing = action_ship_checks.ShipCheckTiming.from_inputs(
        timeout_seconds=12.5,
        progress_interval_seconds=2.5,
    )

    assert timing.timeout_seconds == 12.5
    assert timing.poll_interval_seconds == 0.1
    assert timing.progress_interval_seconds == 2.5
    assert timing.no_checks_grace_seconds == 0.0

def test_ship_check_timing_rejects_non_finite_values(monkeypatch: Any) -> None:
    monkeypatch.setenv("ENVCTL_SHIP_CHECK_TIMEOUT_SECONDS", "nan")
    monkeypatch.setenv("ENVCTL_SHIP_CHECK_POLL_INTERVAL_SECONDS", "inf")

    timing = action_ship_checks.ShipCheckTiming.from_inputs(
        progress_interval_seconds=float("nan"),
        no_checks_grace_seconds=float("inf"),
    )

    assert timing.timeout_seconds == action_ship_checks.DEFAULT_CHECK_TIMEOUT_SECONDS
    assert timing.poll_interval_seconds == action_ship_checks.DEFAULT_CHECK_POLL_INTERVAL_SECONDS
    assert timing.progress_interval_seconds == action_ship_checks.DEFAULT_CHECK_PROGRESS_INTERVAL_SECONDS
    assert timing.no_checks_grace_seconds == action_ship_checks.DEFAULT_NO_CHECKS_GRACE_SECONDS

def test_github_pr_checks_reports_no_checks_after_default_grace_for_expected_head(tmp_path: Path) -> None:
    clock = {"now": 0.0}
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(
                {
                    "headRefOid": "newsha",
                    "statusCheckRollup": [],
                    "url": "https://github.com/acme/repo/pull/7",
                }
            ),
            stderr="",
        )

    def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds

    checks = github_pr_checks(
        tmp_path,
        expected_head_sha="newsha",
        timeout_seconds=120.0,
        poll_interval_seconds=5.0,
        run_command=fake_run,
        monotonic=lambda: clock["now"],
        sleep=fake_sleep,
    )

    assert checks["state"] == "no_checks_reported"
    assert checks["duration_seconds"] == 15.0
    assert len(calls) == 4

def test_github_pr_checks_emits_progress_every_progress_interval_while_pending(tmp_path: Path) -> None:
    clock = {"now": 0.0}
    updates: list[str] = []
    outputs = [
        {
            "headRefOid": "newsha",
            "statusCheckRollup": [{"name": "pytest", "workflowName": "Tests", "status": "IN_PROGRESS"}],
        },
        {
            "headRefOid": "newsha",
            "statusCheckRollup": [{"name": "pytest", "workflowName": "Tests", "status": "IN_PROGRESS"}],
        },
        {
            "headRefOid": "newsha",
            "statusCheckRollup": [
                {"name": "pytest", "workflowName": "Tests", "status": "COMPLETED", "conclusion": "SUCCESS"}
            ],
        },
    ]

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["/usr/bin/gh", "api"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="[]", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(outputs.pop(0)), stderr="")

    def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds

    checks = github_pr_checks(
        tmp_path,
        expected_head_sha="newsha",
        timeout_seconds=120.0,
        poll_interval_seconds=10.0,
        progress_callback=updates.append,
        run_command=fake_run,
        monotonic=lambda: clock["now"],
        sleep=fake_sleep,
    )

    assert checks["state"] == "checks_passed"
    assert updates == ["ship: GitHub checks still running after 10s (pending=1, passed=0, failed=0, timeout=120s)"]

def test_github_pr_checks_ignores_non_test_checks_after_target_tests_pass(tmp_path: Path) -> None:
    clock = {"now": 0.0}
    outputs = [
        {
            "headRefOid": "newsha",
            "statusCheckRollup": [
                {"name": "pytest", "workflowName": "TeStS", "status": "IN_PROGRESS"},
                {"name": "security", "workflowName": "CodeQL", "status": "IN_PROGRESS"},
            ],
        },
        {
            "headRefOid": "newsha",
            "statusCheckRollup": [
                {"name": "pytest", "workflowName": "TeStS", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"name": "security", "workflowName": "CodeQL", "status": "IN_PROGRESS"},
            ],
        },
    ]

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["/usr/bin/gh", "api"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="[]", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(outputs.pop(0)), stderr="")

    def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds

    checks = github_pr_checks(
        tmp_path,
        expected_head_sha="newsha",
        timeout_seconds=120.0,
        poll_interval_seconds=5.0,
        run_command=fake_run,
        monotonic=lambda: clock["now"],
        sleep=fake_sleep,
    )

    assert checks["state"] == "checks_passed"
    assert checks["duration_seconds"] == 5.0
    assert checks["passed_checks"] == [{"name": "pytest", "workflow": "TeStS", "state": "SUCCESS"}]
    assert checks["pending_checks"] == []

def test_github_pr_checks_ignores_malformed_check_items(tmp_path: Path) -> None:
    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps(
                [
                    "unexpected-check-item",
                    {"name": "pytest", "workflow": "Tests", "state": "SUCCESS"},
                ]
            ),
            stderr="",
        )

    checks = github_pr_checks(
        tmp_path,
        run_command=fake_run,
    )

    assert checks["state"] == "checks_passed"
    assert checks["passed_checks"] == [{"name": "pytest", "workflow": "Tests", "state": "SUCCESS"}]

def test_github_pr_checks_can_detect_success_before_next_progress_heartbeat(tmp_path: Path) -> None:
    clock = {"now": 0.0}
    updates: list[str] = []
    outputs = [
        {
            "headRefOid": "newsha",
            "statusCheckRollup": [{"name": "pytest", "workflowName": "Tests", "status": "IN_PROGRESS"}],
        },
        {
            "headRefOid": "newsha",
            "statusCheckRollup": [
                {"name": "pytest", "workflowName": "Tests", "status": "COMPLETED", "conclusion": "SUCCESS"}
            ],
        },
    ]

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["/usr/bin/gh", "api"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="[]", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(outputs.pop(0)), stderr="")

    def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds

    checks = github_pr_checks(
        tmp_path,
        expected_head_sha="newsha",
        timeout_seconds=120.0,
        poll_interval_seconds=2.0,
        progress_interval_seconds=10.0,
        progress_callback=updates.append,
        run_command=fake_run,
        monotonic=lambda: clock["now"],
        sleep=fake_sleep,
    )

    assert checks["state"] == "checks_passed"
    assert checks["duration_seconds"] == 2.0
    assert updates == []

def test_github_pr_checks_waits_for_expected_head_sha_before_accepting_rollup(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    outputs = [
        {
            "headRefOid": "oldsha",
            "statusCheckRollup": [
                {
                    "__typename": "CheckRun",
                    "name": "pytest",
                    "workflowName": "Tests",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                    "detailsUrl": "https://github.com/acme/repo/actions/runs/1/job/1",
                }
            ],
        },
        {
            "headRefOid": "newsha",
            "statusCheckRollup": [
                {
                    "__typename": "CheckRun",
                    "name": "pytest",
                    "workflowName": "Tests",
                    "status": "IN_PROGRESS",
                    "conclusion": "",
                    "detailsUrl": "https://github.com/acme/repo/actions/runs/2/job/2",
                }
            ],
        },
        {
            "headRefOid": "newsha",
            "statusCheckRollup": [
                {
                    "__typename": "CheckRun",
                    "name": "pytest",
                    "workflowName": "Tests",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                    "detailsUrl": "https://github.com/acme/repo/actions/runs/2/job/2",
                }
            ],
        },
    ]

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:2] == ["/usr/bin/gh", "api"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="[]", stderr="")
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(outputs.pop(0)), stderr="")

    checks = github_pr_checks(
        tmp_path,
        expected_head_sha="newsha",
        timeout_seconds=5.0,
        poll_interval_seconds=0.01,
        run_command=fake_run,
        sleep=no_sleep,
    )

    assert checks["state"] == "checks_passed"
    assert checks["passed_checks"] == [
        {
            "name": "pytest",
            "workflow": "Tests",
            "state": "SUCCESS",
            "link": "https://github.com/acme/repo/actions/runs/2/job/2",
        }
    ]
    assert [call[:4] for call in calls if call[1:3] == ["pr", "view"]] == [
        ["/usr/bin/gh", "pr", "view", "feature/demo"],
        ["/usr/bin/gh", "pr", "view", "feature/demo"],
        ["/usr/bin/gh", "pr", "view", "feature/demo"],
    ]

def test_github_pr_checks_returns_no_checks_reported_without_polling(tmp_path: Path) -> None:
    calls = 0

    def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="no checks reported on the 'feature/demo' branch\n",
        )

    checks = github_pr_checks(
        tmp_path,
        timeout_seconds=30.0,
        poll_interval_seconds=0.01,
        run_command=fake_run,
        sleep=no_sleep,
    )

    assert checks["state"] == "no_checks_reported"
    assert checks["failing_checks"] == []
    assert checks["passed_checks"] == []
    assert checks["pending_checks"] == []
    assert calls == 1
