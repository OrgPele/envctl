from __future__ import annotations

import fcntl
import os
import signal
import sys
import termios
import threading
import traceback
from typing import Any, Callable


def _bool_env(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def snapshot_enabled(env: dict[str, str] | None) -> bool:
    return _bool_env((env or {}).get("ENVCTL_DEBUG_PLAN_SNAPSHOT"))


def emit_plan_handoff_snapshot(
    emit: Callable[..., Any] | None,
    *,
    env: dict[str, str] | None,
    checkpoint: str,
    extra: dict[str, object] | None = None,
) -> None:
    if emit is None or not snapshot_enabled(env):
        return
    payload: dict[str, object] = {
        "checkpoint": checkpoint,
        "fds": {str(fd): _fd_snapshot(fd) for fd in (0, 1, 2)},
        "signals": _signal_snapshot(),
        "threads": _thread_snapshot(),
    }
    if extra:
        payload.update(extra)
    emit("ui.plan_handoff.snapshot", **payload)


def _fd_snapshot(fd: int) -> dict[str, object]:
    snapshot: dict[str, object] = {
        "fd": fd,
        "isatty": False,
    }
    try:
        flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        snapshot["flags"] = flags
        snapshot["nonblock"] = bool(flags & os.O_NONBLOCK)
    except Exception as exc:
        snapshot["flags_error"] = repr(exc)
        return snapshot
    is_tty = os.isatty(fd)
    snapshot["isatty"] = is_tty
    if not is_tty:
        return snapshot
    try:
        snapshot["ttyname"] = os.ttyname(fd)
    except Exception as exc:
        snapshot["ttyname_error"] = repr(exc)
    try:
        attrs = termios.tcgetattr(fd)
        lflag = int(attrs[3])
        pendin = int(getattr(termios, "PENDIN", 0))
        snapshot["iflag"] = int(attrs[0])
        snapshot["oflag"] = int(attrs[1])
        snapshot["cflag"] = int(attrs[2])
        snapshot["lflag"] = lflag
        snapshot["icanon"] = bool(lflag & int(termios.ICANON))
        snapshot["echo"] = bool(lflag & int(termios.ECHO))
        snapshot["isig"] = bool(lflag & int(termios.ISIG))
        snapshot["pendin"] = bool(pendin and (lflag & pendin))
        snapshot["vmin"] = _cc_to_int(attrs[6][termios.VMIN])
        snapshot["vtime"] = _cc_to_int(attrs[6][termios.VTIME])
    except Exception as exc:
        snapshot["termios_error"] = repr(exc)
    return snapshot


def _cc_to_int(value: object) -> int | str:
    if isinstance(value, bytes):
        return int(value[0]) if value else 0
    try:
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return str(value)


def _signal_snapshot() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for name in ("SIGINT", "SIGWINCH", "SIGTSTP"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            handler = signal.getsignal(sig)
            mapping[name] = _handler_name(handler)
        except Exception as exc:
            mapping[name] = f"error:{exc!r}"
    return mapping


def _handler_name(handler: object) -> str:
    if handler is signal.SIG_DFL:
        return "SIG_DFL"
    if handler is signal.SIG_IGN:
        return "SIG_IGN"
    if callable(handler):
        return getattr(handler, "__qualname__", getattr(handler, "__name__", repr(handler)))
    return repr(handler)


def _thread_snapshot() -> list[dict[str, object]]:
    current_frames = sys._current_frames()
    snapshots: list[dict[str, object]] = []
    for thread in threading.enumerate():
        stack_tail: list[str] = []
        frame = current_frames.get(thread.ident) if thread.ident is not None else None
        if frame is not None:
            extracted = traceback.extract_stack(frame)
            stack_tail = [f"{item.filename}:{item.lineno}:{item.name}" for item in extracted[-5:]]
        snapshots.append(
            {
                "name": thread.name,
                "ident": thread.ident,
                "daemon": bool(thread.daemon),
                "alive": bool(thread.is_alive()),
                "stack_tail": stack_tail,
            }
        )
    return snapshots
