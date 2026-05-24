from __future__ import annotations

import sys
from typing import Any

from envctl_engine.ui.color_policy import colors_enabled


def action_colors_enabled(runtime: Any) -> bool:
    rt_env = getattr(runtime, "env", {})
    interactive_tty = False
    raw_runtime = getattr(runtime, "raw_runtime", runtime)
    can_interactive_tty = getattr(raw_runtime, "_can_interactive_tty", None)
    if callable(can_interactive_tty):
        try:
            interactive_tty = bool(can_interactive_tty())
        except Exception:
            interactive_tty = False
    return colors_enabled(rt_env, stream=sys.stdout, interactive_tty=interactive_tty)


def colorize_action_text(
    text: str,
    *,
    enabled: bool,
    fg: str | None = None,
    bold: bool = False,
    dim: bool = False,
) -> str:
    if not enabled:
        return text
    palette = {
        "red": "31",
        "green": "32",
        "yellow": "33",
        "blue": "34",
        "magenta": "35",
        "cyan": "36",
        "gray": "90",
    }
    codes: list[str] = []
    if bold:
        codes.append("1")
    if dim:
        codes.append("2")
    if fg is not None:
        code = palette.get(str(fg).strip().lower())
        if code is not None:
            codes.append(code)
    if not codes:
        return text
    return f"\033[{';'.join(codes)}m{text}\033[0m"
