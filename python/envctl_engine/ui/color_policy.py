from __future__ import annotations

import os
import sys
from typing import Mapping, TextIO

from ..shared.parsing import parse_bool


def colors_enabled(
    env: Mapping[str, str] | None = None,
    *,
    stream: TextIO | None = None,
    interactive_tty: bool = False,
) -> bool:
    merged = dict(os.environ)
    if env:
        merged.update(env)

    mode_raw = str(merged.get("ENVCTL_UI_COLOR_MODE", merged.get("ENVCTL_UI_COLOR", "auto"))).strip().lower()
    mode = mode_raw if mode_raw in {"auto", "on", "off"} else "auto"
    if mode == "off":
        return False
    if mode == "on":
        return True

    if parse_bool(merged.get("FORCE_COLOR"), False):
        return True
    if parse_bool(merged.get("CLICOLOR_FORCE"), False):
        return True

    clicolor_raw = str(merged.get("CLICOLOR", "")).strip()
    if clicolor_raw == "0":
        return False

    no_color_raw = merged.get("NO_COLOR")
    no_color = no_color_raw is not None and str(no_color_raw).strip() != ""
    if no_color and not interactive_tty:
        return False

    out = stream or sys.stdout
    is_tty = bool(getattr(out, "isatty", lambda: False)())
    if interactive_tty:
        return True
    return is_tty
