from __future__ import annotations

from contextlib import contextmanager
import os
import sys
from typing import Any, Callable, cast

from .backend_policy import emit_selector_debug


@contextmanager
def guard_textual_nonblocking_read(
    *,
    emit: Callable[..., None] | None,
    selector_id: str,
    deep_debug: bool,
) -> Any:
    guard_env = str(os.environ.get("ENVCTL_UI_SELECTOR_NONBLOCK_READ_GUARD", "")).strip().lower()
    guard_enabled = guard_env in {"1", "true", "yes", "on"}
    if not guard_enabled:
        emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.read_guard",
            selector_id=selector_id,
            guard_enabled=False,
            reason="disabled_by_default",
        )
        yield
        return

    try:
        import textual.drivers.linux_driver as linux_driver_mod
    except Exception as exc:
        emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.read_guard",
            selector_id=selector_id,
            guard_enabled=False,
            reason="linux_driver_import_failed",
            error=type(exc).__name__,
        )
        yield
        return
    try:
        import fcntl  # type: ignore
    except Exception as exc:
        emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.read_guard",
            selector_id=selector_id,
            guard_enabled=False,
            reason="fcntl_import_failed",
            error=type(exc).__name__,
        )
        yield
        return

    try:
        stdin_obj = getattr(sys, "__stdin__", None) or sys.stdin
        stdin_fd = int(stdin_obj.fileno())
    except Exception:
        stdin_fd = -1
    if stdin_fd < 0:
        emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.read_guard",
            selector_id=selector_id,
            guard_enabled=False,
            reason="stdin_fileno_unavailable",
        )
        yield
        return

    original_flags: int | None = None
    nonblocking_applied = False
    try:
        original_flags = int(fcntl.fcntl(stdin_fd, fcntl.F_GETFL))
    except Exception as exc:
        emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.read_guard",
            selector_id=selector_id,
            guard_enabled=False,
            reason="fcntl_getfl_failed",
            error=type(exc).__name__,
        )
        yield
        return
    try:
        if original_flags & int(os.O_NONBLOCK):
            nonblocking_applied = False
        else:
            fcntl.fcntl(stdin_fd, fcntl.F_SETFL, original_flags | int(os.O_NONBLOCK))
            nonblocking_applied = True
    except Exception as exc:
        emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.read_guard",
            selector_id=selector_id,
            guard_enabled=False,
            reason="fcntl_setfl_failed",
            error=type(exc).__name__,
        )
        yield
        return

    original_os_read = getattr(linux_driver_mod.os, "read", None)
    patched_read = False

    def _safe_os_read(fd: int, n: int) -> bytes:
        if not callable(original_os_read):
            raise OSError("os.read unavailable")
        try:
            return cast(bytes, original_os_read(fd, n))
        except (BlockingIOError, InterruptedError):
            return b""

    if callable(original_os_read):
        try:
            setattr(linux_driver_mod.os, "read", _safe_os_read)
            patched_read = True
        except Exception:
            patched_read = False

    emit_selector_debug(
        emit,
        enabled=deep_debug,
        event="ui.selector.key.driver.read_guard",
        selector_id=selector_id,
        guard_enabled=True,
        nonblocking_applied=nonblocking_applied,
        patched_read=patched_read,
        stdin_fd=stdin_fd,
    )
    try:
        yield
    finally:
        if patched_read and callable(original_os_read):
            try:
                setattr(linux_driver_mod.os, "read", original_os_read)
            except Exception:
                pass
        if nonblocking_applied and original_flags is not None:
            try:
                fcntl.fcntl(stdin_fd, fcntl.F_SETFL, original_flags)
            except Exception:
                pass


_guard_textual_nonblocking_read = guard_textual_nonblocking_read
