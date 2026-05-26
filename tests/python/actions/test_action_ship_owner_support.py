from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from envctl_engine.actions import action_ship_checks
from envctl_engine.actions import action_ship_check_queries
from envctl_engine.actions.action_ship_checks import normalize_github_pr_checks as normalize_checks_from_owner
from envctl_engine.actions.action_ship_check_results import (
    normalize_github_pr_checks as normalize_checks_from_result_owner,
    target_status_checks,
)
from envctl_engine.actions.action_ship_failure_logs import failure_log_excerpt
from envctl_engine.actions.action_ship_conflicts import parse_merge_tree_conflicts as parse_conflicts_from_owner
from envctl_engine.actions.action_ship_contract import (
    ship_action_payload as ship_action_payload_from_contract,
    ship_payload as ship_payload_from_owner,
)
from envctl_engine.actions.action_ship_support import (
    existing_merge_conflict_report,
    normalize_github_pr_checks,
    parse_merge_tree_conflicts,
    predicted_merge_conflict_report,
    parse_ship_json_output,
    print_ship_result,
    ship_payload,
)


@dataclass
class _Context:
    project_name: str
    project_root: Path
    repo_root: Path
    env: dict[str, str]


def test_existing_merge_conflict_report_includes_unmerged_stage_entries(tmp_path: Path) -> None:
    def git_output(_root: Path, args: list[str]) -> str:
        if args == ["diff", "--name-only", "--diff-filter=U"]:
            return "python/app.py\n"
        if args == ["ls-files", "-u"]:
            return "100644 aaaaa 1\tpython/app.py\n100644 bbbbb 2\tpython/app.py\n100644 ccccc 3\tpython/app.py\n"
        raise AssertionError(args)

    report = existing_merge_conflict_report(tmp_path, branch="feature", git_output=git_output)

    assert report["state"] == "conflicts"
    assert report["type"] == "unmerged_index"
    assert report["head_ref"] == "feature"
    assert report["conflicting_files"] == [
        {
            "path": "python/app.py",
            "kind": "unmerged_index",
            "stages": ["1", "2", "3"],
            "stage_entries": [
                {"mode": "100644", "object": "aaaaa", "stage": "1", "path": "python/app.py"},
                {"mode": "100644", "object": "bbbbb", "stage": "2", "path": "python/app.py"},
                {"mode": "100644", "object": "ccccc", "stage": "3", "path": "python/app.py"},
            ],
            "messages": ["Unmerged index entries exist for python/app.py."],
        }
    ]


def test_predicted_merge_conflict_report_parses_merge_tree_conflicts(tmp_path: Path) -> None:
    def git_output(_root: Path, args: list[str]) -> str:
        assert args == ["merge-base", "HEAD", "origin/main"]
        return "merge-base-sha\n"

    def run_git(_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        assert args == ["merge-tree", "--write-tree", "--messages", "--name-only", "HEAD", "origin/main"]
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout=("tree-sha\npython/app.py\n\nCONFLICT (content): Merge conflict in python/app.py\n"),
            stderr="",
        )

    report = predicted_merge_conflict_report(
        object(),
        tmp_path,
        branch="feature",
        resolve_base_branch=lambda _context, _root: "main",
        resolve_base_ref=lambda _root, _branch: "origin/main",
        run_git=run_git,
        git_output=git_output,
    )

    assert report["state"] == "conflicts"
    assert report["merge_base"] == "merge-base-sha"
    assert report["conflicting_files"] == [
        {
            "path": "python/app.py",
            "kind": "predicted_merge",
            "messages": ["CONFLICT (content): Merge conflict in python/app.py"],
        }
    ]


