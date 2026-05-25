from __future__ import annotations

import json
import inspect
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import envctl_engine.actions.action_ship_support as ship_support
from envctl_engine.actions.action_ship_support import run_ship_workflow


class ActionShipSupportTests(unittest.TestCase):
    def test_public_run_ship_workflow_is_thin_compatibility_wrapper(self) -> None:
        source = inspect.getsource(run_ship_workflow)
        self.assertIn("ShipWorkflowRunner", source)
        self.assertLessEqual(len(source.splitlines()), 35)

    def test_ship_workflow_runner_exposes_named_phases(self) -> None:
        runner_cls = getattr(ship_support, "ShipWorkflowRunner", None)
        self.assertIsNotNone(runner_cls)
        for phase in (
            "_reject_unavailable_git",
            "_resolve_branch",
            "_reject_existing_merge_conflicts",
            "_run_commit_phase",
            "_run_pr_phase",
            "_reject_predicted_merge_conflicts",
            "_run_checks_phase",
        ):
            self.assertTrue(hasattr(runner_cls, phase), phase)

    def test_ship_workflow_dependencies_group_injected_collaborators(self) -> None:
        dependencies_cls = getattr(ship_support, "ShipWorkflowDependencies", None)
        self.assertIsNotNone(dependencies_cls)
        field_names = set(getattr(dependencies_cls, "__dataclass_fields__", {}))
        self.assertEqual(
            field_names,
            {
                "resolve_git_root",
                "git_available",
                "git_output",
                "run_git",
                "resolve_base_branch",
                "resolve_base_ref",
                "run_commit_action",
                "run_pr_action",
                "probe_dirty_worktree",
                "existing_pr_url",
                "partition_envctl_protected_paths",
                "ordered_unique_paths",
                "github_pr_checks",
            },
        )

        runner_fields = set(getattr(ship_support.ShipWorkflowRunner, "__dataclass_fields__", {}))
        self.assertEqual(runner_fields, {"context", "dependencies"})

    def test_run_ship_workflow_reuses_existing_pr_and_reports_failed_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir()
            context = SimpleNamespace(
                repo_root=repo_root,
                project_root=repo_root,
                project_name="Main",
                env={"ENVCTL_ACTION_JSON": "true"},
            )

            def git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/demo\n"
                if args == ["rev-parse", "HEAD"]:
                    return "abc123\n"
                return ""

            checks_expected_sha = ""

            def github_pr_checks(_git_root: Path, *, branch: str, pr_url: str, expected_head_sha: str) -> dict[str, object]:
                nonlocal checks_expected_sha
                self.assertEqual(branch, "feature/demo")
                self.assertEqual(pr_url, "https://github.com/acme/repo/pull/7")
                checks_expected_sha = expected_head_sha
                return {
                    "state": "checks_failed",
                    "failing_checks": [{"name": "pytest", "state": "FAILURE"}],
                    "passed_checks": [{"name": "ruff", "state": "SUCCESS"}],
                    "pending_checks": [],
                    "duration_seconds": 0.1,
                    "expected_head_sha": expected_head_sha,
                }

            with redirect_stdout(StringIO()) as stdout:
                code = run_ship_workflow(
                    context,
                    resolve_git_root=lambda project_root, repo_root: project_root,
                    git_available=True,
                    git_output=git_output,
                    run_git=lambda _git_root, args: subprocess.CompletedProcess(args=args, returncode=0),
                    resolve_base_branch=lambda _context, _git_root: "main",
                    resolve_base_ref=lambda _git_root, _base_branch: "origin/main",
                    run_commit_action=lambda _context: 0,
                    run_pr_action=lambda _context: 0,
                    probe_dirty_worktree=lambda *_args, **_kwargs: SimpleNamespace(dirty=False),
                    existing_pr_url=lambda _git_root, _branch: "https://github.com/acme/repo/pull/7",
                    partition_envctl_protected_paths=lambda _status: SimpleNamespace(
                        protected_staged_paths=[],
                        protected_skipped_paths=[],
                    ),
                    ordered_unique_paths=lambda *groups: [path for group in groups for path in group],
                    github_pr_checks=github_pr_checks,
                )

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "checks_failed")
        self.assertEqual(payload["step_statuses"], ["clean_no_changes", "pr_exists", "checks_failed"])
        self.assertEqual(
            payload["operation_statuses"],
            {
                "checks": "checks_failed",
                "commit": "no_changes",
                "merge_conflicts": "none",
                "pr": "existing",
                "push": "not_needed",
            },
        )
        self.assertEqual(payload["passed_checks"], [{"name": "ruff", "state": "SUCCESS"}])
        self.assertEqual(payload["failing_checks"], [{"name": "pytest", "state": "FAILURE"}])
        self.assertEqual(payload["pr_url"], "https://github.com/acme/repo/pull/7")
        self.assertEqual(checks_expected_sha, "abc123")
        self.assertEqual(payload["checks_expected_head_sha"], "abc123")

    def test_run_ship_workflow_creates_pr_and_reports_check_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir()
            context = SimpleNamespace(
                repo_root=repo_root,
                project_root=repo_root,
                project_name="Main",
                env={"ENVCTL_ACTION_JSON": "true"},
            )
            existing_calls = 0

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

            commit_called = False
            pr_called = False

            def run_commit_action(_context: object) -> int:
                nonlocal commit_called
                commit_called = True
                return 0

            def run_pr_action(_context: object) -> int:
                nonlocal pr_called
                pr_called = True
                return 0

            checks_expected_sha = ""

            def github_pr_checks(_git_root: Path, *, branch: str, pr_url: str, expected_head_sha: str) -> dict[str, object]:
                nonlocal checks_expected_sha
                self.assertEqual(branch, "feature/demo")
                self.assertEqual(pr_url, "https://github.com/acme/repo/pull/8")
                checks_expected_sha = expected_head_sha
                return {
                    "state": "checks_passed",
                    "passed_checks": [{"name": "pytest", "state": "SUCCESS"}],
                    "failing_checks": [],
                    "pending_checks": [],
                    "duration_seconds": 0.1,
                }

            with redirect_stdout(StringIO()) as stdout:
                code = run_ship_workflow(
                    context,
                    resolve_git_root=lambda project_root, repo_root: project_root,
                    git_available=True,
                    git_output=git_output,
                    run_git=lambda _git_root, args: subprocess.CompletedProcess(args=args, returncode=0),
                    resolve_base_branch=lambda _context, _git_root: "main",
                    resolve_base_ref=lambda _git_root, _base_branch: "origin/main",
                    run_commit_action=run_commit_action,
                    run_pr_action=run_pr_action,
                    probe_dirty_worktree=lambda *_args, **_kwargs: SimpleNamespace(dirty=True),
                    existing_pr_url=existing_pr_url,
                    partition_envctl_protected_paths=lambda _status: SimpleNamespace(
                        protected_staged_paths=[],
                        protected_skipped_paths=[],
                    ),
                    ordered_unique_paths=lambda *groups: [path for group in groups for path in group],
                    github_pr_checks=github_pr_checks,
                )

        self.assertEqual(code, 0)
        self.assertTrue(commit_called)
        self.assertTrue(pr_called)
        self.assertEqual(checks_expected_sha, "after")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "checks_passed")
        self.assertEqual(payload["step_statuses"], ["committed_pushed", "pr_created", "checks_passed"])
        self.assertEqual(
            payload["operation_statuses"],
            {
                "checks": "checks_passed",
                "commit": "success",
                "merge_conflicts": "none",
                "pr": "created",
                "push": "success",
            },
        )
        self.assertEqual(payload["passed_checks"], [{"name": "pytest", "state": "SUCCESS"}])
        self.assertEqual(payload["pr_url"], "https://github.com/acme/repo/pull/8")

    def test_run_ship_workflow_returns_failure_when_checks_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir()
            context = SimpleNamespace(
                repo_root=repo_root,
                project_root=repo_root,
                project_name="Main",
                env={"ENVCTL_ACTION_JSON": "true"},
            )

            def git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/demo\n"
                if args == ["rev-parse", "HEAD"]:
                    return "abc123\n"
                return ""

            with redirect_stdout(StringIO()) as stdout:
                code = run_ship_workflow(
                    context,
                    resolve_git_root=lambda project_root, repo_root: project_root,
                    git_available=True,
                    git_output=git_output,
                    run_git=lambda _git_root, args: subprocess.CompletedProcess(args=args, returncode=0),
                    resolve_base_branch=lambda _context, _git_root: "main",
                    resolve_base_ref=lambda _git_root, _base_branch: "origin/main",
                    run_commit_action=lambda _context: 0,
                    run_pr_action=lambda _context: 0,
                    probe_dirty_worktree=lambda *_args, **_kwargs: SimpleNamespace(dirty=False),
                    existing_pr_url=lambda _git_root, _branch: "https://github.com/acme/repo/pull/7",
                    partition_envctl_protected_paths=lambda _status: SimpleNamespace(
                        protected_staged_paths=[],
                        protected_skipped_paths=[],
                    ),
                    ordered_unique_paths=lambda *groups: [path for group in groups for path in group],
                    github_pr_checks=lambda _git_root, *, branch, pr_url, expected_head_sha: {
                        "state": "checks_pending_timeout",
                        "failing_checks": [],
                        "passed_checks": [{"name": "ruff", "state": "SUCCESS"}],
                        "pending_checks": [{"name": "pytest", "state": "QUEUED"}],
                        "duration_seconds": 30.0,
                        "timeout_seconds": 30.0,
                    },
                )

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "checks_pending_timeout")
        self.assertEqual(payload["operation_statuses"]["checks"], "checks_pending_timeout")
        self.assertEqual(payload["checks_timeout_seconds"], 30.0)
        self.assertEqual(payload["pending_checks"], [{"name": "pytest", "state": "QUEUED"}])

    def test_run_ship_workflow_treats_no_checks_as_successful_ship_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir()
            context = SimpleNamespace(
                repo_root=repo_root,
                project_root=repo_root,
                project_name="Main",
                env={"ENVCTL_ACTION_JSON": "true"},
            )

            def git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/demo\n"
                if args == ["rev-parse", "HEAD"]:
                    return "abc123\n"
                return ""

            with redirect_stdout(StringIO()) as stdout:
                code = run_ship_workflow(
                    context,
                    resolve_git_root=lambda project_root, repo_root: project_root,
                    git_available=True,
                    git_output=git_output,
                    run_git=lambda _git_root, args: subprocess.CompletedProcess(args=args, returncode=0),
                    resolve_base_branch=lambda _context, _git_root: "main",
                    resolve_base_ref=lambda _git_root, _base_branch: "origin/main",
                    run_commit_action=lambda _context: 0,
                    run_pr_action=lambda _context: 0,
                    probe_dirty_worktree=lambda *_args, **_kwargs: SimpleNamespace(dirty=False),
                    existing_pr_url=lambda _git_root, _branch: "https://github.com/acme/repo/pull/7",
                    partition_envctl_protected_paths=lambda _status: SimpleNamespace(
                        protected_staged_paths=[],
                        protected_skipped_paths=[],
                    ),
                    ordered_unique_paths=lambda *groups: [path for group in groups for path in group],
                    github_pr_checks=lambda _git_root, *, branch, pr_url, expected_head_sha: {
                        "state": "no_checks_reported",
                        "failing_checks": [],
                        "passed_checks": [],
                        "pending_checks": [],
                        "duration_seconds": 0.1,
                    },
                )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "no_checks_reported")
        self.assertEqual(payload["operation_statuses"]["checks"], "no_checks_reported")


if __name__ == "__main__":
    unittest.main()
