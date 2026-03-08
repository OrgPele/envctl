from __future__ import annotations

import os
from typing import Any, Callable, cast

from ..state.models import RunState
from .command_loop import run_dashboard_command_loop
from .terminal_session import normalize_standard_tty_state


def _preserve_output_tty_state_for_dashboard() -> bool:
    return str(os.environ.get("TERM_PROGRAM", "")).strip() == "Apple_Terminal"


def _tty_termios_group_enabled() -> bool:
    raw_orch = str(os.environ.get("ENVCTL_DEBUG_PLAN_ORCH_GROUP", "")).strip().lower()
    orch_groups = {
        token.strip()
        for token in raw_orch.replace("+", ",").split(",")
        if token.strip()
    }
    if orch_groups and "tty" not in orch_groups:
        return True
    raw_tty = str(os.environ.get("ENVCTL_DEBUG_PLAN_TTY_GROUP", "")).strip().lower()
    tty_groups = {
        token.strip()
        for token in raw_tty.replace("+", ",").split(",")
        if token.strip()
    }
    if not tty_groups:
        return True
    return "termios" in tty_groups


def run_legacy_dashboard_loop(
    *,
    state: RunState,
    runtime: Any,
    fallback_handler: Callable[[str, RunState, object], tuple[bool, RunState]] | None = None,
    sanitize: Callable[[str], str] | None = None,
) -> int:
    tty_termios_enabled = _tty_termios_group_enabled()
    emit = getattr(runtime, "_emit", None)
    if callable(emit):
        emit(
            "startup.debug_tty_group",
            component="ui.dashboard_loop",
            group="termios",
            action="normalize_standard_tty_state",
            enabled=tty_termios_enabled,
            detail="dashboard_loop_entry",
        )
    if tty_termios_enabled and not _preserve_output_tty_state_for_dashboard():
        normalize_standard_tty_state(emit=emit, component="ui.dashboard_loop")
    runtime_command_handler = getattr(runtime, "_run_interactive_command", None)

    def handle_command(raw: str, current_state: RunState, runtime_obj: object) -> tuple[bool, RunState]:
        if callable(runtime_command_handler):
            return cast(tuple[bool, RunState], runtime_command_handler(raw, current_state))
        if callable(fallback_handler):
            return fallback_handler(raw, current_state, runtime_obj)
        return True, current_state

    return run_dashboard_command_loop(
        state=state,
        runtime=runtime,
        handle_command=handle_command,
        sanitize=sanitize,
        can_interactive_tty=getattr(runtime, "_can_interactive_tty", None),
        read_command_line=getattr(runtime, "_read_interactive_command_line", None),
        flush_pending_input=getattr(runtime, "_flush_pending_interactive_input", None),
    )
