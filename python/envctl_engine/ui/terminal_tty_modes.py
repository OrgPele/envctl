from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import os
import subprocess
import sys
import termios
from typing import Any, cast


def restore_terminal_after_input(
    *, fd: int, original_state: list[int] | None, emit: Callable[..., None] | None = None
) -> None:
    if original_state is not None:
        try:
            # Preserve unread bytes so rapid follow-up keystrokes survive the
            # dashboard-command -> selector handoff instead of being discarded.
            termios.tcsetattr(fd, termios.TCSADRAIN, cast(Any, original_state))
            _clear_pendin(fd=fd, emit=emit, component="ui.terminal_session")
            if callable(emit):
                emit("ui.tty.transition", component="ui.terminal_session", action="restore", method="tcsetattr")
            return
        except Exception:
            pass
    try:
        subprocess.run(
            ["stty", "sane"],
            stdin=fd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if callable(emit):
            emit("ui.tty.transition", component="ui.terminal_session", action="restore", method="stty_sane")
    except Exception:
        return
    _clear_standard_tty_pendin(emit=emit, component="ui.terminal_session")


def _set_tty_character_mode(*, fd: int, original_state: list[Any]) -> bool:
    updated = list(original_state)
    if len(updated) <= 6:
        return False
    try:
        updated[3] = int(updated[3]) & ~int(termios.ICANON | termios.ECHO)
        cc = list(updated[6])
        if len(cc) <= max(termios.VMIN, termios.VTIME):
            return False
        cc[termios.VMIN] = 1
        cc[termios.VTIME] = 0
        updated[6] = cc
        termios.tcsetattr(fd, termios.TCSADRAIN, cast(Any, updated))
        return True
    except Exception:
        return False


def _ensure_tty_line_mode(*, fd: int) -> None:
    try:
        state = termios.tcgetattr(fd)
    except Exception:
        restore_terminal_after_input(fd=fd, original_state=None)
        return
    if len(state) <= 3:
        return
    if len(state) <= 1:
        return
    current_iflag = int(state[0])
    current_lflag = int(state[3])
    desired_iflag = current_iflag | termios.ICRNL
    desired_iflag &= ~int(getattr(termios, "INLCR", 0))
    desired_iflag &= ~int(getattr(termios, "IGNCR", 0))
    desired_lflag = _strip_pendin(current_lflag | termios.ICANON | termios.ECHO | termios.ISIG)
    if desired_lflag == current_lflag and desired_iflag == current_iflag:
        return
    updated = list(state)
    updated[0] = desired_iflag
    updated[3] = desired_lflag
    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, cast(Any, updated))
    except Exception:
        restore_terminal_after_input(fd=fd, original_state=None)


def _canonical_line_state(*, fd: int) -> list[int] | None:
    try:
        current = termios.tcgetattr(fd)
    except Exception:
        return None
    if len(current) <= 3:
        return list(current)
    updated = list(current)
    if len(updated) > 0:
        iflag = int(updated[0]) | termios.ICRNL
        iflag &= ~int(getattr(termios, "INLCR", 0))
        iflag &= ~int(getattr(termios, "IGNCR", 0))
        updated[0] = iflag
    updated[3] = _strip_pendin(int(updated[3]) | termios.ICANON | termios.ECHO | termios.ISIG)
    return updated


@contextmanager
def temporary_tty_character_mode(
    *,
    fd: int,
    emit: Callable[..., None] | None = None,
    clear_pendin: bool = True,
) -> Iterator[bool]:
    """Switch stdin to character mode for interactive TUI handoff windows.

    This closes the gap between line-oriented dashboard input and the selector TUI
    taking control of the terminal. Without this, early arrow-key bursts can be
    echoed and line-buffered before Textual installs its own input mode.
    """
    try:
        original_state = termios.tcgetattr(fd)
    except Exception:
        yield False
        return
    if clear_pendin:
        _clear_standard_tty_pendin(emit=emit, component="ui.terminal_session")
    applied = _set_tty_character_mode(fd=fd, original_state=original_state)
    if callable(emit):
        emit(
            "ui.tty.transition",
            component="ui.terminal_session",
            action="selector_launch_character_mode",
            applied=applied,
        )
    try:
        yield applied
    finally:
        restore_terminal_after_input(fd=fd, original_state=original_state, emit=emit)


