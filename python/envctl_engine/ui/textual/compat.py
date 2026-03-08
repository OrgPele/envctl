from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class TextualRunPolicy:
    mouse: bool
    reason: str
    term_program: str


def textual_run_policy(*, screen: str) -> TextualRunPolicy:
    raw_mouse = str(os.environ.get("ENVCTL_UI_TEXTUAL_MOUSE", "")).strip().lower()
    term_program = str(os.environ.get("TERM_PROGRAM", "")).strip()
    if raw_mouse in {"1", "true", "yes", "on"}:
        return TextualRunPolicy(mouse=True, reason="env_override_on", term_program=term_program)
    if raw_mouse in {"0", "false", "no", "off"}:
        return TextualRunPolicy(mouse=False, reason="env_override_off", term_program=term_program)
    if term_program == "Apple_Terminal":
        # Apple Terminal is the only environment where we have repeatable live
        # evidence of Textual selector startup dropping early arrow bursts while
        # still delivering mouse traffic. Disabling mouse support avoids that
        # protocol path for selector-style apps.
        return TextualRunPolicy(
            mouse=False,
            reason=f"apple_terminal_{screen}_compat",
            term_program=term_program,
        )
    return TextualRunPolicy(mouse=True, reason="default", term_program=term_program)


def apply_textual_driver_compat(
    *,
    driver: Any,
    screen: str,
    mouse_enabled: bool,
    disable_focus_reporting: bool,
    emit: Callable[..., None] | None = None,
    selector_id: str | None = None,
) -> None:
    write = getattr(driver, "write", None)
    flush = getattr(driver, "flush", None)
    if not callable(write):
        return
    sequences: list[str] = []
    if not mouse_enabled:
        # Apple Terminal can continue delivering stale mouse protocol traffic
        # even when Textual is launched with mouse=False. Force keyboard-only
        # terminal modes for selector-style apps.
        sequences.extend(
            [
                "\x1b[?1l",
                "\x1b>",
                "\x1b[?1000l",
                "\x1b[?1002l",
                "\x1b[?1003l",
                "\x1b[?1005l",
                "\x1b[?1006l",
                "\x1b[<u",
                "\x1b[?2004l",
            ]
        )
    if disable_focus_reporting:
        sequences.append("\x1b[?1004l")
    if not sequences:
        return
    try:
        write("".join(sequences))
        if callable(flush):
            flush()
        if callable(emit):
            emit(
                "ui.textual.driver_compat",
                component="ui.textual.compat",
                screen=screen,
                selector_id=selector_id,
                mouse_enabled=mouse_enabled,
                disable_focus_reporting=disable_focus_reporting,
                result="ok",
            )
    except Exception as exc:
        if callable(emit):
            emit(
                "ui.textual.driver_compat",
                component="ui.textual.compat",
                screen=screen,
                selector_id=selector_id,
                mouse_enabled=mouse_enabled,
                disable_focus_reporting=disable_focus_reporting,
                result="failed",
                error=type(exc).__name__,
            )
