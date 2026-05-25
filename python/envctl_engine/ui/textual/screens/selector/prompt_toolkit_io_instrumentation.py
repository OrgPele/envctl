from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Sequence, cast

from .backend_policy import emit_selector_debug
from .io_probe import SelectorIoProbe


def _initial_prompt_toolkit_io_stats() -> dict[str, object]:
    return {
        "select_calls": 0,
        "select_ready_calls": 0,
        "select_not_ready_calls": 0,
        "select_errors": 0,
        "select_fd_counts": {},
        "select_ready_fd_counts": {},
        "select_fd_termios": {},
        "read_calls": 0,
        "read_bytes": 0,
        "read_errors": 0,
        "read_samples": [],
        "read_fd_counts": {},
    }


@contextmanager
def instrument_prompt_toolkit_posix_io(
    *,
    emit: Callable[..., None] | None,
    deep_debug: bool,
    enabled: bool,
    selector_id: str,
) -> Sequence[Callable[[], dict[str, object]]]:
    if not deep_debug or not enabled:
        yield ((lambda: {}),)
        return
    try:
        import prompt_toolkit.input.posix_utils as posix_utils
    except Exception:
        emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.unavailable",
            selector_id=selector_id,
            backend="prompt_toolkit",
            reason="prompt_toolkit_posix_utils_missing",
        )
        yield ((lambda: {}),)
        return

    stats = _initial_prompt_toolkit_io_stats()
    original_select = getattr(posix_utils.select, "select", None)
    original_read = getattr(posix_utils.os, "read", None)
    io_probe = SelectorIoProbe()

    def _instrumented_select(rlist, wlist, xlist, timeout=None):  # noqa: ANN001,ANN202
        if not callable(original_select):
            raise OSError("select unavailable")
        _record_select_inputs(stats=stats, rlist=rlist, io_probe=io_probe)
        try:
            ready = original_select(rlist, wlist, xlist, timeout)
        except Exception:
            stats["select_errors"] = int(stats["select_errors"]) + 1
            raise
        _record_select_result(stats=stats, ready=ready, io_probe=io_probe)
        return ready

    def _instrumented_read(fd: int, count: int):  # noqa: ANN202
        if not callable(original_read):
            raise OSError("os.read unavailable")
        try:
            data = original_read(fd, count)
        except Exception:
            stats["read_errors"] = int(stats["read_errors"]) + 1
            raise
        _record_read(stats=stats, fd=fd, data=data)
        return data

    if callable(original_select):
        try:
            setattr(posix_utils.select, "select", _instrumented_select)
        except Exception:
            pass
    if callable(original_read):
        try:
            setattr(posix_utils.os, "read", _instrumented_read)
        except Exception:
            pass
    emit_selector_debug(
        emit,
        enabled=deep_debug,
        event="ui.selector.key.driver.install",
        selector_id=selector_id,
        backend="prompt_toolkit",
        method="posix_utils_io_patch",
    )
    try:

        def _snapshot() -> dict[str, object]:
            return prompt_toolkit_io_snapshot(stats)

        yield (_snapshot,)
    finally:
        if callable(original_select):
            try:
                setattr(posix_utils.select, "select", original_select)
            except Exception:
                pass
        if callable(original_read):
            try:
                setattr(posix_utils.os, "read", original_read)
            except Exception:
                pass
        emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.summary",
            selector_id=selector_id,
            backend="prompt_toolkit",
            **_snapshot(),
        )


def _record_select_inputs(*, stats: dict[str, object], rlist: object, io_probe: SelectorIoProbe) -> None:
    stats["select_calls"] = int(stats["select_calls"]) + 1
    fd_counts = cast(dict[int, int], stats["select_fd_counts"])
    fd_termios = cast(dict[int, dict[str, object]], stats["select_fd_termios"])
    for item in list(rlist) if rlist is not None else []:
        fd_val = io_probe.fd_value(item)
        if fd_val is None:
            continue
        fd_counts[fd_val] = int(fd_counts.get(fd_val, 0)) + 1
        if fd_val not in fd_termios:
            fd_termios[fd_val] = io_probe.prompt_toolkit_termios_snapshot(fd_val)


def _record_select_result(*, stats: dict[str, object], ready: object, io_probe: SelectorIoProbe) -> None:
    ready_r = ready[0] if isinstance(ready, tuple) and len(ready) >= 1 else []
    ready_fd_counts = cast(dict[int, int], stats["select_ready_fd_counts"])
    for item in list(ready_r):
        fd_val = io_probe.fd_value(item)
        if fd_val is None:
            continue
        ready_fd_counts[fd_val] = int(ready_fd_counts.get(fd_val, 0)) + 1
    if ready_r:
        stats["select_ready_calls"] = int(stats["select_ready_calls"]) + 1
    else:
        stats["select_not_ready_calls"] = int(stats["select_not_ready_calls"]) + 1


def _record_read(*, stats: dict[str, object], fd: int, data: bytes) -> None:
    stats["read_calls"] = int(stats["read_calls"]) + 1
    stats["read_bytes"] = int(stats["read_bytes"]) + len(data)
    fd_counts = cast(dict[int, int], stats["read_fd_counts"])
    fd_counts[int(fd)] = int(fd_counts.get(int(fd), 0)) + 1
    read_samples = cast(list[str], stats["read_samples"])
    if len(read_samples) < 24:
        read_samples.append(repr(data[:64]))


def prompt_toolkit_io_snapshot(stats: dict[str, object]) -> dict[str, object]:
    return {
        "io_select_calls": int(stats["select_calls"]),
        "io_select_ready_calls": int(stats["select_ready_calls"]),
        "io_select_not_ready_calls": int(stats["select_not_ready_calls"]),
        "io_select_errors": int(stats["select_errors"]),
        "io_select_fd_counts": dict(cast(dict[int, int], stats["select_fd_counts"])),
        "io_select_ready_fd_counts": dict(cast(dict[int, int], stats["select_ready_fd_counts"])),
        "io_select_fd_termios": dict(cast(dict[int, dict[str, object]], stats["select_fd_termios"])),
        "io_read_calls": int(stats["read_calls"]),
        "io_read_bytes": int(stats["read_bytes"]),
        "io_read_errors": int(stats["read_errors"]),
        "io_read_samples": list(cast(list[str], stats["read_samples"])),
        "io_read_fd_counts": dict(cast(dict[int, int], stats["read_fd_counts"])),
    }


_instrument_prompt_toolkit_posix_io = instrument_prompt_toolkit_posix_io