def normalize_standard_tty_state(
    *, emit: Callable[..., None] | None = None, component: str = "ui.terminal_session"
) -> None:
    for fd in _standard_output_tty_fds():
        _ensure_tty_line_mode(fd=fd)
        _clear_pendin(fd=fd, emit=emit, component=component)


def _strip_pendin(lflag: int) -> int:
    pendin = int(getattr(termios, "PENDIN", 0))
    if pendin:
        lflag &= ~pendin
    return lflag


def _clear_pendin(*, fd: int, emit: Callable[..., None] | None = None, component: str) -> bool:
    pendin = int(getattr(termios, "PENDIN", 0))
    if not pendin:
        return False
    try:
        state = termios.tcgetattr(fd)
    except Exception:
        return False
    if len(state) <= 3:
        return False
    current_lflag = int(state[3])
    if (current_lflag & pendin) == 0:
        return False
    updated = list(state)
    updated[3] = current_lflag & ~pendin
    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, cast(Any, updated))
        if callable(emit):
            emit("ui.tty.transition", component=component, action="clear_pendin", fd=fd, applied=True)
        return True
    except Exception as exc:
        if callable(emit):
            emit(
                "ui.tty.transition",
                component=component,
                action="clear_pendin",
                fd=fd,
                applied=False,
                error=type(exc).__name__,
            )
        return False


def _set_pendin(*, fd: int, emit: Callable[..., None] | None = None, component: str) -> bool:
    pendin = int(getattr(termios, "PENDIN", 0))
    if not pendin:
        return False
    try:
        state = termios.tcgetattr(fd)
    except Exception:
        return False
    if len(state) <= 3:
        return False
    current_lflag = int(state[3])
    if (current_lflag & pendin) != 0:
        return False
    updated = list(state)
    updated[3] = current_lflag | pendin
    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, cast(Any, updated))
        if callable(emit):
            emit("ui.tty.transition", component=component, action="set_pendin", fd=fd, applied=True)
        return True
    except Exception as exc:
        if callable(emit):
            emit(
                "ui.tty.transition",
                component=component,
                action="set_pendin",
                fd=fd,
                applied=False,
                error=type(exc).__name__,
            )
        return False


def _clear_standard_tty_pendin(*, emit: Callable[..., None] | None = None, component: str) -> None:
    for fd in _standard_output_tty_fds():
        _clear_pendin(fd=fd, emit=emit, component=component)


@contextmanager
def temporary_standard_output_pendin(
    *,
    emit: Callable[..., None] | None = None,
    component: str = "ui.terminal_session",
) -> Iterator[None]:
    touched: list[tuple[int, list[int]]] = []
    for fd in _standard_output_tty_fds():
        try:
            state = termios.tcgetattr(fd)
        except Exception:
            continue
        touched.append((fd, list(state)))
        _set_pendin(fd=fd, emit=emit, component=component)
    try:
        yield
    finally:
        for fd, state in reversed(touched):
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, cast(Any, state))
            except Exception:
                restore_terminal_after_input(fd=fd, original_state=None, emit=emit)


def _standard_output_tty_fds() -> tuple[int, ...]:
    fds: list[int] = []
    seen: set[int] = set()
    for stream in (
        getattr(sys, "stdout", None),
        getattr(sys, "stderr", None),
        getattr(sys, "__stdout__", None),
        getattr(sys, "__stderr__", None),
    ):
        if stream is None:
            continue
        try:
            fd = int(stream.fileno())
        except Exception:
            continue
        if fd in seen:
            continue
        seen.add(fd)
        try:
            if not os.isatty(fd):
                continue
        except Exception:
            continue
        fds.append(fd)
    return tuple(fds)
