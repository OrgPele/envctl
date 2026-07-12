from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.actions import action_commit_support
from envctl_engine.actions.action_protected_artifacts import partition_envctl_protected_paths


def _completed(args: list[str], stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)


class ActionCommitSupportTests(unittest.TestCase):
    def test_commit_workflow_skips_protected_artifacts_and_advances_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            ledger = project_root / ".envctl-commit-message.md"
            ledger.write_text("Old summary\n\n### Envctl pointer ###\nNew summary\n", encoding="utf-8")
            context = SimpleNamespace(
                repo_root=project_root,
                project_root=project_root,
                project_name="Main",
                env={},
            )
            seen: list[list[str]] = []

            def _run_git(_git_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
                seen.append(args)
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return _completed(args, stdout="?? .envctl-commit-message.md\n M app.py\n")
                if args == ["status", "--porcelain"]:
                    return _completed(args, stdout="M  app.py\n?? .envctl-commit-message.md\n")
                return _completed(args)

            code = action_commit_support.run_commit_workflow(
                context,
                resolve_git_root=lambda project_root, _repo_root: project_root,
                git_available=True,
                git_output=lambda _git_root, _args: "feature-branch\n",
                run_git=_run_git,
                print_error=lambda _prefix, _result: None,
                partition_envctl_protected_paths=partition_envctl_protected_paths,
                ordered_unique_paths=lambda *groups: [item for group in groups for item in group],
            )

            self.assertEqual(code, 0)
            self.assertIn(["add", "--all", "--", "app.py"], seen)
            self.assertTrue(any(args[:2] == ["commit", "-F"] for args in seen))
            self.assertIn(["push", "-u", "origin", "feature-branch"], seen)
            self.assertEqual(ledger.read_text(encoding="utf-8"), "Old summary\n\nNew summary\n\n### Envctl pointer ###\n")

    def test_stage_paths_records_unstaged_tracked_deletions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            git_root = Path(temp_dir)

            def run_git(_git_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    ["git", *args],
                    cwd=git_root,
                    text=True,
                    capture_output=True,
                    check=False,
                )

            for args in (
                ["init"],
                ["config", "user.email", "envctl-tests@example.invalid"],
                ["config", "user.name", "Envctl Tests"],
            ):
                self.assertEqual(run_git(git_root, args).returncode, 0)
            obsolete = git_root / "obsolete.py"
            obsolete.write_text("obsolete = True\n", encoding="utf-8")
            self.assertEqual(run_git(git_root, ["add", "obsolete.py"]).returncode, 0)
            self.assertEqual(run_git(git_root, ["commit", "-m", "initial"]).returncode, 0)
            obsolete.unlink()

            runner = action_commit_support.CommitWorkflowRunner(
                context=SimpleNamespace(),
                dependencies=action_commit_support.CommitWorkflowDependencies(
                    resolve_git_root=lambda project_root, _repo_root: project_root,
                    git_available=True,
                    git_output=lambda _git_root, _args: "",
                    run_git=run_git,
                    print_error=lambda _prefix, _result: None,
                    partition_envctl_protected_paths=partition_envctl_protected_paths,
                    ordered_unique_paths=lambda *groups: [item for group in groups for item in group],
                ),
            )

            self.assertTrue(runner._stage_paths(git_root, ["obsolete.py"]))
            staged = run_git(git_root, ["diff", "--cached", "--name-status"])
            self.assertEqual(staged.returncode, 0)
            self.assertEqual(staged.stdout.strip(), "D\tobsolete.py")

    def test_stage_candidates_preserves_an_already_staged_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            git_root = Path(temp_dir)

            def run_git(_git_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    ["git", *args],
                    cwd=git_root,
                    text=True,
                    capture_output=True,
                    check=False,
                )

            for args in (
                ["init"],
                ["config", "user.email", "envctl-tests@example.invalid"],
                ["config", "user.name", "Envctl Tests"],
            ):
                self.assertEqual(run_git(git_root, args).returncode, 0)
            obsolete = git_root / "obsolete.py"
            obsolete.write_text("obsolete = True\n", encoding="utf-8")
            self.assertEqual(run_git(git_root, ["add", "obsolete.py"]).returncode, 0)
            self.assertEqual(run_git(git_root, ["commit", "-m", "initial"]).returncode, 0)
            obsolete.unlink()
            self.assertEqual(run_git(git_root, ["add", "--all"]).returncode, 0)

            runner = action_commit_support.CommitWorkflowRunner(
                context=SimpleNamespace(),
                dependencies=action_commit_support.CommitWorkflowDependencies(
                    resolve_git_root=lambda project_root, _repo_root: project_root,
                    git_available=True,
                    git_output=lambda _git_root, _args: "",
                    run_git=run_git,
                    print_error=lambda _prefix, _result: None,
                    partition_envctl_protected_paths=partition_envctl_protected_paths,
                    ordered_unique_paths=lambda *groups: [item for group in groups for item in group],
                ),
            )

            partition = runner._stage_commit_candidates(git_root)
            self.assertIsNotNone(partition)
            staged = run_git(git_root, ["diff", "--cached", "--name-status"])
            self.assertEqual(staged.returncode, 0)
            self.assertEqual(staged.stdout.strip(), "D\tobsolete.py")

    def test_read_commit_ledger_segment_reports_empty_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = Path(temp_dir) / ".envctl-commit-message.md"
            ledger.write_text("Archived\n\n### Envctl pointer ###\n", encoding="utf-8")

            payload, error = action_commit_support.read_commit_ledger_segment(ledger)

            self.assertEqual(payload, "")
            self.assertIsNotNone(error)
            self.assertIn("empty after the pointer", str(error))


if __name__ == "__main__":
    unittest.main()
