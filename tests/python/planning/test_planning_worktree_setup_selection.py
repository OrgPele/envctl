# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.planning_worktree_setup_test_support import *


class PlanningWorktreeSetupSelectionTests(PlanningWorktreeSetupTestCase):
    def test_invalid_planning_selection_is_strict_and_no_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime)
            contexts = engine._discover_projects(mode="trees")
            route = parse_route(["--plan", "implementations/missing"], env={})

            out = StringIO()
            with redirect_stdout(out):
                selected = engine._select_plan_projects(route, contexts)

            self.assertEqual(selected, [])
            self.assertIn("Planning file not found", out.getvalue())

    def test_plan_selection_uses_execution_root_plans_from_linked_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = root / "runtime"
            gitdir = repo / ".git" / "worktrees" / "feature-a-1"
            gitdir.mkdir(parents=True, exist_ok=True)
            (repo / ".git").mkdir(exist_ok=True)
            (repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=trees\n", encoding="utf-8")
            (worktree / "todo" / "plans" / "features").mkdir(parents=True, exist_ok=True)
            (worktree / "todo" / "plans" / "features" / "task.md").write_text("# task\n", encoding="utf-8")
            (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")

            engine = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_EXECUTION_ROOT": str(worktree),
                    "ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true",
                },
            )
            route = parse_route(["--plan", "features/task"], env={})

            selected = engine._select_plan_projects(route, [])

            self.assertEqual(engine.config.base_dir, repo.resolve())
            self.assertEqual(engine.config.planning_dir, (worktree / "todo" / "plans").resolve())
            self.assertEqual([ctx.name for ctx in selected], ["features_task-1"])
            self.assertEqual(
                (repo / "trees" / "features_task" / "1" / "MAIN_TASK.md").read_text(encoding="utf-8"),
                "# task\n",
            )

    def test_interactive_plan_dry_run_previews_without_syncing_worktrees_or_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime)
            orchestrator = engine.planning_worktree_orchestrator
            route = parse_route(["--plan", "--dry-run"], env={})
            sync_calls: list[dict[str, int]] = []
            save_calls: list[dict[str, int]] = []

            def fake_menu(
                planning_files: list[str],
                selected_counts: dict[str, int],
                existing_counts: dict[str, int],
            ) -> dict[str, int]:
                self.assertEqual(planning_files, ["feature/task.md"])
                self.assertEqual(existing_counts, {"feature/task.md": 0})
                return {"feature/task.md": 1}

            def fake_sync(**kwargs: object) -> object:
                sync_calls.append(dict(kwargs["plan_counts"]))  # type: ignore[index,arg-type]
                return engine._sync_plan_worktrees_from_plan_counts(**kwargs)  # type: ignore[arg-type]

            def fake_save(chosen: dict[str, int]) -> None:
                save_calls.append(dict(chosen))

            with (
                patch.object(orchestrator, "_run_planning_selection_menu", side_effect=fake_menu),
                patch.object(orchestrator, "_sync_plan_worktrees_from_plan_counts", side_effect=fake_sync),
                patch.object(orchestrator, "_save_plan_selection_memory", side_effect=fake_save),
                patch.object(sys.stdin, "isatty", return_value=True),
                patch.object(sys.stdout, "isatty", return_value=True),
            ):
                selected = engine._select_plan_projects(route, [])

            self.assertEqual([ctx.name for ctx in selected], ["feature_task-1"])
            self.assertEqual(sync_calls, [])
            self.assertEqual(save_calls, [])
            self.assertFalse((repo / "trees" / "feature_task" / "1").exists())
            result = orchestrator.last_plan_selection_result()
            self.assertEqual([worktree.name for worktree in result.created_worktrees], ["feature_task-1"])

    def test_plan_selection_creates_missing_worktrees_for_requested_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime, env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true"})
            initial = engine._discover_projects(mode="trees")
            self.assertEqual(initial, [])
            route = parse_route(["--plan", "implementations/task,implementations/task"], env={})

            selected = engine._select_plan_projects(route, initial)

            names = [ctx.name for ctx in selected]
            self.assertEqual(names, ["implementations_task-1", "implementations_task-2"])
            self.assertTrue((repo / "trees" / "implementations_task" / "1").is_dir())
            self.assertTrue((repo / "trees" / "implementations_task" / "2").is_dir())
            self.assertEqual(
                (repo / "trees" / "implementations_task" / "1" / "MAIN_TASK.md").read_text(encoding="utf-8"),
                "# task\n",
            )
            self.assertEqual(
                (repo / "trees" / "implementations_task" / "2" / "MAIN_TASK.md").read_text(encoding="utf-8"),
                "# task\n",
            )

    def test_plan_selection_create_missing_worktrees_fails_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime)
            initial = engine._discover_projects(mode="trees")
            route = parse_route(["--plan", "implementations/task,implementations/task"], env={})

            out = StringIO()
            with redirect_stdout(out):
                selected = engine._select_plan_projects(route, initial)

            self.assertEqual(selected, [])
            self.assertIn("failed creating worktree implementations_task/1", out.getvalue().lower())

    def test_plan_selection_deletes_excess_worktrees_to_match_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")
            for iteration in (1, 2, 3):
                (repo / "trees" / "implementations_task" / str(iteration)).mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime)
            cleanup_calls: list[tuple[str, Path, str]] = []

            def fake_blast_worktree_before_delete(*, project_name: str, project_root: Path, source_command: str):
                cleanup_calls.append((project_name, project_root, source_command))
                return []

            engine._blast_worktree_before_delete = fake_blast_worktree_before_delete  # type: ignore[assignment]
            contexts = engine._discover_projects(mode="trees")
            route = parse_route(["--plan", "implementations/task"], env={})

            selected = engine._select_plan_projects(route, contexts)

            self.assertEqual([ctx.name for ctx in selected], ["implementations_task-1"])
            self.assertTrue((repo / "trees" / "implementations_task" / "1").is_dir())
            self.assertFalse((repo / "trees" / "implementations_task" / "2").exists())
            self.assertFalse((repo / "trees" / "implementations_task" / "3").exists())
            self.assertEqual(
                cleanup_calls,
                [
                    (
                        "implementations_task-3",
                        (repo / "trees" / "implementations_task" / "3").resolve(),
                        "blast-worktree",
                    ),
                    (
                        "implementations_task-2",
                        (repo / "trees" / "implementations_task" / "2").resolve(),
                        "blast-worktree",
                    ),
                ],
            )

    def test_plan_selection_records_launch_candidates_for_startup_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime, env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true"})
            route = parse_route(["--plan", "implementations/task"], env={})

            selected = engine._select_plan_projects(route, [])

            selection_result = engine.planning_worktree_orchestrator.last_plan_selection_result()
            self.assertIsInstance(selection_result, PlanSelectionResult)
            self.assertEqual([ctx.name for ctx in selected], ["implementations_task-1"])
            self.assertEqual([item.name for item in selection_result.created_worktrees], ["implementations_task-1"])

    def test_plan_selection_with_new_session_launch_creates_and_targets_next_iteration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true"})
            contexts = engine._discover_projects(mode="trees")
            route = parse_route(
                ["--plan", "implementations/task", "--tmux", "--opencode", "--headless", "--new-session"],
                env={},
            )

            selected = engine._select_plan_projects(route, contexts)

            selection_result = engine.planning_worktree_orchestrator.last_plan_selection_result()
            self.assertEqual([ctx.name for ctx in selected], ["implementations_task-2"])
            self.assertEqual([item.name for item in selection_result.created_worktrees], ["implementations_task-2"])
            self.assertTrue((repo / "trees" / "implementations_task" / "1").is_dir())
            self.assertTrue((repo / "trees" / "implementations_task" / "2").is_dir())

    def test_plan_selection_with_cmux_new_session_launch_creates_and_targets_next_iteration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true"})
            contexts = engine._discover_projects(mode="trees")
            route = parse_route(
                ["--plan", "implementations/task", "--cmux", "--headless", "--new-session"],
                env={},
            )

            selected = engine._select_plan_projects(route, contexts)

            selection_result = engine.planning_worktree_orchestrator.last_plan_selection_result()
            self.assertEqual([ctx.name for ctx in selected], ["implementations_task-2"])
            self.assertEqual([item.name for item in selection_result.created_worktrees], ["implementations_task-2"])
            self.assertTrue((repo / "trees" / "implementations_task" / "1").is_dir())
            self.assertTrue((repo / "trees" / "implementations_task" / "2").is_dir())
