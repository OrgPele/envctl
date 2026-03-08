"""Visual indicators and formatting helpers for test output."""

from __future__ import annotations

from .colors import TerminalColors


# Visual symbols
CHECK_MARK: str = "✓"
CROSS_MARK: str = "✗"
WARNING: str = "⚠"

# Spinner animation frames
SPINNER_FRAMES: list[str] = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def print_banner(
    text: str,
    colors: TerminalColors | None = None,
    width: int = 80,
) -> str:
    """Format text as a banner with borders.

    Args:
        text: Banner text content.
        colors: TerminalColors instance for styling. If None, uses default.
        width: Total banner width.

    Returns:
        Formatted banner string.
    """
    if colors is None:
        colors = TerminalColors()

    border = "=" * width
    padding = (width - len(text) - 2) // 2
    padded_text = " " * padding + text + " " * (width - padding - len(text) - 2)

    return f"{colors.BOLD}{border}\n {padded_text}\n{border}{colors.NC}"


def format_duration(seconds: float) -> str:
    """Format duration in seconds to human-readable string.

    Args:
        seconds: Duration in seconds.

    Returns:
        Formatted duration string (e.g., "1m 23s", "45s", "2.5s").
    """
    if seconds < 0:
        return "0s"

    if seconds < 1:
        return f"{seconds:.2f}s"

    minutes = int(seconds // 60)
    secs = seconds % 60

    if minutes > 0:
        return f"{minutes}m {secs:.0f}s"

    return f"{secs:.1f}s"
