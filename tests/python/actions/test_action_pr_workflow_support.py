from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace

from envctl_engine.actions import action_pr_workflow_support as support


class ActionPrWorkflowSupportTests(unittest.TestCase):
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
                existing_pr_url_fn=lambda _git_root, _branch: "https://github.com/acme/repo/pull/12",
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
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="https://example.test/pr/1\n", stderr="")

            def write_body(_body: str) -> Path:
                body_file.write_text("Body", encoding="utf-8")
                return body_file

            code = support.run_pr_workflow(
                context,
                resolve_git_root_fn=lambda project_root, _repo_root: project_root,
                git_available=True,
                git_output_fn=lambda _git_root, _args: "feature/demo\n",
                resolve_base_branch_fn=lambda _context, _git_root: "main",
                existing_pr_url_fn=lambda _git_root, _branch: "",
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


if __name__ == "__main__":
    unittest.main()
