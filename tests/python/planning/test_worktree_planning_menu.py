from __future__ import annotations

import unittest
from unittest.mock import patch

from envctl_engine.planning.worktree_planning_menu import run_planning_selection_menu


class WorktreePlanningMenuTests(unittest.TestCase):
    def test_run_planning_selection_menu_flushes_input_and_normalizes_counts(self) -> None:
        flush_calls: list[bool] = []
        emit_calls: list[tuple[str, dict[str, object]]] = []

        with (
            patch("envctl_engine.ui.terminal_session.normalize_standard_tty_state") as normalize_mock,
            patch("envctl_engine.ui.terminal_session._reset_terminal_escape_modes") as reset_mock,
        ):
            chosen = run_planning_selection_menu(
                planning_files=["backend/task.md"],
                selected_counts={"backend/task.md": 1},
                existing_counts={"backend/task.md": 0},
                flush_pending_interactive_input=lambda: flush_calls.append(True),
                emit=lambda event, **payload: emit_calls.append((event, payload)),
                select_planning_counts=lambda **_kwargs: {"backend/task.md": "2"},
            )

        self.assertEqual(chosen, {"backend/task.md": 2})
        self.assertEqual(flush_calls, [True])
        normalize_mock.assert_called_once()
        reset_mock.assert_called_once()

    def test_run_planning_selection_menu_returns_none_for_cancel_or_invalid_payload(self) -> None:
        self.assertIsNone(
            run_planning_selection_menu(
                planning_files=["backend/task.md"],
                selected_counts={"backend/task.md": 1},
                existing_counts={"backend/task.md": 0},
                flush_pending_interactive_input=lambda: None,
                emit=None,
                select_planning_counts=lambda **_kwargs: None,
            )
        )
        self.assertIsNone(
            run_planning_selection_menu(
                planning_files=["backend/task.md"],
                selected_counts={"backend/task.md": 1},
                existing_counts={"backend/task.md": 0},
                flush_pending_interactive_input=lambda: None,
                emit=None,
                select_planning_counts=lambda **_kwargs: ["backend/task.md"],
            )
        )

    def test_run_planning_selection_menu_falls_back_to_positive_selected_counts_on_exception(self) -> None:
        chosen = run_planning_selection_menu(
            planning_files=["backend/task.md", "frontend/task.md"],
            selected_counts={"backend/task.md": 2, "frontend/task.md": 0},
            existing_counts={"backend/task.md": 0, "frontend/task.md": 1},
            flush_pending_interactive_input=lambda: None,
            emit=None,
            select_planning_counts=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("no tty")),
        )

        self.assertEqual(chosen, {"backend/task.md": 2})


if __name__ == "__main__":
    unittest.main()
