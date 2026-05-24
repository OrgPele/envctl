from __future__ import annotations

from typing import Callable

from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI


def render_planning_selection_menu(
    terminal_ui: RuntimeTerminalUI,
    *,
    planning_files: list[str],
    selected_counts: dict[str, int],
    existing_counts: dict[str, int],
    cursor: int,
    message: str,
    terminal_width: int | None = None,
    terminal_height: int | None = None,
) -> str:
    return terminal_ui.planning_menu.render(
        planning_files=planning_files,
        selected_counts=selected_counts,
        existing_counts=existing_counts,
        cursor=cursor,
        message=message,
        terminal_width=terminal_width,
        terminal_height=terminal_height,
    )


def terminal_size(terminal_ui: RuntimeTerminalUI) -> tuple[int, int]:
    return terminal_ui.planning_menu.terminal_size()


def truncate_text(value: str, max_len: int) -> str:
    return RuntimeTerminalUI().planning_menu.truncate_text(value, max_len)


def to_terminal_lines(frame: str) -> str:
    return RuntimeTerminalUI().planning_menu.to_terminal_lines(frame)


def read_planning_menu_key(terminal_ui: RuntimeTerminalUI, *, fd: int, selector: Callable[..., object]) -> str:
    return terminal_ui.planning_menu.read_key(fd=fd, selector=selector)


def read_planning_menu_escape_sequence(
    *,
    fd: int,
    selector: Callable[..., object],
    timeout: float,
    max_bytes: int,
) -> bytes:
    return RuntimeTerminalUI().planning_menu.read_escape_sequence(
        fd=fd,
        selector=selector,
        timeout=timeout,
        max_bytes=max_bytes,
    )


def decode_planning_menu_escape(sequence: bytes) -> str | None:
    return RuntimeTerminalUI().planning_menu.decode_escape(sequence)


def planning_menu_apply_key(
    terminal_ui: RuntimeTerminalUI,
    *,
    key: str,
    cursor: int,
    planning_files: list[str],
    selected_counts: dict[str, int],
    existing_counts: dict[str, int],
) -> tuple[int, str, str]:
    return terminal_ui.planning_menu.apply_key(
        key=key,
        cursor=cursor,
        planning_files=planning_files,
        selected_counts=selected_counts,
        existing_counts=existing_counts,
    )
