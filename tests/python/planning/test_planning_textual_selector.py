from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime


class PlanningTextualSelectorTests(unittest.TestCase):
    def _engine(self) -> PythonEngineRuntime:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        root = Path(tmpdir.name)
        repo = root / "repo"
        runtime = root / "runtime"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(runtime),
            }
        )
        return PythonEngineRuntime(config, env={})

    def test_run_planning_selection_menu_uses_textual_selector(self) -> None:
        engine = self._engine()
        planning_files = ["backend/task-a.md"]
        selected_counts = {"backend/task-a.md": 1}
        existing_counts = {"backend/task-a.md": 0}

        with (
            patch.object(engine, "_flush_pending_interactive_input") as flush_mock,
            patch(
                "envctl_engine.planning.worktree_domain.select_planning_counts_textual",
                return_value={"backend/task-a.md": 2},
            ) as selector_mock,
        ):
            chosen = engine._run_planning_selection_menu(
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            )

        self.assertEqual(chosen, {"backend/task-a.md": 2})
        flush_mock.assert_called_once_with()
        selector_mock.assert_called_once()

    def test_run_planning_selection_menu_returns_none_when_cancelled(self) -> None:
        engine = self._engine()

        with patch(
            "envctl_engine.planning.worktree_domain.select_planning_counts_textual",
            return_value=None,
        ):
            chosen = engine._run_planning_selection_menu(
                planning_files=["backend/task-a.md"],
                selected_counts={"backend/task-a.md": 1},
                existing_counts={"backend/task-a.md": 0},
            )

        self.assertIsNone(chosen)

    def test_run_planning_selection_menu_preserves_zero_scale_when_existing_worktrees_present(self) -> None:
        engine = self._engine()

        with patch(
            "envctl_engine.planning.worktree_domain.select_planning_counts_textual",
            return_value={"backend/task-a.md": 0},
        ):
            chosen = engine._run_planning_selection_menu(
                planning_files=["backend/task-a.md"],
                selected_counts={"backend/task-a.md": 1},
                existing_counts={"backend/task-a.md": 1},
            )

        self.assertEqual(chosen, {"backend/task-a.md": 0})

    def test_run_planning_selection_menu_restores_terminal_state_after_selector(self) -> None:
        engine = self._engine()

        with (
            patch(
                "envctl_engine.planning.worktree_domain.select_planning_counts_textual",
                return_value={"backend/task-a.md": 1},
            ),
            patch("envctl_engine.ui.terminal_session.normalize_standard_tty_state") as normalize_mock,
            patch("envctl_engine.ui.terminal_session._reset_terminal_escape_modes") as reset_mock,
        ):
            chosen = engine._run_planning_selection_menu(
                planning_files=["backend/task-a.md"],
                selected_counts={"backend/task-a.md": 1},
                existing_counts={"backend/task-a.md": 0},
            )

        self.assertEqual(chosen, {"backend/task-a.md": 1})
        normalize_mock.assert_called_once()
        reset_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
