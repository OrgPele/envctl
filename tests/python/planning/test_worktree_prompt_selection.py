from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

from envctl_engine.planning.worktree_prompt_selection import prompt_planning_selection


class WorktreePromptSelectionTests(unittest.TestCase):
    def test_prompt_planning_selection_seeds_menu_from_existing_counts_and_memory(self) -> None:
        calls: dict[str, object] = {}

        def choose(**kwargs: object) -> dict[str, int]:
            calls["menu"] = kwargs
            return {"backend/task.md": 1, "frontend/task.md": 2}

        chosen = prompt_planning_selection(
            planning_files=["backend/task.md", "frontend/task.md"],
            raw_projects=[("backend_task-1", Path("/repo/trees/backend_task/1"))],
            initial_plan_selected_counts=lambda **kwargs: {
                "backend/task.md": kwargs["existing_counts"]["backend/task.md"],
                "frontend/task.md": 2,
            },
            run_planning_selection_menu=choose,
            save_plan_selection_memory=self._unexpected,
            persist_memory=False,
        )

        self.assertEqual(chosen, {"backend/task.md": 1, "frontend/task.md": 2})
        menu_call = calls["menu"]
        self.assertEqual(menu_call["existing_counts"], {"backend/task.md": 1, "frontend/task.md": 0})
        self.assertEqual(menu_call["selected_counts"], {"backend/task.md": 1, "frontend/task.md": 2})

    def test_prompt_planning_selection_persists_chosen_counts_when_enabled(self) -> None:
        saved: list[dict[str, int]] = []

        chosen = prompt_planning_selection(
            planning_files=["backend/task.md"],
            raw_projects=[],
            persist_memory=True,
            initial_plan_selected_counts=lambda **_kwargs: {"backend/task.md": 1},
            run_planning_selection_menu=lambda **_kwargs: {"backend/task.md": 3},
            save_plan_selection_memory=saved.append,
        )

        self.assertEqual(chosen, {"backend/task.md": 3})
        self.assertEqual(saved, [{"backend/task.md": 3}])

    def test_prompt_planning_selection_skips_memory_for_cancel_empty_or_dry_run(self) -> None:
        for persist_memory, menu_result in [(True, None), (True, {}), (False, {"backend/task.md": 1})]:
            with self.subTest(persist_memory=persist_memory, menu_result=menu_result):
                saved: list[dict[str, int]] = []

                chosen = prompt_planning_selection(
                    planning_files=["backend/task.md"],
                    raw_projects=[],
                    persist_memory=persist_memory,
                    initial_plan_selected_counts=lambda **_kwargs: {"backend/task.md": 1},
                    run_planning_selection_menu=lambda **_kwargs: menu_result,
                    save_plan_selection_memory=saved.append,
                )

                self.assertEqual(chosen, menu_result)
                self.assertEqual(saved, [])

    def _unexpected(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("callback should not be called")
