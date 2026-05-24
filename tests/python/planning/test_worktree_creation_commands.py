from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from envctl_engine.planning.worktree_creation_commands import (
    run_worktree_add,
    worktree_branch_exists,
    worktree_branch_name,
    worktree_start_point,
)


class WorktreeCreationCommandsTests(unittest.TestCase):
    def test_worktree_branch_name_joins_feature_and_iteration(self) -> None:
        self.assertEqual(worktree_branch_name(feature="feature-a", iteration="2"), "feature-a-2")

    def test_worktree_branch_exists_verifies_normalized_branch_ref(self) -> None:
        calls: list[list[str]] = []

        self.assertFalse(worktree_branch_exists(branch_name="  ", git_command_output=lambda args: "unused"))

        exists = worktree_branch_exists(
            branch_name=" feature-a-1 ",
            git_command_output=lambda args: calls.append(args) or "deadbeef\n",
        )

        self.assertTrue(exists)
        self.assertEqual(calls, [["rev-parse", "--verify", "refs/heads/feature-a-1"]])

    def test_worktree_start_point_prefers_source_ref_then_source_branch_then_head(self) -> None:
        calls: list[list[str]] = []

        def git_command_output(args: list[str]) -> str:
            calls.append(args)
            if args == ["rev-parse", "--verify", "origin/dev"]:
                return "origin-sha\n"
            if args == ["rev-parse", "--verify", "dev"]:
                return "branch-sha\n"
            if args == ["rev-parse", "HEAD"]:
                return "head-sha\n"
            return ""

        start_point = worktree_start_point(
            provenance={"source_ref": "origin/dev", "source_branch": "dev"},
            git_command_output=git_command_output,
        )

        self.assertEqual(start_point, "origin/dev")
        self.assertEqual(calls, [["rev-parse", "--verify", "origin/dev"]])

    def test_worktree_start_point_falls_back_to_branch_and_head(self) -> None:
        self.assertEqual(
            worktree_start_point(
                provenance={"source_ref": "origin/missing", "source_branch": "dev"},
                git_command_output=lambda args: "branch-sha\n"
                if args == ["rev-parse", "--verify", "dev"]
                else "",
            ),
            "dev",
        )
        self.assertEqual(
            worktree_start_point(
                provenance={},
                git_command_output=lambda args: "head-sha\n" if args == ["rev-parse", "HEAD"] else "",
            ),
            "head-sha",
        )
        self.assertIsNone(worktree_start_point(provenance={}, git_command_output=lambda _args: ""))

    def test_run_worktree_add_builds_hook_disabled_command_with_existing_branch_and_start_point(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            target = repo_root / "trees" / "feature-a" / "1"
            env = {"PLAN_FILE": "/tmp/plan.md"}
            calls: list[dict[str, object]] = []

            def run(command: list[str], *, cwd: Path, env: dict[str, str], timeout: float) -> object:
                calls.append({"command": command, "cwd": cwd, "env": env, "timeout": timeout})
                return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

            result = run_worktree_add(
                repo_root=repo_root,
                feature="feature-a",
                iteration="1",
                target=target,
                env=env,
                git_hooks_disabled=True,
                branch_exists=lambda branch_name: branch_name == "feature-a-1",
                start_point=lambda: "origin/dev",
                run=run,
            )

            self.assertEqual(getattr(result, "returncode"), 0)
            self.assertEqual(
                calls,
                [
                    {
                        "command": [
                            "git",
                            "-c",
                            "core.hooksPath=/dev/null",
                            "-C",
                            str(repo_root),
                            "worktree",
                            "add",
                            "-B",
                            "feature-a-1",
                            str(target),
                            "origin/dev",
                        ],
                        "cwd": repo_root,
                        "env": env,
                        "timeout": 120.0,
                    }
                ],
            )

    def test_run_worktree_add_uses_new_branch_flag_without_start_point_or_hook_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            target = repo_root / "trees" / "feature-a" / "1"
            commands: list[list[str]] = []

            run_worktree_add(
                repo_root=repo_root,
                feature="feature-a",
                iteration="1",
                target=target,
                env={},
                git_hooks_disabled=False,
                branch_exists=lambda _branch_name: False,
                start_point=lambda: "",
                run=lambda command, **_kwargs: commands.append(command)
                or subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr=""),
            )

            self.assertEqual(
                commands,
                [
                    [
                        "git",
                        "-C",
                        str(repo_root),
                        "worktree",
                        "add",
                        "-b",
                        "feature-a-1",
                        str(target),
                    ]
                ],
            )


if __name__ == "__main__":
    unittest.main()
