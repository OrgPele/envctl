from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.actions.action_ship_support import run_ship_workflow


class ActionShipSupportTests(unittest.TestCase):
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
                    github_pr_checks=lambda _git_root, *, branch, pr_url: {
                        "state": "checks_failed",
                        "failing_checks": [{"name": "pytest", "state": "FAILURE"}],
                        "pending_checks": [],
                        "duration_seconds": 0.1,
                    },
                )

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "checks_failed")
        self.assertEqual(payload["step_statuses"], ["clean_no_changes", "pr_exists", "checks_failed"])
        self.assertEqual(payload["pr_url"], "https://github.com/acme/repo/pull/7")


if __name__ == "__main__":
    unittest.main()
