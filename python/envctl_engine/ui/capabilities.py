from __future__ import annotations

import importlib.util
import os
from collections.abc import Mapping


def textual_importable() -> bool:
    try:
        __import__("textual")
    except Exception:
        return False
    return True


def prompt_toolkit_disabled(env: Mapping[str, str]) -> bool:
    raw = env.get("ENVCTL_UI_PROMPT_TOOLKIT")
    if raw is None:
        raw = os.environ.get("ENVCTL_UI_PROMPT_TOOLKIT")
    if raw is None:
        return False
    return str(raw).strip().lower() in {"0", "false", "no", "off"}


def prompt_toolkit_selector_enabled(env: Mapping[str, str]) -> bool:
    from envctl_engine.ui.terminal_session import can_interactive_tty, prompt_toolkit_available

    backend_pref = (
        str(env.get("ENVCTL_UI_SELECTOR_BACKEND", os.environ.get("ENVCTL_UI_SELECTOR_BACKEND", ""))).strip().lower()
    )
    if backend_pref in {"textual", "tui"}:
        return False
    if backend_pref in {"prompt_toolkit", "prompt-toolkit", "ptk"}:
        return can_interactive_tty() and prompt_toolkit_available()
    raw = env.get("ENVCTL_UI_PROMPT_TOOLKIT")
    if raw is None:
        raw = os.environ.get("ENVCTL_UI_PROMPT_TOOLKIT")
    if raw is not None:
        normalized = str(raw).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return can_interactive_tty() and prompt_toolkit_available()
        if normalized in {"0", "false", "no", "off"}:
            return False
    return can_interactive_tty() and prompt_toolkit_available()


def interactive_tty_available() -> bool:
    from envctl_engine.ui.terminal_session import can_interactive_tty

    return can_interactive_tty()


def prompt_toolkit_available() -> bool:
    return importlib.util.find_spec("prompt_toolkit") is not None
