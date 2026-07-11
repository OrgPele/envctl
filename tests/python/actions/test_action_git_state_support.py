from __future__ import annotations

from pathlib import Path
import subprocess
import unittest

from envctl_engine.actions import action_git_state_support as git_state


class ActionGitStateSupportTests(unittest.TestCase):
    def test_probe_dirty_worktree_classifies_status_with_project_name_fallback(self) -> None:
        project_root = Path("/tmp/work/project")
        repo_root = Path("/tmp/work")

        def fake_git_output(_git_root: Path, args: list[str]) -> str:
            self.assertEqual(args, ["status", "--porcelain", "--untracked-files=all"])
            return "M  staged.py\n M unstaged.py\n?? new.py\n"

        report = git_state.probe_dirty_worktree(project_root, repo_root, git_output=fake_git_output)

        self.assertEqual(report.project_name, "project")
        self.assertEqual(report.git_root, project_root)
        self.assertTrue(report.staged)
        self.assertTrue(report.unstaged)
        self.assertTrue(report.untracked)
        self.assertTrue(report.dirty)

    def test_detect_default_branch_prefers_origin_head_then_local_candidates(self) -> None:
        calls: list[list[str]] = []

        def origin_head(_git_root: Path, args: list[str]) -> str:
            calls.append(args)
            return "origin/develop\n"

        self.assertEqual(git_state.detect_default_branch(Path("/repo"), git_output=origin_head), "develop")
        self.assertEqual(calls, [["symbolic-ref", "--short", "refs/remotes/origin/HEAD"]])

        def local_main(_git_root: Path, args: list[str]) -> str:
            if args == ["rev-parse", "--verify", "main"]:
                return "abc123\n"
            return ""

        self.assertEqual(git_state.detect_default_branch(Path("/repo"), git_output=local_main), "main")

    def test_detect_pr_base_branch_prefers_remote_or_local_dev_then_main_then_master(self) -> None:
        def resolve(
            existing_refs: set[str],
            remote_heads: set[str] | None = None,
            *,
            origin_default: str = "",
            symbolic_default: bool = True,
        ) -> str:
            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args[:2] == ["ls-remote", "--heads"]:
                    return "".join(
                        f"abc123\trefs/heads/{branch}\n" for branch in sorted(remote_heads or set())
                    )
                if args == ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"]:
                    return f"origin/{origin_default}\n" if origin_default and symbolic_default else ""
                if args == ["ls-remote", "--symref", "origin", "HEAD"]:
                    return f"ref: refs/heads/{origin_default}\tHEAD\nabc123\tHEAD\n" if origin_default else ""
                self.assertEqual(args[:2], ["rev-parse", "--verify"])
                return "abc123\n" if args[2] in existing_refs else ""

            return git_state.detect_pr_base_branch(Path("/repo"), git_output=fake_git_output)

        self.assertEqual(resolve({"origin/dev", "origin/main", "origin/master"}), "dev")
        self.assertEqual(resolve({"dev", "origin/main"}), "dev")
        self.assertEqual(resolve({"origin/main", "origin/master"}), "main")
        self.assertEqual(resolve({"main", "origin/master"}), "main")
        self.assertEqual(resolve({"origin/master"}), "master")
        self.assertEqual(resolve({"master"}), "master")
        self.assertEqual(resolve(set()), "master")
        self.assertEqual(resolve(set(), {"dev", "main"}), "dev")
        self.assertEqual(resolve(set(), {"main", "master"}), "main")
        self.assertEqual(resolve(set(), origin_default="develop"), "develop")
        self.assertEqual(resolve(set(), origin_default="trunk", symbolic_default=False), "trunk")

    def test_detect_pr_base_branch_does_not_probe_origin_when_local_candidate_exists(self) -> None:
        calls: list[list[str]] = []

        def local_main(_git_root: Path, args: list[str]) -> str:
            calls.append(args)
            if args == ["rev-parse", "--verify", "origin/main"]:
                return "abc123\n"
            if args[0] == "ls-remote":
                raise AssertionError("remote must not be probed when a local base ref is available")
            return ""

        self.assertEqual(
            git_state.detect_pr_base_branch(Path("/repo"), git_output=local_main),
            "main",
        )
        self.assertEqual(
            calls,
            [
                ["rev-parse", "--verify", "origin/dev"],
                ["rev-parse", "--verify", "dev"],
                ["rev-parse", "--verify", "origin/main"],
            ],
        )

    def test_existing_pr_url_uses_gh_pr_list_for_open_branch(self) -> None:
        calls: list[tuple[list[str], str]] = []

        def fake_run(
            args: list[str],
            *,
            cwd: str,
            text: bool,
            capture_output: bool,
            check: bool,
        ) -> subprocess.CompletedProcess[str]:
            self.assertTrue(text)
            self.assertTrue(capture_output)
            self.assertFalse(check)
            calls.append((args, cwd))
            return subprocess.CompletedProcess(args, 0, stdout="https://github.com/acme/repo/pull/9\n", stderr="")

        url = git_state.existing_pr_url(Path("/repo"), "feature", gh_path="/usr/bin/gh", run_process=fake_run)

        self.assertEqual(url, "https://github.com/acme/repo/pull/9")
        self.assertEqual(calls[0][1], "/repo")
        self.assertEqual(calls[0][0][:4], ["/usr/bin/gh", "pr", "list", "--head"])
        self.assertIn("feature", calls[0][0])

    def test_existing_pr_url_skips_invalid_inputs_and_failed_gh(self) -> None:
        def unexpected_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            raise AssertionError("run_process should not be called")

        self.assertEqual(git_state.existing_pr_url(Path("/repo"), "HEAD", gh_path="/usr/bin/gh", run_process=unexpected_run), "")
        self.assertEqual(git_state.existing_pr_url(Path("/repo"), "feature", gh_path=None, run_process=unexpected_run), "")

        def failed_run(*args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="not found")

        self.assertEqual(git_state.existing_pr_url(Path("/repo"), "feature", gh_path="/usr/bin/gh", run_process=failed_run), "")


if __name__ == "__main__":
    unittest.main()
