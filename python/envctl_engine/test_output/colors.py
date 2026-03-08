"""ANSI color codes and terminal color utilities."""

from __future__ import annotations

import sys
from dataclasses import dataclass


def is_tty() -> bool:
    """Detect if output is a TTY (not piped)."""
    return sys.stdout.isatty()


@dataclass(slots=True, frozen=True)
class TerminalColors:
    """ANSI color codes for terminal output."""

    RED: str = "\033[0;31m"
    GREEN: str = "\033[0;32m"
    YELLOW: str = "\033[0;33m"
    BLUE: str = "\033[0;34m"
    CYAN: str = "\033[0;36m"
    MAGENTA: str = "\033[0;35m"
    WHITE: str = "\033[0;37m"
    GRAY: str = "\033[0;90m"
    BOLD: str = "\033[1m"
    NC: str = "\033[0m"  # No Color (reset)

    @classmethod
    def get_colors(cls, enabled: bool | None = None) -> TerminalColors:
        """Get color codes, optionally disabled if not a TTY.

        Args:
            enabled: If None, auto-detect TTY. If True/False, force enable/disable.

        Returns:
            TerminalColors instance with codes or empty strings.
        """
        if enabled is None:
            enabled = is_tty()

        if not enabled:
            return TerminalColors(
                RED="",
                GREEN="",
                YELLOW="",
                BLUE="",
                CYAN="",
                MAGENTA="",
                WHITE="",
                GRAY="",
                BOLD="",
                NC="",
            )
        return cls()
