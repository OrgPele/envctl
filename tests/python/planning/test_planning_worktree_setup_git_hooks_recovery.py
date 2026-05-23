# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.planning_worktree_setup_test_support import *


class PlanningWorktreeSetupGitHooksRecoveryTests(PlanningWorktreeSetupTestCase):
    def test_setup_worktree_creation_can_inherit_git_hooks_by_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_WORKTREE_GIT_HOOKS": "inherit"})

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    self._worktree_add_index(command)
                    self._assert_hooks_inherited_for_worktree_add(command)
                    target = Path(command[-2])
                    target.mkdir(parents=True, exist_ok=True)
                    (target / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]

            error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)

    def test_invalid_worktree_git_hooks_policy_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_WORKTREE_GIT_HOOKS": "maybe"})

            with self.assertRaisesRegex(RuntimeError, "ENVCTL_WORKTREE_GIT_HOOKS"):
                engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

    def test_setup_worktree_recovers_partial_git_worktree_after_late_hook_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "venv").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime)
            events: list[dict[str, object]] = []
            engine._emit = lambda event, **payload: events.append({"event": event, **payload})  # type: ignore[method-assign]

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/late-hook-failure\n", encoding="utf-8")
                    return subprocess.CompletedProcess(
                        args=command,
                        returncode=1,
                        stdout="",
                        stderr="post-checkout hook failed",
                    )
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]

            error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertTrue((target_root / ".git").exists())
            self.assertTrue((target_root / "backend" / "venv").is_symlink())
            self.assertEqual(self._read_provenance(target_root).get("source_branch"), "dev")
            self.assertTrue(
                any(item.get("event") == "setup.worktree.partial_git_failure_recovered" for item in events)
            )

    def test_plan_sync_recovers_partial_git_worktree_without_advancing_iteration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "implementations_task" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime)

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/late-hook-failure\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="hook failed")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]

            result = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                plan_counts={"implementations/task.md": 1},
                raw_projects=[],
                keep_plan=True,
            )

            self.assertIsNone(result.error)
            self.assertEqual([item.name for item in result.created_worktrees], ["implementations_task-1"])
            self.assertTrue((target_root / "MAIN_TASK.md").is_file())
            self.assertFalse((repo / "trees" / "implementations_task" / "2").exists())

    def test_hook_inheritance_surfaces_late_hook_failure_even_when_target_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_WORKTREE_GIT_HOOKS": "inherit"})

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/hook-failure\n", encoding="utf-8")
                    return subprocess.CompletedProcess(
                        args=command,
                        returncode=1,
                        stdout="",
                        stderr="post-checkout hook failed",
                    )
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]

            error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNotNone(error)
            self.assertIn("post-checkout hook failed", error or "")

    def test_plan_sync_reports_created_worktree_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime, env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true"})

            result = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                plan_counts={"implementations/task.md": 2},
                raw_projects=[],
                keep_plan=True,
            )

            self.assertIsNone(result.error)
            self.assertEqual([item.name for item in result.created_worktrees], ["implementations_task-1", "implementations_task-2"])
            self.assertEqual(
                [item.root for item in result.created_worktrees],
                [
                    (repo / "trees" / "implementations_task" / "1").resolve(),
                    (repo / "trees" / "implementations_task" / "2").resolve(),
                ],
            )
            self.assertTrue((result.created_worktrees[0].root / "MAIN_TASK.md").is_file())
            self.assertEqual(result.created_worktrees[0].plan_file, "implementations/task.md")

    def test_plan_sync_reports_only_new_worktrees_as_launch_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true"})
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001

            result = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                plan_counts={"implementations/task.md": 2},
                raw_projects=raw_projects,
                keep_plan=True,
            )

            self.assertIsNone(result.error)
            self.assertEqual(len(result.raw_projects), 2)
            self.assertEqual([item.name for item in result.created_worktrees], ["implementations_task-2"])
