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

    def test_detect_default_branch_prefers_dev_then_main_then_master(self) -> None:
        calls: list[list[str]] = []

        def dev_exists(_git_root: Path, args: list[str]) -> str:
            calls.append(args)
            return "abc123\n" if args == ["rev-parse", "--verify", "refs/remotes/origin/dev"] else ""

        self.assertEqual(git_state.detect_default_branch(Path("/repo"), git_output=dev_exists), "dev")
        self.assertEqual(calls[0], ["rev-parse", "--verify", "refs/remotes/origin/dev"])
        self.assertTrue(any(args[:3] == ["ls-remote", "--symref", "origin"] for args in calls))

        def local_main(_git_root: Path, args: list[str]) -> str:
            if args == ["rev-parse", "--verify", "refs/heads/main"]:
                return "abc123\n"
            return ""

        self.assertEqual(git_state.detect_default_branch(Path("/repo"), git_output=local_main), "main")

        def remote_master(_git_root: Path, args: list[str]) -> str:
            if args == ["rev-parse", "--verify", "refs/remotes/origin/master"]:
                return "abc123\n"
            return ""

        self.assertEqual(git_state.detect_default_branch(Path("/repo"), git_output=remote_master), "master")

    def test_detect_default_branch_uses_remote_head_only_after_preferred_branches_are_absent(self) -> None:
        def remote_head(_git_root: Path, args: list[str]) -> str:
            if args == ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"]:
                return "origin/develop\n"
            return ""

        self.assertEqual(git_state.detect_default_branch(Path("/repo"), git_output=remote_head), "develop")

    def test_detect_default_branch_discovers_dev_omitted_by_local_fetch_refspec(self) -> None:
        def single_branch_clone(_git_root: Path, args: list[str]) -> str:
            if args == ["rev-parse", "--verify", "refs/remotes/origin/main"]:
                return "abc123\n"
            if args[:3] == ["ls-remote", "--symref", "origin"]:
                return "ref: refs/heads/main\tHEAD\nmainsha\tHEAD\ndevsha\trefs/heads/dev\nmainsha\trefs/heads/main\n"
            return ""

        self.assertEqual(
            git_state.detect_default_branch(Path("/repo"), git_output=single_branch_clone),
            "dev",
        )

    def test_live_remote_inventory_overrides_stale_deleted_dev_tracking_ref(self) -> None:
        def stale_dev(_git_root: Path, args: list[str]) -> str:
            if args == ["rev-parse", "--verify", "refs/remotes/origin/dev"]:
                return "stale-dev-sha\n"
            if args == ["rev-parse", "--verify", "refs/remotes/origin/main"]:
                return "main-sha\n"
            if args[:3] == ["ls-remote", "--symref", "origin"]:
                return (
                    "ref: refs/heads/main\tHEAD\n"
                    "main-sha\tHEAD\n"
                    "main-sha\trefs/heads/main\n"
                    "master-sha\trefs/heads/master\n"
                )
            return ""

        self.assertEqual(
            git_state.detect_default_branch(Path("/repo"), git_output=stale_dev),
            "main",
        )

    def test_live_remote_default_overrides_stale_dev_when_no_preferred_head_exists(self) -> None:
        def no_preferred_remote(_git_root: Path, args: list[str]) -> str:
            if args == ["rev-parse", "--verify", "refs/remotes/origin/dev"]:
                return "stale-dev-sha\n"
            if args[:3] == ["ls-remote", "--symref", "origin"]:
                return "ref: refs/heads/feature/alpha\tHEAD\nfeature-sha\tHEAD\n"
            return ""

        self.assertEqual(
            git_state.detect_default_branch(Path("/repo"), git_output=no_preferred_remote),
            "feature/alpha",
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
            return subprocess.CompletedProcess(
                args,
                0,
                stdout='[{"url":"https://github.com/acme/repo/pull/9","baseRefName":"dev"}]\n',
                stderr="",
            )

        url = git_state.existing_pr_url(Path("/repo"), "feature", gh_path="/usr/bin/gh", run_process=fake_run)

        self.assertEqual(url, "https://github.com/acme/repo/pull/9")
        self.assertEqual(calls[0][1], "/repo")
        self.assertEqual(calls[0][0][:4], ["/usr/bin/gh", "pr", "list", "--head"])
        self.assertIn("feature", calls[0][0])

    def test_existing_pull_request_preserves_base_metadata(self) -> None:
        def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                args,
                0,
                stdout='[{"url":"https://github.com/acme/repo/pull/9","baseRefName":"release"}]',
                stderr="",
            )

        existing = git_state.existing_pull_request(
            Path("/repo"),
            "feature",
            gh_path="/usr/bin/gh",
            run_process=fake_run,
        )

        self.assertEqual(
            existing,
            git_state.ExistingPullRequest(
                url="https://github.com/acme/repo/pull/9",
                base_branch="release",
            ),
        )

    def test_update_pull_request_base_uses_pr_url_and_reports_missing_gh(self) -> None:
        existing = git_state.ExistingPullRequest(url="https://github.com/acme/repo/pull/9", base_branch="main")
        calls: list[list[str]] = []

        def fake_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, stdout="updated\n", stderr="")

        updated = git_state.update_pull_request_base(
            Path("/repo"),
            existing,
            "dev",
            gh_path="/usr/bin/gh",
            run_process=fake_run,
        )
        missing = git_state.update_pull_request_base(
            Path("/repo"),
            existing,
            "dev",
            gh_path=None,
            run_process=lambda *_args, **_kwargs: self.fail("process should not run"),
        )

        self.assertEqual(updated.returncode, 0)
        self.assertEqual(
            calls,
            [["/usr/bin/gh", "pr", "edit", "https://github.com/acme/repo/pull/9", "--base", "dev"]],
        )
        self.assertEqual(missing.returncode, 127)
        self.assertIn("gh is required", missing.stderr)

    def test_existing_pr_url_skips_invalid_inputs_and_failed_gh(self) -> None:
        def unexpected_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            raise AssertionError("run_process should not be called")

        self.assertEqual(
            git_state.existing_pr_url(Path("/repo"), "HEAD", gh_path="/usr/bin/gh", run_process=unexpected_run), ""
        )
        self.assertEqual(
            git_state.existing_pr_url(Path("/repo"), "feature", gh_path=None, run_process=unexpected_run), ""
        )

    def test_remote_branch_probe_is_noninteractive_and_bounded(self) -> None:
        captured: dict[str, object] = {}

        def timed_out(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            captured.update(kwargs)
            raise subprocess.TimeoutExpired(args, timeout=float(kwargs["timeout"]))

        result = git_state.run_git(
            Path("/repo"),
            ["ls-remote", "--heads", "origin", "refs/heads/dev"],
            run_process=timed_out,
        )

        self.assertEqual(result.returncode, 124)
        self.assertEqual(captured["timeout"], 10)
        self.assertEqual(captured["env"]["GIT_TERMINAL_PROMPT"], "0")  # type: ignore[index]

        def failed_run(*args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="not found")

        self.assertEqual(
            git_state.existing_pr_url(Path("/repo"), "feature", gh_path="/usr/bin/gh", run_process=failed_run), ""
        )


if __name__ == "__main__":
    unittest.main()
