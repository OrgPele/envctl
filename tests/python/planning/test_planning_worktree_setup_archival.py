# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.planning_worktree_setup_test_support import *


class PlanningWorktreeSetupArchivalTests(PlanningWorktreeSetupTestCase):
    def test_plan_zero_target_moves_plan_to_done_when_keep_plan_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            plan_file = repo / "todo" / "plans" / "implementations" / "task.md"
            plan_file.write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime)
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001
            synced, error = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                plan_counts={"implementations/task.md": 0},
                raw_projects=raw_projects,
                keep_plan=False,
            )
            self.assertIsNone(error)
            self.assertEqual(synced, [])
            self.assertFalse(plan_file.exists())
            done_file = repo / "todo" / "done" / "implementations" / "task.md"
            self.assertTrue(done_file.is_file())

    def test_plan_zero_target_reports_blast_and_delete_before_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            plan_file = repo / "todo" / "plans" / "implementations" / "task.md"
            plan_file.write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_UI_SPINNER_MODE": "off"})
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001
            out = StringIO()
            with redirect_stdout(out):
                synced, error = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                    plan_counts={"implementations/task.md": 0},
                    raw_projects=raw_projects,
                    keep_plan=False,
                )

            self.assertIsNone(error)
            self.assertEqual(synced, [])
            self.assertIn("Blasted and deleted 1 worktree(s) for implementations/task.md.", out.getvalue())

    def test_plan_selection_hyperlinks_plan_file_messages_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            plan_file = repo / "todo" / "plans" / "implementations" / "task.md"
            plan_file.write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(
                repo,
                runtime,
                env={"ENVCTL_UI_SPINNER_MODE": "off", "ENVCTL_UI_HYPERLINK_MODE": "on"},
            )
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001
            out = _TtyStringIO()
            with redirect_stdout(out):
                synced, error = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                    plan_counts={"implementations/task.md": 0},
                    raw_projects=raw_projects,
                    keep_plan=False,
                )

            self.assertIsNone(error)
            self.assertEqual(synced, [])
            rendered = out.getvalue()
            self.assertIn("\x1b]8;;file://", rendered)
            visible = strip_ansi(rendered)
            self.assertIn("Blasted and deleted 1 worktree(s) for implementations/task.md.", visible)
            self.assertIn("Moved implementations/task.md to done/implementations/task.md.", visible)

    def test_plan_zero_target_does_not_move_inactive_plan_to_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            plan_file = repo / "todo" / "plans" / "implementations" / "task.md"
            plan_file.write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime)
            synced, error = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                plan_counts={"implementations/task.md": 0},
                raw_projects=[],
                keep_plan=False,
            )

            self.assertIsNone(error)
            self.assertEqual(synced, [])
            self.assertTrue(plan_file.exists())
            self.assertFalse((repo / "todo" / "done" / "implementations" / "task.md").exists())

    def test_plan_zero_target_keeps_plan_when_keep_plan_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            plan_file = repo / "todo" / "plans" / "implementations" / "task.md"
            plan_file.write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime)
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001
            synced, error = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                plan_counts={"implementations/task.md": 0},
                raw_projects=raw_projects,
                keep_plan=True,
            )
            self.assertIsNone(error)
            self.assertEqual(synced, [])
            self.assertTrue(plan_file.exists())
            done_file = repo / "todo" / "done" / "implementations" / "task.md"
            self.assertFalse(done_file.exists())

    def test_plan_zero_target_moves_plan_to_sibling_done_root_for_custom_planning_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            plan_dir = repo / "work" / "plans" / "implementations"
            plan_dir.mkdir(parents=True, exist_ok=True)
            plan_file = plan_dir / "task.md"
            plan_file.write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_PLANNING_DIR": "work/plans"})
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001
            synced, error = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                plan_counts={"implementations/task.md": 0},
                raw_projects=raw_projects,
                keep_plan=False,
            )

            self.assertIsNone(error)
            self.assertEqual(synced, [])
            self.assertFalse(plan_file.exists())
            self.assertTrue((repo / "work" / "done" / "implementations" / "task.md").is_file())

    def test_plan_zero_target_done_move_avoids_overwriting_existing_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            plan_dir = repo / "todo" / "plans" / "implementations"
            plan_dir.mkdir(parents=True, exist_ok=True)
            plan_file = plan_dir / "task.md"
            plan_file.write_text("# task\n", encoding="utf-8")
            done_dir = repo / "todo" / "done" / "implementations"
            done_dir.mkdir(parents=True, exist_ok=True)
            (done_dir / "task.md").write_text("# previous\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime)
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001
            synced, error = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                plan_counts={"implementations/task.md": 0},
                raw_projects=raw_projects,
                keep_plan=False,
            )

            self.assertIsNone(error)
            self.assertEqual(synced, [])
            self.assertTrue((done_dir / "task.md").is_file())
            moved = sorted(done_dir.glob("task-*.md"))
            self.assertEqual(len(moved), 1)
