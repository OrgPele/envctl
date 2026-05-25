from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from envctl_engine.actions import action_ship_checks
from envctl_engine.actions.action_ship_checks import normalize_github_pr_checks as normalize_checks_from_owner
from envctl_engine.actions.action_ship_conflicts import parse_merge_tree_conflicts as parse_conflicts_from_owner
from envctl_engine.actions.action_ship_contract import ship_payload as ship_payload_from_owner
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
            return (
                "100644 aaaaa 1\tpython/app.py\n"
                "100644 bbbbb 2\tpython/app.py\n"
                "100644 ccccc 3\tpython/app.py\n"
            )
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
            stdout=(
                "tree-sha\n"
                "python/app.py\n"
                "\n"
                "CONFLICT (content): Merge conflict in python/app.py\n"
            ),
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

    failed = normalize_github_pr_checks(checks, duration_seconds=1.25)
    assert failed["state"] == "checks_failed"
    assert failed["failing_checks"] == [{"name": "pytest", "state": "FAILED"}]
    assert failed["passed_checks"] == [{"name": "ruff", "state": "SUCCESS"}]
    assert failed["pending_checks"] == [{"name": "build", "state": "QUEUED"}]
    assert failed["duration_seconds"] == 1.25

    pending = normalize_github_pr_checks([{"name": "pytest", "state": "PENDING"}], duration_seconds=0.5)
    assert pending["state"] == "checks_pending_timeout"

    passed = normalize_github_pr_checks([{"name": "ruff", "state": "SKIPPED"}], duration_seconds=0.25)
    assert passed["state"] == "checks_passed"
    assert passed["passed_checks"] == [{"name": "ruff", "state": "SKIPPED"}]


def test_github_pr_checks_polls_until_pending_checks_finish(tmp_path: Path, monkeypatch: Any) -> None:
    calls: list[list[str]] = []
    outputs = [
        [{"name": "pytest", "state": "PENDING", "link": "https://ci.test/1"}],
        [{"name": "pytest", "state": "SUCCESS", "link": "https://ci.test/1"}],
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


def test_github_pr_checks_default_timeout_is_fast_handoff_window() -> None:
    assert action_ship_checks.DEFAULT_CHECK_TIMEOUT_SECONDS == 10.0


def test_github_pr_checks_waits_for_expected_head_sha_before_accepting_rollup(
    tmp_path: Path, monkeypatch: Any
) -> None:
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
            stdout=json.dumps([{"name": "pytest", "state": "FAILURE", "link": "https://ci.test/1"}]),
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
    assert checks["failing_checks"] == [{"name": "pytest", "state": "FAILURE", "link": "https://ci.test/1"}]
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


def test_ship_support_reexports_cohesive_owner_modules() -> None:
    assert ship_payload is ship_payload_from_owner
    assert parse_merge_tree_conflicts is parse_conflicts_from_owner
    assert normalize_github_pr_checks is normalize_checks_from_owner