def test_parse_merge_tree_conflicts_falls_back_to_global_messages() -> None:
    assert parse_merge_tree_conflicts("tree\nREADME.md\n\nCONFLICT (rename/delete): conflict\n") == [
        {
            "path": "README.md",
            "kind": "predicted_merge",
            "messages": ["CONFLICT (rename/delete): conflict"],
        }
    ]


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
        {"name": "security", "workflow": "CodeQL", "state": "PENDING"},
        "malformed",
    ]

    assert target_status_checks(checks) == [{"name": "pytest", "workflow": "TeStS", "state": "SUCCESS"}]


def test_github_check_normalization_treats_completed_without_conclusion_as_pending() -> None:
    checks = normalize_checks_from_result_owner(
        [{"name": "pytest", "workflow": "Tests", "state": "COMPLETED"}],
        duration_seconds=0.25,
    )

    assert checks["state"] == "checks_pending_timeout"
    assert checks["passed_checks"] == []
    assert checks["pending_checks"] == [{"name": "pytest", "workflow": "Tests", "state": "COMPLETED"}]


def test_ship_failure_log_excerpt_starts_at_failure_section_and_strips_runner_prefixes() -> None:
    excerpt, truncated = failure_log_excerpt(
        "pytest\tRun pytest\t2026-05-25T20:00:00Z setup line\n"
        "pytest\tRun pytest\t2026-05-25T20:00:01Z ================= FAILURES =================\n"
        "pytest\tRun pytest\t2026-05-25T20:00:02Z FAILED tests/test_demo.py::test_demo - AssertionError\n"
        "pytest\tRun pytest\t2026-05-25T20:00:03Z Error: Process completed with exit code 1.\n"
    )

    assert excerpt == (
        "================= FAILURES =================\n"
        "FAILED tests/test_demo.py::test_demo - AssertionError\n"
        "Error: Process completed with exit code 1."
    )
    assert truncated is True


