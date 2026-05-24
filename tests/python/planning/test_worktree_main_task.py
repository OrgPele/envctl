from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from envctl_engine.planning.worktree_main_task import (
    move_plan_to_done,
    next_available_iteration,
    seed_main_task_from_plan,
)


class WorktreeMainTaskTests(unittest.TestCase):
    def test_seed_main_task_copies_plan_with_trailing_newline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "trees" / "feature" / "1"
            plan_path = root / "todo" / "plans" / "feature.md"
            target.mkdir(parents=True)
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text("# Feature", encoding="utf-8")

            seed_main_task_from_plan(target=target, plan_path=plan_path)

            self.assertEqual((target / "MAIN_TASK.md").read_text(encoding="utf-8"), "# Feature\n")

    def test_seed_main_task_ignores_missing_empty_or_invalid_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            target = root / "trees" / "feature" / "1"
            missing_plan = root / "todo" / "plans" / "missing.md"
            empty_plan = root / "todo" / "plans" / "empty.md"
            target.mkdir(parents=True)
            empty_plan.parent.mkdir(parents=True)
            empty_plan.write_text("  \n", encoding="utf-8")

            seed_main_task_from_plan(target=target, plan_path=missing_plan)
            seed_main_task_from_plan(target=target, plan_path=empty_plan)
            seed_main_task_from_plan(target=root / "missing-target", plan_path=empty_plan)

            self.assertFalse((target / "MAIN_TASK.md").exists())

    def test_move_plan_to_done_preserves_relative_area_and_deduplicates_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            planning_root = root / "todo" / "plans"
            done_root = root / "todo" / "done"
            plan = planning_root / "features" / "task.md"
            existing_done = done_root / "features" / "task.md"
            plan.parent.mkdir(parents=True)
            existing_done.parent.mkdir(parents=True)
            plan.write_text("# current\n", encoding="utf-8")
            existing_done.write_text("# old\n", encoding="utf-8")
            fixed_now = datetime(2026, 5, 21, 12, 34, 56, tzinfo=UTC)

            with patch("envctl_engine.planning.worktree_main_task.datetime") as fake_datetime:
                fake_datetime.now.return_value = fixed_now
                move_plan_to_done(
                    plan_file="features/task.md",
                    planning_root=planning_root,
                    planning_done_root=done_root,
                    render_path=lambda *, absolute_path, display_text: display_text,
                    emit_message=lambda _message: None,
                )

            self.assertFalse(plan.exists())
            self.assertEqual(existing_done.read_text(encoding="utf-8"), "# old\n")
            archived = done_root / "features" / "task-20260521123456.md"
            self.assertEqual(archived.read_text(encoding="utf-8"), "# current\n")

    def test_move_plan_to_done_uses_misc_for_root_plan_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            planning_root = root / "todo" / "plans"
            done_root = root / "todo" / "done"
            plan = planning_root / "task.md"
            plan.parent.mkdir(parents=True)
            plan.write_text("# current\n", encoding="utf-8")
            messages: list[str] = []

            move_plan_to_done(
                plan_file="task.md",
                planning_root=planning_root,
                planning_done_root=done_root,
                render_path=lambda *, absolute_path, display_text: display_text,
                emit_message=messages.append,
            )

            self.assertFalse(plan.exists())
            self.assertEqual((done_root / "_misc" / "task.md").read_text(encoding="utf-8"), "# current\n")
            self.assertEqual(messages, ["Moved task.md to done/_misc/task.md."])

    def test_next_available_iteration_fills_first_gap(self) -> None:
        self.assertEqual(next_available_iteration({1, 2, 4}), 3)


if __name__ == "__main__":
    unittest.main()
