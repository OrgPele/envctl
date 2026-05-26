from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.python.actions.ship_workflow_test_support import ship_workflow_fixture


def test_run_ship_workflow_reuses_existing_pr_and_reports_failed_checks() -> None:
    with ship_workflow_fixture() as fixture:
        checks_expected_sha = ""

        def github_pr_checks(
            _git_root: Path,
            *,
            branch: str,
            pr_url: str,
            expected_head_sha: str,
        ) -> dict[str, object]:
            nonlocal checks_expected_sha
            assert branch == "feature/demo"
            assert pr_url == "https://github.com/acme/repo/pull/7"
            checks_expected_sha = expected_head_sha
            return {
                "state": "checks_failed",
                "failing_checks": [{"name": "pytest", "state": "FAILURE"}],
                "passed_checks": [{"name": "ruff", "state": "SUCCESS"}],
                "pending_checks": [],
                "duration_seconds": 0.1,
                "expected_head_sha": expected_head_sha,
            }

        result = fixture.run(github_pr_checks=github_pr_checks)

    assert result.code == 1
    assert result.payload["status"] == "checks_failed"
    assert result.payload["step_statuses"] == ["clean_no_changes", "pr_exists", "checks_failed"]
    assert result.payload["operation_statuses"] == {
        "checks": "checks_failed",
        "commit": "no_changes",
        "merge_conflicts": "none",
        "pr": "existing",
        "push": "not_needed",
    }
    assert result.payload["passed_checks"] == [{"name": "ruff", "state": "SUCCESS"}]
    assert result.payload["failing_checks"] == [{"name": "pytest", "state": "FAILURE"}]
    assert result.payload["pr_url"] == "https://github.com/acme/repo/pull/7"
    assert checks_expected_sha == "abc123"
    assert result.payload["checks_expected_head_sha"] == "abc123"


def test_run_ship_workflow_pushes_clean_local_head_when_existing_pr_branch_is_stale() -> None:
    with ship_workflow_fixture() as fixture:
        run_git_calls: list[list[str]] = []
        checks_expected_sha = ""

        def run_git(_git_root: Path, args: list[str]):
            run_git_calls.append(args)
            if args == ["rev-parse", "--verify", "@{u}"]:
                return SimpleNamespace(returncode=0, stdout="old123\n", stderr="", args=args)
            if args == ["push", "-u", "origin", "feature/demo"]:
                return SimpleNamespace(returncode=0, stdout="", stderr="", args=args)
            return SimpleNamespace(returncode=0, stdout="", stderr="", args=args)

        def github_pr_checks(
            _git_root: Path,
            *,
            branch: str,
            pr_url: str,
            expected_head_sha: str,
        ) -> dict[str, object]:
            nonlocal checks_expected_sha
            assert branch == "feature/demo"
            assert pr_url == "https://github.com/acme/repo/pull/7"
            checks_expected_sha = expected_head_sha
            return {
                "state": "checks_passed",
                "passed_checks": [{"name": "pytest", "state": "SUCCESS"}],
                "failing_checks": [],
                "pending_checks": [],
                "duration_seconds": 0.1,
                "expected_head_sha": expected_head_sha,
                "actual_head_sha": expected_head_sha,
            }

        result = fixture.run(run_git=run_git, github_pr_checks=github_pr_checks)

    assert result.code == 0
    assert ["push", "-u", "origin", "feature/demo"] in run_git_calls
    assert checks_expected_sha == "abc123"
    assert result.payload["status"] == "checks_passed"
    assert result.payload["step_statuses"] == [
        "clean_no_changes",
        "pr_exists",
        "pushed_existing_head",
        "checks_passed",
    ]
    assert result.payload["operation_statuses"] == {
        "checks": "checks_passed",
        "commit": "no_changes",
        "merge_conflicts": "none",
        "pr": "existing",
        "push": "success",
    }
    assert result.payload["committed"] is False
    assert result.payload["pushed"] is True
    assert result.payload["checks_expected_head_sha"] == "abc123"
    assert result.payload["checks_actual_head_sha"] == "abc123"


def test_run_ship_workflow_fails_on_detached_head() -> None:
    with ship_workflow_fixture() as fixture:
        commit_called = False
        pr_called = False
        checks_called = False

        def git_output(_git_root: Path, args: list[str]) -> str:
            if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                return "HEAD\n"
            if args == ["rev-parse", "HEAD"]:
                return "abc123\n"
            return ""

        def run_commit_action(_context: object) -> int:
            nonlocal commit_called
            commit_called = True
            return 0

        def run_pr_action(_context: object) -> int:
            nonlocal pr_called
            pr_called = True
            return 0

        def github_pr_checks(*_args: object, **_kwargs: object) -> dict[str, object]:
            nonlocal checks_called
            checks_called = True
            return {"state": "checks_passed", "failing_checks": [], "pending_checks": []}

        result = fixture.run(
            git_output=git_output,
            run_commit_action=run_commit_action,
            run_pr_action=run_pr_action,
            existing_pr_url=lambda _git_root, _branch: "",
            github_pr_checks=github_pr_checks,
        )

    assert result.code == 1
    assert commit_called is False
    assert pr_called is False
    assert checks_called is False
    assert result.payload["status"] == "detached_head"
    assert result.payload["operation_statuses"] == {
        "checks": "not_run",
        "commit": "not_run",
        "merge_conflicts": "not_checked",
        "pr": "not_run",
        "push": "not_run",
    }


