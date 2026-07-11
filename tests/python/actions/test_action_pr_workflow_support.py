from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace

from envctl_engine.actions import action_pr_workflow_support as support
from envctl_engine.actions.action_git_state_support import ExistingPullRequest


class ActionPrWorkflowSupportTests(unittest.TestCase):
    def test_pr_workflow_rejects_default_branch_as_the_head(self) -> None:
        context = SimpleNamespace(
            repo_root=Path("/repo"),
            project_root=Path("/repo"),
            project_name="Main",
        )

        code = support.run_pr_workflow(
            context,
            resolve_git_root_fn=lambda project_root, _repo_root: project_root,
            git_available=True,
            git_output_fn=lambda _git_root, _args: "dev\n",
            resolve_base_branch_fn=lambda _context, _git_root: "dev",
            existing_pull_request_fn=lambda *_args: None,
            update_pull_request_base_fn=lambda *_args: self.fail("base update should not run"),
            probe_dirty_worktree_fn=lambda *_args: self.fail("worktree should not be probed"),
            run_commit_action_fn=lambda _context: self.fail("commit should not run"),
            pr_title_fn=lambda *_args: self.fail("title should not be built"),
            pr_body_fn=lambda *_args: self.fail("body should not be built"),
            write_pr_body_file_fn=lambda _body: self.fail("body file should not be written"),
            print_process_output_fn=lambda _result: None,
            gh_path="/usr/bin/gh",
        )

        self.assertEqual(code, 1)

    def test_pr_workflow_rediscovers_existing_pr_before_self_base_guard(self) -> None:
        context = SimpleNamespace(
            repo_root=Path("/repo"),
            project_root=Path("/repo"),
            project_name="Main",
        )

        code = support.run_pr_workflow(
            context,
            resolve_git_root_fn=lambda project_root, _repo_root: project_root,
            git_available=True,
            git_output_fn=lambda _git_root, _args: "dev\n",
            resolve_base_branch_fn=lambda _context, _git_root: "dev",
            existing_pull_request_fn=lambda _git_root, _branch: ExistingPullRequest(
                url="https://github.com/acme/repo/pull/12",
                base_branch="dev",
            ),
            update_pull_request_base_fn=lambda *_args: self.fail("base update should not run"),
            probe_dirty_worktree_fn=lambda *_args: self.fail("worktree should not be probed"),
            run_commit_action_fn=lambda _context: self.fail("commit should not run"),
            pr_title_fn=lambda *_args: self.fail("title should not be built"),
            pr_body_fn=lambda *_args: self.fail("body should not be built"),
            write_pr_body_file_fn=lambda _body: self.fail("body file should not be written"),
            print_process_output_fn=lambda _result: None,
            gh_path="/usr/bin/gh",
        )

        self.assertEqual(code, 0)

    def test_pr_workflow_skips_existing_pull_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            context = SimpleNamespace(repo_root=repo_root, project_root=repo_root, project_name="Main")
            calls: list[list[str]] = []

            code = support.run_pr_workflow(
                context,
                resolve_git_root_fn=lambda project_root, _repo_root: project_root,
                git_available=True,
                git_output_fn=lambda _git_root, _args: "feature/demo\n",
                resolve_base_branch_fn=lambda _context, _git_root: "main",
                existing_pull_request_fn=lambda _git_root, _branch: ExistingPullRequest(
                    url="https://github.com/acme/repo/pull/12",
                    base_branch="main",
                ),
                update_pull_request_base_fn=lambda *_args: self.fail("base update should not run"),
                probe_dirty_worktree_fn=lambda *_args: self.fail("dirty worktree should not be probed"),
                run_commit_action_fn=lambda _context: self.fail("commit should not run"),
                pr_title_fn=lambda *_args: self.fail("title should not be built"),
                pr_body_fn=lambda *_args: self.fail("body should not be built"),
                write_pr_body_file_fn=lambda _body: self.fail("body file should not be written"),
                print_process_output_fn=lambda _result: None,
                gh_path="/usr/bin/gh",
                run_process_fn=lambda args, **_kwargs: calls.append(list(args)),
            )

            self.assertEqual(code, 0)
            self.assertEqual(calls, [])

    def test_pr_workflow_creates_with_gh_and_removes_body_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            context = SimpleNamespace(repo_root=repo_root, project_root=repo_root, project_name="Main")
            body_file = repo_root / "body.md"
            calls: list[list[str]] = []

            def run_process(args: list[str], **_kwargs):  # noqa: ANN001
                calls.append([str(token) for token in args])
                self.assertTrue(body_file.is_file())
                return subprocess.CompletedProcess(
                    args=args, returncode=0, stdout="https://example.test/pr/1\n", stderr=""
                )

            def write_body(_body: str) -> Path:
                body_file.write_text("Body", encoding="utf-8")
                return body_file

            code = support.run_pr_workflow(
                context,
                resolve_git_root_fn=lambda project_root, _repo_root: project_root,
                git_available=True,
                git_output_fn=lambda _git_root, _args: "feature/demo\n",
                resolve_base_branch_fn=lambda _context, _git_root: "main",
                existing_pull_request_fn=lambda _git_root, _branch: None,
                update_pull_request_base_fn=lambda *_args: self.fail("base update should not run"),
                probe_dirty_worktree_fn=lambda *_args: SimpleNamespace(dirty=False),
                run_commit_action_fn=lambda _context: self.fail("commit should not run"),
                pr_title_fn=lambda _context, _git_root, _head_branch: "Demo PR",
                pr_body_fn=lambda _context, _git_root, _head_branch, _base_branch: "Body",
                write_pr_body_file_fn=write_body,
                print_process_output_fn=lambda _result: None,
                gh_path="/usr/bin/gh",
                run_process_fn=run_process,
            )

            self.assertEqual(code, 0)
            self.assertFalse(body_file.exists())
            self.assertEqual(calls[0][:5], ["/usr/bin/gh", "pr", "create", "--title", "Demo PR"])
            self.assertIn("--base", calls[0])
            self.assertIn("main", calls[0])

    def test_explicit_base_updates_existing_pr_and_verifies_result(self) -> None:
        context = SimpleNamespace(
            repo_root=Path("/repo"),
            project_root=Path("/repo"),
            project_name="Main",
            env={"ENVCTL_PR_BASE": "release"},
        )
        existing_values = iter(
            [
                ExistingPullRequest("https://github.com/acme/repo/pull/12", "main"),
                ExistingPullRequest("https://github.com/acme/repo/pull/12", "release"),
            ]
        )
        update_calls: list[tuple[ExistingPullRequest, str]] = []

        def update_base(
            _git_root: Path,
            existing: ExistingPullRequest,
            base_branch: str,
        ) -> subprocess.CompletedProcess[str]:
            update_calls.append((existing, base_branch))
            return subprocess.CompletedProcess([], 0, stdout="updated\n", stderr="")

        code = support.run_pr_workflow(
            context,
            resolve_git_root_fn=lambda project_root, _repo_root: project_root,
            git_available=True,
            git_output_fn=lambda _git_root, _args: "feature/demo\n",
            resolve_base_branch_fn=lambda *_args: self.fail("implicit resolver should not run"),
            existing_pull_request_fn=lambda *_args: next(existing_values),
            update_pull_request_base_fn=update_base,
            probe_dirty_worktree_fn=lambda *_args: self.fail("worktree should not be probed"),
            run_commit_action_fn=lambda _context: self.fail("commit should not run"),
            pr_title_fn=lambda *_args: self.fail("title should not be built"),
            pr_body_fn=lambda *_args: self.fail("body should not be built"),
            write_pr_body_file_fn=lambda _body: self.fail("body file should not be written"),
            print_process_output_fn=lambda _result: None,
            gh_path="/usr/bin/gh",
        )

        self.assertEqual(code, 0)
        self.assertEqual(len(update_calls), 1)
        self.assertEqual(update_calls[0][1], "release")

    def test_implicit_default_preserves_existing_pr_base(self) -> None:
        context = SimpleNamespace(
            repo_root=Path("/repo"),
            project_root=Path("/repo"),
            project_name="Main",
            env={},
        )

        code = support.run_pr_workflow(
            context,
            resolve_git_root_fn=lambda project_root, _repo_root: project_root,
            git_available=True,
            git_output_fn=lambda _git_root, _args: "feature/demo\n",
            resolve_base_branch_fn=lambda *_args: self.fail("implicit resolver should not run for an existing PR"),
            existing_pull_request_fn=lambda *_args: ExistingPullRequest(
                "https://github.com/acme/repo/pull/12",
                "main",
            ),
            update_pull_request_base_fn=lambda *_args: self.fail("base update should not run"),
            probe_dirty_worktree_fn=lambda *_args: self.fail("worktree should not be probed"),
            run_commit_action_fn=lambda _context: self.fail("commit should not run"),
            pr_title_fn=lambda *_args: self.fail("title should not be built"),
            pr_body_fn=lambda *_args: self.fail("body should not be built"),
            write_pr_body_file_fn=lambda _body: self.fail("body file should not be written"),
            print_process_output_fn=lambda _result: None,
            gh_path="/usr/bin/gh",
        )

        self.assertEqual(code, 0)

    def test_failed_gh_create_recovers_concurrent_matching_pr(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            context = SimpleNamespace(repo_root=repo_root, project_root=repo_root, project_name="Main", env={})
            existing_values = iter(
                [
                    None,
                    ExistingPullRequest("https://github.com/acme/repo/pull/13", "dev"),
                ]
            )
            body_file = repo_root / "body.md"

            code = support.run_pr_workflow(
                context,
                resolve_git_root_fn=lambda project_root, _repo_root: project_root,
                git_available=True,
                git_output_fn=lambda _git_root, _args: "feature/race\n",
                resolve_base_branch_fn=lambda *_args: "dev",
                existing_pull_request_fn=lambda *_args: next(existing_values),
                update_pull_request_base_fn=lambda *_args: self.fail("base update should not run"),
                probe_dirty_worktree_fn=lambda *_args: SimpleNamespace(dirty=False),
                run_commit_action_fn=lambda _context: self.fail("commit should not run"),
                pr_title_fn=lambda *_args: "Race",
                pr_body_fn=lambda *_args: "Body",
                write_pr_body_file_fn=lambda _body: body_file,
                print_process_output_fn=lambda _result: self.fail("recovered create error should stay quiet"),
                gh_path="/usr/bin/gh",
                run_process_fn=lambda args, **_kwargs: subprocess.CompletedProcess(
                    args,
                    1,
                    stdout="",
                    stderr="a pull request already exists",
                ),
            )

            self.assertEqual(code, 0)

    def test_failed_helper_create_recovers_concurrent_matching_pr(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir)
            helper = repo_root / "utils" / "create-pr.sh"
            helper.parent.mkdir(parents=True)
            helper.write_text("#!/bin/sh\n", encoding="utf-8")
            helper.chmod(0o755)
            context = SimpleNamespace(repo_root=repo_root, project_root=repo_root, project_name="Main", env={})
            existing_values = iter(
                [
                    None,
                    ExistingPullRequest("https://github.com/acme/repo/pull/14", "dev"),
                ]
            )

            code = support.run_pr_workflow(
                context,
                resolve_git_root_fn=lambda project_root, _repo_root: project_root,
                git_available=True,
                git_output_fn=lambda _git_root, _args: "feature/race\n",
                resolve_base_branch_fn=lambda *_args: "dev",
                existing_pull_request_fn=lambda *_args: next(existing_values),
                update_pull_request_base_fn=lambda *_args: self.fail("base update should not run"),
                probe_dirty_worktree_fn=lambda *_args: SimpleNamespace(dirty=False),
                run_commit_action_fn=lambda _context: self.fail("commit should not run"),
                pr_title_fn=lambda *_args: self.fail("title should not be built"),
                pr_body_fn=lambda *_args: self.fail("body should not be built"),
                write_pr_body_file_fn=lambda _body: self.fail("body file should not be written"),
                print_process_output_fn=lambda _result: self.fail("recovered helper error should stay quiet"),
                gh_path=None,
                run_process_fn=lambda args, **_kwargs: subprocess.CompletedProcess(
                    args,
                    1,
                    stdout="",
                    stderr="a pull request already exists",
                ),
            )

            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
