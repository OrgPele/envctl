"""Handle output modes for interactive and batch environments."""

from __future__ import annotations

import re
import sys
from typing import Any, Callable

from .colors import TerminalColors


class OutputModeHandler:
    """Manages output behavior based on interactive vs batch mode."""

    batch: bool
    interactive: bool
    emit_callback: Callable[[str, dict[str, Any]], None] | None
    colors: TerminalColors

    def __init__(
        self,
        interactive: bool | None = None,
        batch: bool | None = None,
        emit_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        """Initialize output mode handler.

        Args:
            interactive: Force interactive mode. If None, auto-detect.
            batch: Force batch mode. If None, auto-detect from TTY.
            emit_callback: Optional callback for emitting events to dashboard.
        """
        # Auto-detect batch mode if not explicitly set
        if batch is None:
            batch = not sys.stdout.isatty()

        self.batch = batch
        self.interactive = interactive if interactive is not None else not batch
        self.emit_callback = emit_callback
        self.colors = self._get_colors()

    def print(self, message: str, color: str | None = None) -> None:
        """Print message with appropriate mode handling.

        Args:
            message: Message to print.
            color: Optional color code from TerminalColors.
        """
        if color is None:
            color = ""

        # In batch mode, strip colors
        if self.batch:
            # Remove ANSI codes
            ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
            message = ansi_escape.sub("", message)

        print(message)

        # Emit to dashboard in interactive mode
        if self.interactive and self.emit_callback:
            self.emit_callback("output.print", {"message": message, "color": color})

    def should_show_spinner(self) -> bool:
        """Determine if spinner should be shown.

        Returns:
            True if spinner should be displayed (interactive mode).
        """
        return self.interactive and sys.stdout.isatty()

    def should_stream_output(self) -> bool:
        """Determine if output should stream in real-time.

        Returns:
            True if output should stream (interactive mode).
        """
        return self.interactive

    def get_colors(self) -> TerminalColors:
        """Get appropriate colors for current mode.

        Returns:
            TerminalColors instance (disabled in batch mode).
        """
        return self.colors

    def _get_colors(self) -> TerminalColors:
        """Get colors based on mode.

        Returns:
            TerminalColors with colors enabled/disabled appropriately.
        """
        if self.batch:
            return self._no_colors()
        return TerminalColors.get_colors(enabled=True)

    @staticmethod
    def _no_colors() -> TerminalColors:
        """Create TerminalColors with all colors disabled.

        Returns:
            TerminalColors instance with empty color codes.
        """
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