def test_run_ship_workflow_creates_pr_and_reports_check_success() -> None:
    with ship_workflow_fixture() as fixture:
        existing_calls = 0
        commit_called = False
        pr_called = False
        checks_expected_sha = ""

        def git_output(_git_root: Path, args: list[str]) -> str:
            if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                return "feature/demo\n"
            if args == ["rev-parse", "HEAD"]:
                return "before\n" if not commit_called else "after\n"
            return ""

        def existing_pr_url(_git_root: Path, _branch: str) -> str:
            nonlocal existing_calls
            existing_calls += 1
            return "" if existing_calls == 1 else "https://github.com/acme/repo/pull/8"

        def run_commit_action(_context: object) -> int:
            nonlocal commit_called
            commit_called = True
            return 0

        def run_pr_action(_context: object) -> int:
            nonlocal pr_called
            pr_called = True
            return 0

        def github_pr_checks(
            _git_root: Path,
            *,
            branch: str,
            pr_url: str,
            expected_head_sha: str,
        ) -> dict[str, object]:
            nonlocal checks_expected_sha
            assert branch == "feature/demo"
            assert pr_url == "https://github.com/acme/repo/pull/8"
            checks_expected_sha = expected_head_sha
            return {
                "state": "checks_passed",
                "passed_checks": [{"name": "pytest", "state": "SUCCESS"}],
                "failing_checks": [],
                "pending_checks": [],
                "duration_seconds": 0.1,
            }

        result = fixture.run(
            git_output=git_output,
            run_commit_action=run_commit_action,
            run_pr_action=run_pr_action,
            probe_dirty_worktree=lambda *_args, **_kwargs: SimpleNamespace(dirty=True),
            existing_pr_url=existing_pr_url,
            github_pr_checks=github_pr_checks,
        )

    assert result.code == 0
    assert commit_called is True
    assert pr_called is True
    assert checks_expected_sha == "after"
    assert result.payload["status"] == "checks_passed"
    assert result.payload["step_statuses"] == ["committed_pushed", "pr_created", "checks_passed"]
    assert result.payload["operation_statuses"] == {
        "checks": "checks_passed",
        "commit": "success",
        "merge_conflicts": "none",
        "pr": "created",
        "push": "success",
    }
    assert result.payload["passed_checks"] == [{"name": "pytest", "state": "SUCCESS"}]
    assert result.payload["pr_url"] == "https://github.com/acme/repo/pull/8"
    assert result.stderr.splitlines() == [
        "ship: add succeeded for Main.",
        "ship: commit succeeded for Main (after).",
        "ship: push succeeded for Main.",
        "ship: PR created for Main: https://github.com/acme/repo/pull/8",
    ]


def test_run_ship_workflow_fails_when_pr_action_succeeds_but_pr_url_is_unresolved() -> None:
    with ship_workflow_fixture() as fixture:
        checks_called = False
        commit_called = False

        def git_output(_git_root: Path, args: list[str]) -> str:
            if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                return "feature/demo\n"
            if args == ["rev-parse", "HEAD"]:
                return "before\n" if not commit_called else "after\n"
            return ""

        def run_commit_action(_context: object) -> int:
            nonlocal commit_called
            commit_called = True
            return 0

        def github_pr_checks(*_args: object, **_kwargs: object) -> dict[str, object]:
            nonlocal checks_called
            checks_called = True
            return {"state": "checks_passed", "failing_checks": [], "pending_checks": []}

        result = fixture.run(
            git_output=git_output,
            run_commit_action=run_commit_action,
            probe_dirty_worktree=lambda *_args, **_kwargs: SimpleNamespace(dirty=True),
            existing_pr_url=lambda _git_root, _branch: "",
            github_pr_checks=github_pr_checks,
        )

    assert result.code == 1
    assert checks_called is False
    assert result.payload["status"] == "pr_unresolved"
    assert result.payload["step_statuses"] == ["committed_pushed", "pr_unresolved"]
    assert result.payload["operation_statuses"] == {
        "checks": "not_run",
        "commit": "success",
        "merge_conflicts": "not_checked",
        "pr": "unresolved",
        "push": "success",
    }
    assert result.payload["commit_sha"] == "after"
    assert result.payload["pr_url"] == ""


def test_run_ship_workflow_does_not_report_commit_success_when_dirty_artifacts_are_skipped() -> None:
    with ship_workflow_fixture() as fixture:

        def git_output(_git_root: Path, args: list[str]) -> str:
            if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                return "feature/demo\n"
            if args == ["rev-parse", "HEAD"]:
                return "abc123\n"
            if args == ["status", "--porcelain", "--untracked-files=all"]:
                return "?? .envctl-state/code-intelligence.json\n"
            return ""

        result = fixture.run(
            git_output=git_output,
            probe_dirty_worktree=lambda *_args, **_kwargs: SimpleNamespace(dirty=True),
            partition_envctl_protected_paths=lambda _status: SimpleNamespace(
                protected_staged_paths=[],
                protected_skipped_paths=[".envctl-state/code-intelligence.json"],
            ),
        )

    assert result.code == 0
    assert result.payload["status"] == "checks_passed"
    assert result.payload["step_statuses"] == ["clean_no_changes", "pr_exists", "checks_passed"]
    assert result.payload["operation_statuses"] == {
        "checks": "checks_passed",
        "commit": "no_changes",
        "merge_conflicts": "none",
        "pr": "existing",
        "push": "not_needed",
    }
    assert result.payload["committed"] is False
    assert result.payload["pushed"] is False
    assert result.payload["protected_local_artifacts_skipped"] == [".envctl-state/code-intelligence.json"]
    assert result.stderr.splitlines() == [
        "ship: PR already exists for Main: https://github.com/acme/repo/pull/7"
    ]