def test_github_pr_checks_polls_until_pending_checks_finish(tmp_path: Path, monkeypatch: Any) -> None:
    calls: list[list[str]] = []
    outputs = [
        [{"name": "pytest", "workflow": "Tests", "state": "PENDING", "link": "https://ci.test/1"}],
        [{"name": "pytest", "workflow": "Tests", "state": "SUCCESS", "link": "https://ci.test/1"}],
    ]

    class _Completed:
        returncode = 0
        stderr = ""

        @property
        def stdout(self) -> str:
            return json.dumps(outputs.pop(0))

    def fake_run(args: list[str], **_kwargs: object) -> _Completed:
        calls.append(args)
        return _Completed()

    monkeypatch.setattr(action_ship_checks.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(action_ship_checks.subprocess, "run", fake_run)
    monkeypatch.setattr(action_ship_checks.time, "sleep", lambda _seconds: None)

    checks = action_ship_checks.github_pr_checks(
        tmp_path,
        branch="feature/demo",
        pr_url="https://github.com/acme/repo/pull/7",
        timeout_seconds=5.0,
        poll_interval_seconds=0.01,
    )

    assert checks["state"] == "checks_passed"
    assert checks["pending_checks"] == []
    assert len(calls) == 2


def test_github_pr_checks_default_timeout_is_two_minute_wait_window() -> None:
    assert action_ship_checks.DEFAULT_CHECK_TIMEOUT_SECONDS == 120.0


def test_github_pr_checks_default_no_checks_grace_is_ten_seconds() -> None:
    assert action_ship_checks.DEFAULT_NO_CHECKS_GRACE_SECONDS == 10.0


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


def test_github_pr_checks_reports_no_checks_after_ten_second_grace_for_expected_head(
    tmp_path: Path, monkeypatch: Any
) -> None:
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

    monkeypatch.setattr(action_ship_checks.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(action_ship_checks.subprocess, "run", fake_run)
    monkeypatch.setattr(action_ship_checks.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(action_ship_checks.time, "sleep", fake_sleep)

    checks = action_ship_checks.github_pr_checks(
        tmp_path,
        branch="feature/demo",
        pr_url="https://github.com/acme/repo/pull/7",
        expected_head_sha="newsha",
        timeout_seconds=120.0,
        poll_interval_seconds=10.0,
    )

    assert checks["state"] == "no_checks_reported"
    assert checks["duration_seconds"] == 10.0
    assert len(calls) == 2


def test_github_pr_checks_emits_progress_every_progress_interval_while_pending(
    tmp_path: Path, monkeypatch: Any
) -> None:
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
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(outputs.pop(0)), stderr="")

    def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds

    monkeypatch.setattr(action_ship_checks.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(action_ship_checks.subprocess, "run", fake_run)
    monkeypatch.setattr(action_ship_checks.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(action_ship_checks.time, "sleep", fake_sleep)

    checks = action_ship_checks.github_pr_checks(
        tmp_path,
        branch="feature/demo",
        pr_url="https://github.com/acme/repo/pull/7",
        expected_head_sha="newsha",
        timeout_seconds=120.0,
        poll_interval_seconds=10.0,
        progress_callback=updates.append,
    )

    assert checks["state"] == "checks_passed"
    assert updates == ["ship: GitHub checks still running after 10s (pending=1, passed=0, failed=0, timeout=120s)"]


def test_github_pr_checks_ignores_non_test_checks_after_target_tests_pass(tmp_path: Path, monkeypatch: Any) -> None:
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
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(outputs.pop(0)), stderr="")

    def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds

    monkeypatch.setattr(action_ship_checks.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(action_ship_checks.subprocess, "run", fake_run)
    monkeypatch.setattr(action_ship_checks.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(action_ship_checks.time, "sleep", fake_sleep)

    checks = action_ship_checks.github_pr_checks(
        tmp_path,
        branch="feature/demo",
        pr_url="https://github.com/acme/repo/pull/7",
        expected_head_sha="newsha",
        timeout_seconds=120.0,
        poll_interval_seconds=5.0,
    )

    assert checks["state"] == "checks_passed"
    assert checks["duration_seconds"] == 5.0
    assert checks["passed_checks"] == [{"name": "pytest", "workflow": "TeStS", "state": "SUCCESS"}]
    assert checks["pending_checks"] == []


def test_github_pr_checks_ignores_malformed_check_items(tmp_path: Path, monkeypatch: Any) -> None:
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

    monkeypatch.setattr(action_ship_checks.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(action_ship_checks.subprocess, "run", fake_run)

    checks = action_ship_checks.github_pr_checks(
        tmp_path,
        branch="feature/demo",
        pr_url="https://github.com/acme/repo/pull/7",
    )

    assert checks["state"] == "checks_passed"
    assert checks["passed_checks"] == [{"name": "pytest", "workflow": "Tests", "state": "SUCCESS"}]


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


def test_github_pr_checks_can_detect_success_before_next_progress_heartbeat(tmp_path: Path, monkeypatch: Any) -> None:
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
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(outputs.pop(0)), stderr="")

    def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds

    monkeypatch.setattr(action_ship_checks.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(action_ship_checks.subprocess, "run", fake_run)
    monkeypatch.setattr(action_ship_checks.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(action_ship_checks.time, "sleep", fake_sleep)

    checks = action_ship_checks.github_pr_checks(
        tmp_path,
        branch="feature/demo",
        pr_url="https://github.com/acme/repo/pull/7",
        expected_head_sha="newsha",
        timeout_seconds=120.0,
        poll_interval_seconds=2.0,
        progress_interval_seconds=10.0,
        progress_callback=updates.append,
    )

    assert checks["state"] == "checks_passed"
    assert checks["duration_seconds"] == 2.0
    assert updates == []


def test_github_pr_checks_waits_for_expected_head_sha_before_accepting_rollup(tmp_path: Path, monkeypatch: Any) -> None:
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
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(outputs.pop(0)), stderr="")

    monkeypatch.setattr(action_ship_checks.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(action_ship_checks.subprocess, "run", fake_run)
    monkeypatch.setattr(action_ship_checks.time, "sleep", lambda _seconds: None)

    checks = action_ship_checks.github_pr_checks(
        tmp_path,
        branch="feature/demo",
        pr_url="https://github.com/acme/repo/pull/7",
        expected_head_sha="newsha",
        timeout_seconds=5.0,
        poll_interval_seconds=0.01,
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
    assert [call[:4] for call in calls] == [
        ["/usr/bin/gh", "pr", "view", "feature/demo"],
        ["/usr/bin/gh", "pr", "view", "feature/demo"],
        ["/usr/bin/gh", "pr", "view", "feature/demo"],
    ]


def test_github_pr_checks_returns_failed_check_without_waiting_for_timeout(tmp_path: Path, monkeypatch: Any) -> None:
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

    monkeypatch.setattr(action_ship_checks.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(action_ship_checks.subprocess, "run", fake_run)

    checks = action_ship_checks.github_pr_checks(
        tmp_path,
        branch="feature/demo",
        pr_url="https://github.com/acme/repo/pull/7",
        timeout_seconds=30.0,
        poll_interval_seconds=0.01,
    )

    assert checks["state"] == "checks_failed"
    assert checks["failing_checks"] == [
        {"name": "pytest", "workflow": "Tests", "state": "FAILURE", "link": "https://ci.test/1"}
    ]
    assert calls == 1


def test_github_pr_checks_adds_failed_check_log_excerpt(tmp_path: Path, monkeypatch: Any) -> None:
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

    monkeypatch.setattr(action_ship_checks.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(action_ship_checks.subprocess, "run", fake_run)

    checks = action_ship_checks.github_pr_checks(
        tmp_path,
        branch="feature/demo",
        pr_url="https://github.com/acme/repo/pull/7",
        timeout_seconds=30.0,
        poll_interval_seconds=0.01,
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


def test_github_pr_checks_retries_failed_check_logs_until_github_makes_them_available(
    tmp_path: Path, monkeypatch: Any
) -> None:
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
        raise AssertionError(args)

    def fake_sleep(seconds: float) -> None:
        clock["now"] += seconds

    monkeypatch.setattr(action_ship_checks.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(action_ship_checks.subprocess, "run", fake_run)
    monkeypatch.setattr(action_ship_checks.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(action_ship_checks.time, "sleep", fake_sleep)

    checks = action_ship_checks.github_pr_checks(
        tmp_path,
        branch="feature/demo",
        pr_url="https://github.com/acme/repo/pull/7",
        expected_head_sha="newsha",
        timeout_seconds=120.0,
        poll_interval_seconds=10.0,
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


def test_github_pr_checks_returns_no_checks_reported_without_polling(tmp_path: Path, monkeypatch: Any) -> None:
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

    monkeypatch.setattr(action_ship_checks.shutil, "which", lambda _name: "/usr/bin/gh")
    monkeypatch.setattr(action_ship_checks.subprocess, "run", fake_run)
    monkeypatch.setattr(action_ship_checks.time, "sleep", lambda _seconds: None)

    checks = action_ship_checks.github_pr_checks(
        tmp_path,
        branch="feature/demo",
        pr_url="https://github.com/acme/repo/pull/7",
        timeout_seconds=30.0,
        poll_interval_seconds=0.01,
    )

    assert checks["state"] == "no_checks_reported"
    assert checks["failing_checks"] == []
    assert checks["passed_checks"] == []
    assert checks["pending_checks"] == []
    assert calls == 1


def test_ship_payload_and_result_output_keep_json_contract(tmp_path: Path, capsys: Any) -> None:
    context = _Context(project_name="Main", project_root=tmp_path / "project", repo_root=tmp_path, env={})
    context.project_root.mkdir()

    payload = ship_payload(
        context=context,
        git_root=tmp_path,
        branch="feature",
        status="checks_passed",
        started=0.0,
        commit_sha="abc123",
        committed=True,
        pushed=True,
        pr_url="https://example.test/pr/1",
        pr_created=False,
        checks={"state": "checks_passed", "duration_seconds": 0.1},
        protected_paths=[".envctl-state/code-intelligence.json"],
    )
    code = print_ship_result(payload, json_output=True, ok=True)

    assert code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["contract_version"] == "envctl.ship.v1"
    assert printed["operation_statuses"] == {
        "checks": "checks_passed",
        "commit": "success",
        "merge_conflicts": "none",
        "pr": "existing",
        "push": "success",
    }
    assert printed["checks_state"] == "checks_passed"
    assert printed["passed_checks"] == []
    assert printed["checks_error"] == ""
    assert printed["checks_timeout_seconds"] == 0.0
    assert printed["protected_local_artifacts_skipped"] == [".envctl-state/code-intelligence.json"]
    assert parse_ship_json_output(_Context("Main", tmp_path, tmp_path, {})) is True
    assert parse_ship_json_output(_Context("Main", tmp_path, tmp_path, {"ENVCTL_ACTION_JSON": "true"})) is True
    assert parse_ship_json_output(_Context("Main", tmp_path, tmp_path, {"ENVCTL_ACTION_HUMAN": "true"})) is False


def test_ship_contract_owner_parses_embedded_payload_and_strips_ansi() -> None:
    output = (
        "\x1b[32mship progress\x1b[0m\n"
        "{\n"
        '  "contract_version": "envctl.ship.v1",\n'
        '  "status": "checks_pending_timeout"\n'
        "}\n"
    )

    assert ship_action_payload_from_contract(output) == {
        "contract_version": "envctl.ship.v1",
        "status": "checks_pending_timeout",
    }


def test_ship_payload_normalizes_malformed_nested_payloads(tmp_path: Path) -> None:
    context = _Context(project_name="Main", project_root=tmp_path / "project", repo_root=tmp_path, env={})
    context.project_root.mkdir()

    payload = ship_payload(
        context=context,
        git_root=tmp_path,
        branch="feature",
        status="checks_passed",
        started=0.0,
        checks={
            "state": "checks_passed",
            "passed_checks": "malformed",
            "failing_checks": {"name": "pytest"},
            "pending_checks": None,
        },
        merge_conflicts="malformed",  # type: ignore[arg-type]
    )

    assert payload["passed_checks"] == []
    assert payload["failing_checks"] == []
    assert payload["pending_checks"] == []
    assert payload["merge_conflicts"] == {}


def test_ship_result_human_output_includes_pr_creation_state(tmp_path: Path, capsys: Any) -> None:
    context = _Context(project_name="Main", project_root=tmp_path / "project", repo_root=tmp_path, env={})
    context.project_root.mkdir()
    payload = ship_payload(
        context=context,
        git_root=tmp_path,
        branch="feature",
        status="checks_passed",
        started=0.0,
        commit_sha="abc123",
        committed=True,
        pushed=True,
        pr_url="https://example.test/pr/1",
        pr_created=True,
        checks={"state": "checks_passed", "duration_seconds": 0.1},
    )

    code = print_ship_result(payload, json_output=False, ok=True)

    assert code == 0
    assert capsys.readouterr().out == "ship: checks_passed pr=created https://example.test/pr/1\n"


def test_ship_result_human_output_tolerates_malformed_operation_statuses(capsys: Any) -> None:
    code = print_ship_result(
        {
            "status": "checks_passed",
            "operation_statuses": "malformed",
            "pr_url": "https://example.test/pr/1",
        },
        json_output=False,
        ok=True,
    )

    assert code == 0
    assert capsys.readouterr().out == "ship: checks_passed https://example.test/pr/1\n"


def test_ship_support_reexports_cohesive_owner_modules() -> None:
    assert ship_payload is ship_payload_from_owner
    assert parse_merge_tree_conflicts is parse_conflicts_from_owner
    assert normalize_checks_from_owner is normalize_checks_from_result_owner
    assert normalize_github_pr_checks is normalize_checks_from_owner
