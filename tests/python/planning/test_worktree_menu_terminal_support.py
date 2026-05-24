from __future__ import annotations

import unittest
from typing import Any

from envctl_engine.planning.worktree_menu_terminal_support import (
    planning_menu_apply_key,
    read_planning_menu_key,
    render_planning_selection_menu,
    terminal_size,
)


class _PlanningMenu:
    def __init__(self) -> None:
        self.render_kwargs: dict[str, Any] | None = None
        self.apply_kwargs: dict[str, Any] | None = None

    def render(self, **kwargs: Any) -> str:
        self.render_kwargs = dict(kwargs)
        return "rendered-menu"

    def terminal_size(self) -> tuple[int, int]:
        return (100, 32)

    def read_key(self, *, fd: int, selector: Any) -> str:
        return f"key:{fd}:{selector.__name__}"

    def apply_key(self, **kwargs: Any) -> tuple[int, str, str]:
        self.apply_kwargs = dict(kwargs)
        return (1, "continue", "message")


class _TerminalUI:
    def __init__(self) -> None:
        self.planning_menu = _PlanningMenu()


def _selector() -> object:
    return object()


class WorktreeMenuTerminalSupportTests(unittest.TestCase):
    def test_render_and_apply_delegate_to_runtime_terminal_planning_menu(self) -> None:
        terminal_ui = _TerminalUI()
        planning_files = ["one.md", "two.md"]
        selected_counts = {"one.md": 1}
        existing_counts = {"two.md": 2}

        self.assertEqual(
            render_planning_selection_menu(
                terminal_ui,  # type: ignore[arg-type]
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
                cursor=1,
                message="Choose",
                terminal_width=120,
                terminal_height=40,
            ),
            "rendered-menu",
        )
        self.assertEqual(
            terminal_ui.planning_menu.render_kwargs,
            {
                "planning_files": planning_files,
                "selected_counts": selected_counts,
                "existing_counts": existing_counts,
                "cursor": 1,
                "message": "Choose",
                "terminal_width": 120,
                "terminal_height": 40,
            },
        )

        self.assertEqual(
            planning_menu_apply_key(
                terminal_ui,  # type: ignore[arg-type]
                key="down",
                cursor=0,
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            ),
            (1, "continue", "message"),
        )
        self.assertEqual(
            terminal_ui.planning_menu.apply_kwargs,
            {
                "key": "down",
                "cursor": 0,
                "planning_files": planning_files,
                "selected_counts": selected_counts,
                "existing_counts": existing_counts,
            },
        )

    def test_terminal_size_and_key_read_delegate_to_terminal_ui(self) -> None:
        terminal_ui = _TerminalUI()

        self.assertEqual(terminal_size(terminal_ui), (100, 32))  # type: ignore[arg-type]
        self.assertEqual(
            read_planning_menu_key(terminal_ui, fd=7, selector=_selector),  # type: ignore[arg-type]
            "key:7:_selector",
        )


if __name__ == "__main__":
    unittest.main()
