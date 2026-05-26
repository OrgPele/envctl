from __future__ import annotations

import os
import select
import sys
from typing import Any, Mapping

from envctl_engine.ui.backend_selector_debug import debug_tty_group_enabled


def selector_subprocess_enabled(runtime: Any) -> bool:
    raw = ""
    env = getattr(runtime, "env", None)
    if isinstance(env, Mapping):
        raw = str(env.get("ENVCTL_UI_TEXTUAL_SELECTOR_SUBPROCESS", "")).strip().lower()
    if not raw:
        raw = str(os.environ.get("ENVCTL_UI_TEXTUAL_SELECTOR_SUBPROCESS", "")).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return str(os.environ.get("TERM_PROGRAM", "")).strip() == "Apple_Terminal"


def flush_pending_input(runtime: Any) -> None:
    flush = getattr(runtime, "_flush_pending_interactive_input", None)
    if callable(flush):
        flush()


def selector_preflight_flag(*, runtime: Any, key: str, default: bool) -> bool:
    raw = ""
    env = getattr(runtime, "env", None)
    if isinstance(env, Mapping):
        raw = str(env.get(key, "")).strip().lower()
    if not raw:
        raw = str(os.environ.get(key, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def selector_launch_character_mode_enabled() -> bool:
    raw = str(os.environ.get("ENVCTL_UI_SELECTOR_CHARACTER_MODE", "")).strip().lower()
    if not raw:
        return False
    return raw in {"1", "true", "yes", "on"}


def preserve_output_tty_state_for_selector(runtime: Any) -> bool:
    if not debug_tty_group_enabled(runtime, "termios"):
        return True
    if str(os.environ.get("TERM_PROGRAM", "")).strip() != "Apple_Terminal":
        return False
    if not selector_subprocess_enabled(runtime):
        return False
    return True


def emit_selector_preflight(emit: Any, **payload: object) -> None:
    if callable(emit):
        emit("ui.selector.preflight", component="ui.backend", **payload)


def stdin_tty_fd() -> int | None:
    if not sys.stdin.isatty():
        return None
    try:
        return sys.stdin.fileno()
    except (OSError, ValueError):
        return None


def stdout_tty_fd() -> int | None:
    stream = getattr(sys, "stdout", None)
    if stream is None:
        return None
    try:
        fd = int(stream.fileno())
    except (OSError, ValueError, TypeError):
        return None
    try:
        if not os.isatty(fd):
            return None
    except Exception:
        return None
    return fd


def normalize_stdin_line_mode(fd: int) -> bool:
    try:
        import termios

        state = termios.tcgetattr(fd)
        if len(state) > 3 and (int(state[3]) & int(termios.ICANON)) == 0:
            return True
    except Exception:
        pass
    try:
        from .terminal_session import _ensure_tty_line_mode  # noqa: PLC2701

        _ensure_tty_line_mode(fd=fd)
        return True
    except Exception:
        return False


def drain_stdin_escape_tail(*, fd: int, max_window_seconds: float, max_bytes: int) -> int:
    if max_window_seconds <= 0 or max_bytes <= 0:
        return 0
    max_polls = max(1, int(max_window_seconds * 1000))
    polls = 0
    drained = 0
    while drained < max_bytes:
        if polls >= max_polls:
            break
        polls += 1
        try:
            ready, _, _ = select.select([fd], [], [], 0)
        except Exception:
            break
        if not ready:
            break
        try:
            chunk = os.read(fd, 1)
        except Exception:
            break
        if not chunk:
            break
        drained += len(chunk)
    return drained


_drain_stdin_escape_tail = drain_stdin_escape_tail
_emit_selector_preflight = emit_selector_preflight
_flush_pending_input = flush_pending_input
_normalize_stdin_line_mode = normalize_stdin_line_mode
_preserve_output_tty_state_for_selector = preserve_output_tty_state_for_selector
_selector_launch_character_mode_enabled = selector_launch_character_mode_enabled
_selector_preflight_flag = selector_preflight_flag
_selector_subprocess_enabled = selector_subprocess_enabled
_stdin_tty_fd = stdin_tty_fd
_stdout_tty_fd = stdout_tty_fd
