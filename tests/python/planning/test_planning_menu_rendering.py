from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import termios
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.planning.menu import PlanningSelectionMenu


class PlanningMenuRenderingTests(unittest.TestCase):
    def test_render_is_deterministic_for_long_lists(self) -> None:
        menu = PlanningSelectionMenu()
        planning_files = [f"features/task-{i}.md" for i in range(1, 40)]
        selected = {name: 1 if i % 3 == 0 else 0 for i, name in enumerate(planning_files)}
        existing = {name: 0 for name in planning_files}

        frame_a = menu.render(
            planning_files=planning_files,
            selected_counts=selected,
            existing_counts=existing,
            cursor=10,
            message="",
            terminal_width=80,
            terminal_height=20,
        )
        frame_b = menu.render(
            planning_files=planning_files,
            selected_counts=selected,
            existing_counts=existing,
            cursor=10,
            message="",
            terminal_width=80,
            terminal_height=20,
        )
        self.assertEqual(frame_a, frame_b)

    def test_apply_key_navigation_and_toggle(self) -> None:
        menu = PlanningSelectionMenu()
        planning_files = ["a.md", "b.md", "c.md"]
        selected = {"a.md": 0, "b.md": 0, "c.md": 0}
        existing = {"a.md": 1, "b.md": 0, "c.md": 2}

        cursor, action, _ = menu.apply_key(
            key="down",
            cursor=0,
            planning_files=planning_files,
            selected_counts=selected,
            existing_counts=existing,
        )
        self.assertEqual((cursor, action), (1, "continue"))

        cursor, action, _ = menu.apply_key(
            key="space",
            cursor=0,
            planning_files=planning_files,
            selected_counts=selected,
            existing_counts=existing,
        )
        self.assertEqual(action, "continue")
        self.assertEqual(selected["a.md"], 1)

        _cursor, action, _ = menu.apply_key(
            key="enter",
            cursor=cursor,
            planning_files=planning_files,
            selected_counts=selected,
            existing_counts=existing,
        )
        self.assertEqual(action, "submit")

    def test_run_restores_terminal_mode_with_fallback_when_drain_restore_fails(self) -> None:
        menu = PlanningSelectionMenu()
        planning_files = ["a.md"]
        selected = {"a.md": 0}
        existing = {"a.md": 0}

        original_state = [0, 0, 0, 0, 0, 0]
        restore_calls: list[tuple[int, list[int]]] = []

        def fake_tcsetattr(_fd: int, when: int, state: list[int]) -> None:
            restore_calls.append((when, state))
            if len(restore_calls) == 1:
                raise termios.error("interrupted")

        with (
            patch("sys.stdin.fileno", return_value=7),
            patch("termios.tcgetattr", return_value=original_state),
            patch("termios.tcsetattr", side_effect=fake_tcsetattr),
            patch("tty.setraw"),
            patch("os.read", return_value=b"q"),
            patch.object(PlanningSelectionMenu, "flush_pending_input"),
            patch.object(PlanningSelectionMenu, "_prompt_toolkit_enabled", return_value=False),
            redirect_stdout(StringIO()),
        ):
            result = menu.run(
                planning_files=planning_files,
                selected_counts=selected,
                existing_counts=existing,
            )

        self.assertTrue(result.cancelled)
        self.assertGreaterEqual(len(restore_calls), 2)
        self.assertEqual(restore_calls[0][0], termios.TCSADRAIN)
        self.assertEqual(restore_calls[1][0], termios.TCSAFLUSH)

    def test_run_flushes_pending_input_on_exit(self) -> None:
        menu = PlanningSelectionMenu()
        planning_files = ["a.md"]
        selected = {"a.md": 1}
        existing = {"a.md": 0}

        with (
            patch("sys.stdin.fileno", return_value=7),
            patch("termios.tcgetattr", return_value=[0, 0, 0, 0, 0, 0]),
            patch("termios.tcsetattr"),
            patch("tty.setraw"),
            patch("os.read", return_value=b"\n"),
            patch.object(PlanningSelectionMenu, "flush_pending_input") as flush_mock,
            patch.object(PlanningSelectionMenu, "_prompt_toolkit_enabled", return_value=False),
            redirect_stdout(StringIO()),
        ):
            result = menu.run(
                planning_files=planning_files,
                selected_counts=selected,
                existing_counts=existing,
            )

        self.assertFalse(result.cancelled)
        self.assertEqual(result.selected_counts, {"a.md": 1})
        self.assertGreaterEqual(flush_mock.call_count, 2)

    def test_run_submit_preserves_zero_counts_when_existing_worktrees_present(self) -> None:
        menu = PlanningSelectionMenu()
        planning_files = ["a.md"]
        selected = {"a.md": 1}
        existing = {"a.md": 1}

        with (
            patch("sys.stdin.fileno", return_value=7),
            patch("termios.tcgetattr", return_value=[0, 0, 0, 0, 0, 0]),
            patch("termios.tcsetattr"),
            patch("tty.setraw"),
            patch("os.read", side_effect=[b"x", b"\n"]),
            patch.object(PlanningSelectionMenu, "flush_pending_input"),
            patch.object(PlanningSelectionMenu, "_prompt_toolkit_enabled", return_value=False),
            redirect_stdout(StringIO()),
        ):
            result = menu.run(
                planning_files=planning_files,
                selected_counts=selected,
                existing_counts=existing,
            )

        self.assertFalse(result.cancelled)
        self.assertEqual(result.selected_counts, {"a.md": 0})

    def test_ctrl_c_is_treated_as_cancel(self) -> None:
        menu = PlanningSelectionMenu()
        planning_files = ["a.md"]
        selected = {"a.md": 1}
        existing = {"a.md": 0}

        with (
            patch("sys.stdin.fileno", return_value=7),
            patch("termios.tcgetattr", return_value=[0, 0, 0, 0, 0, 0]),
            patch("termios.tcsetattr"),
            patch("tty.setraw"),
            patch("os.read", return_value=b"\x03"),
            patch.object(PlanningSelectionMenu, "flush_pending_input"),
            patch.object(PlanningSelectionMenu, "_prompt_toolkit_enabled", return_value=False),
            redirect_stdout(StringIO()),
        ):
            result = menu.run(
                planning_files=planning_files,
                selected_counts=selected,
                existing_counts=existing,
            )

        self.assertTrue(result.cancelled)

    def test_run_uses_prompt_toolkit_path_when_enabled(self) -> None:
        menu = PlanningSelectionMenu()
        planning_files = ["a.md"]
        selected = {"a.md": 1}
        existing = {"a.md": 0}
        sentinel = PlanningSelectionMenu().run

        with (
            patch.object(PlanningSelectionMenu, "_prompt_toolkit_enabled", return_value=True),
            patch.object(PlanningSelectionMenu, "_run_prompt_toolkit", return_value=sentinel),
        ):
            result = menu.run(
                planning_files=planning_files,
                selected_counts=selected,
                existing_counts=existing,
            )

        self.assertIs(result, sentinel)


if __name__ == "__main__":
    unittest.main()
