from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from envctl_engine.planning.worktree_prompt_selection import prompt_planning_selection


class WorktreePromptSelectionTests(unittest.TestCase):
    def test_prompt_planning_selection_seeds_menu_from_current_existing_counts(self) -> None:
        calls: dict[str, object] = {}

        def choose(**kwargs: object) -> dict[str, int]:
            calls["menu"] = kwargs
            return {"backend/task.md": 1, "frontend/task.md": 2}

        chosen = prompt_planning_selection(
            planning_files=["backend/task.md", "frontend/task.md"],
            raw_projects=[("backend_task-1", Path("/repo/trees/backend_task/1"))],
            run_planning_selection_menu=choose,
        )

        self.assertEqual(chosen, {"backend/task.md": 1, "frontend/task.md": 2})
        menu_call = calls["menu"]
        self.assertEqual(menu_call["existing_counts"], {"backend/task.md": 1, "frontend/task.md": 0})
        self.assertEqual(menu_call["selected_counts"], {"backend/task.md": 1, "frontend/task.md": 0})

    def test_prompt_planning_selection_clamps_invalid_existing_counts(self) -> None:
        calls: dict[str, object] = {}

        def choose(**kwargs: object) -> None:
            calls.update(kwargs)
            return None

        with patch(
            "envctl_engine.planning.worktree_prompt_selection.planning_existing_counts",
            return_value={"backend/task.md": -2, "frontend/task.md": 3},
        ):
            chosen = prompt_planning_selection(
                planning_files=["backend/task.md", "frontend/task.md"],
                raw_projects=[],
                run_planning_selection_menu=choose,
            )

        self.assertIsNone(chosen)
        self.assertEqual(calls["selected_counts"], {"backend/task.md": 0, "frontend/task.md": 3})
