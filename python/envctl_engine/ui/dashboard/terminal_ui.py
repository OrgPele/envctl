from __future__ import annotations

import sys

from envctl_engine.planning.menu import PlanningSelectionMenu
from envctl_engine.ui.terminal_session import TerminalSession, can_interactive_tty, restore_terminal_after_input


class RuntimeTerminalUI:
    def __init__(self) -> None:
        self._planning_menu = PlanningSelectionMenu()

    @property
    def planning_menu(self) -> PlanningSelectionMenu:
        return self._planning_menu

    def planning_selection(
        self,
        planning_files: list[str],
        selected_counts: dict[str, int],
        existing_counts: dict[str, int],
    ) -> dict[str, int]:
        result = self._planning_menu.run(
            planning_files=planning_files,
            selected_counts=selected_counts,
            existing_counts=existing_counts,
        )
        return result.selected_counts

    @staticmethod
    def read_interactive_command_line(prompt: str, env: dict[str, str]) -> str:
        """Read a command line from interactive TTY with raw termios handling."""
        session = TerminalSession(env)
        return session.read_command_line(prompt)

    @staticmethod
    def restore_terminal_after_input(*, fd: int, original_state: list[int] | None) -> None:
        """Restore terminal state after raw input handling."""
        restore_terminal_after_input(fd=fd, original_state=original_state)

    @staticmethod
    def flush_pending_interactive_input() -> None:
        """Flush pending input from stdin."""
        if not sys.stdin.isatty():
            return
        try:
            fd = sys.stdin.fileno()
        except (OSError, ValueError):
            return
        RuntimeTerminalUI().planning_menu.flush_pending_input(fd=fd)

    @staticmethod
    def _can_interactive_tty() -> bool:
        """Check if interactive TTY is available."""
        return can_interactive_tty()
