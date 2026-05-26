from __future__ import annotations

import unittest

from envctl_engine.ui.textual.screens.planning_selector_model import PlanningSelectionModel


class PlanningSelectionModelTests(unittest.TestCase):
    def test_model_normalizes_counts_and_builds_render_entries(self) -> None:
        model = PlanningSelectionModel.from_counts(
            planning_files=["backend/task-a.md", "frontend/task-b.md"],
            selected_counts={"backend/task-a.md": 2, "frontend/task-b.md": -5},
            existing_counts={"backend/task-a.md": 1, "frontend/task-b.md": 0},
        )

        self.assertEqual(
            [entry.text for entry in model.render_entries()],
            ["● [2x] backend/task-a.md (existing 1x)", "○ [0x] frontend/task-b.md"],
        )
        self.assertEqual(model.status_text(), "1 selected visible • 1 selected total • 2 visible")
        self.assertTrue(model.run_enabled())

    def test_toggle_uses_existing_count_as_default_and_result_preserves_existing_rows(self) -> None:
        model = PlanningSelectionModel.from_counts(
            planning_files=["backend/task-a.md", "frontend/task-b.md"],
            selected_counts={"backend/task-a.md": 0, "frontend/task-b.md": 0},
            existing_counts={"backend/task-a.md": 3, "frontend/task-b.md": 0},
        )

        self.assertEqual(model.toggle_model_index(0).count, 3)
        self.assertEqual(model.toggle_model_index(0).count, 0)
        self.assertEqual(model.result(), {"backend/task-a.md": 0, "frontend/task-b.md": 0})

    def test_filter_and_result_policy_ignore_unselected_rows_without_existing_worktrees(self) -> None:
        model = PlanningSelectionModel.from_counts(
            planning_files=["backend/task-a.md", "frontend/task-b.md"],
            selected_counts={"backend/task-a.md": 1, "frontend/task-b.md": 0},
            existing_counts={},
        )

        query = model.apply_filter("FRONT")

        self.assertEqual(query, "front")
        self.assertEqual([entry.plan_file for entry in model.render_entries()], ["frontend/task-b.md"])
        self.assertEqual(model.status_text(), "0 selected visible • 1 selected total • 1 visible")
        self.assertEqual(model.result(), {"backend/task-a.md": 1})


if __name__ == "__main__":
    unittest.main()
