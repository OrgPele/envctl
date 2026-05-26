from __future__ import annotations

from contextlib import contextmanager
import os
import sys
import threading
import time
from typing import Any, Callable, Mapping, cast

from envctl_engine.shared.parsing import parse_int

from .backend_policy import emit_selector_debug
from .io_probe import SelectorIoProbe


def _initial_textual_driver_stats() -> dict[str, object]:
    return {
        "select_calls": 0,
        "select_ready_calls": 0,
        "select_not_ready_calls": 0,
        "select_errors": 0,
        "select_timeout_samples": [],
        "select_read_fd_counts": {},
        "select_ready_fd_counts": {},
        "read_calls": 0,
        "read_bytes": 0,
        "read_samples": [],
        "read_thread_counts": {},
        "read_fd_counts": {},
        "read_fd_termios_initial": {},
        "read_errors": 0,
        "read_zero_reads": 0,
        "last_read_mono_ns": 0,
        "feed_calls": 0,
        "feed_chars": 0,
        "escape_bytes": 0,
        "messages_total": 0,
        "key_events_total": 0,
        "key_events_by_name": {},
        "non_key_messages": {},
        "feed_samples": [],
    }


def _stat_int(stats: Mapping[str, object], key: str) -> int:
    return parse_int(stats.get(key), 0)


def _increment_stat(stats: dict[str, object], key: str, amount: int = 1) -> None:
    stats[key] = _stat_int(stats, key) + amount


def _increment_counter(counter: dict[object, object], key: object, amount: int = 1) -> None:
    counter[key] = parse_int(counter.get(key), 0) + amount


@contextmanager
def instrument_textual_parser_keys(
    *,
    emit: Callable[..., None] | None,
    enabled: bool,
    selector_id: str,
    deep_debug: bool,
    esc_delay_env_ms: int,
) -> Any:
    if not enabled:
        yield
        return
    try:
        import textual.constants as textual_constants
        import textual.drivers.linux_driver as linux_driver_mod
        import textual.events as textual_events
    except Exception as exc:
        emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.unavailable",
            selector_id=selector_id,
            reason="import_failed",
            error=type(exc).__name__,
        )
        yield
        return
    original_parser = getattr(linux_driver_mod, "XTermParser", None)
    if original_parser is None:
        emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.unavailable",
            selector_id=selector_id,
            reason="missing_xterm_parser",
        )
        yield
        return

    stats = _initial_textual_driver_stats()
    stats_lock = threading.Lock()
    io_probe = SelectorIoProbe()
    stdin_fd = io_probe.safe_fileno(sys.stdin)
    stdout_fd = io_probe.safe_fileno(sys.stdout)

    emit_selector_debug(
        emit,
        enabled=deep_debug,
        event="ui.selector.key.driver.config",
        selector_id=selector_id,
        env_escdelay_ms=esc_delay_env_ms,
        textual_escape_delay_ms=int(float(textual_constants.ESCAPE_DELAY) * 1000.0),
        parser_class=str(getattr(original_parser, "__name__", "XTermParser")),
        stdin_fd=stdin_fd,
        stdout_fd=stdout_fd,
        stdin_tty=bool(getattr(sys.stdin, "isatty", lambda: False)()),
        stdout_tty=bool(getattr(sys.stdout, "isatty", lambda: False)()),
        stdin_tty_name=io_probe.tty_name(stdin_fd),
        term=str(os.environ.get("TERM", "")),
        colorterm=str(os.environ.get("COLORTERM", "")),
        term_program=str(os.environ.get("TERM_PROGRAM", "")),
        term_program_version=str(os.environ.get("TERM_PROGRAM_VERSION", "")),
        term_session_id=str(os.environ.get("TERM_SESSION_ID", "")),
        vscode_pid=str(os.environ.get("VSCODE_PID", "")),
        textual_parent_pid=str(os.environ.get("TEXTUAL_PID", "")),
        stdin_termios=io_probe.termios_snapshot(stdin_fd),
        stdout_termios=io_probe.termios_snapshot(stdout_fd),
    )

    class _InstrumentedXTermParser(original_parser):
        def feed(self, data: str):  # type: ignore[override]
            with stats_lock:
                _increment_stat(stats, "feed_calls")
                _increment_stat(stats, "feed_chars", len(data))
                _increment_stat(stats, "escape_bytes", data.count("\x1b"))
                samples = stats["feed_samples"]
                if isinstance(samples, list) and len(samples) < 16:
                    samples.append(repr(data[:48]))
            for message in super().feed(data):
                with stats_lock:
                    _increment_stat(stats, "messages_total")
                    if isinstance(message, textual_events.Key):
                        _increment_stat(stats, "key_events_total")
                        key = str(getattr(message, "key", "") or "").strip() or "<empty>"
                        by_name = stats["key_events_by_name"]
                        if isinstance(by_name, dict):
                            _increment_counter(by_name, key)
                    else:
                        message_name = type(message).__name__
                        non_key = stats["non_key_messages"]
                        if isinstance(non_key, dict):
                            _increment_counter(non_key, message_name)
                yield message

    original_os_read = getattr(linux_driver_mod.os, "read", None)
    selectors_mod = getattr(linux_driver_mod, "selectors", None)
    select_selector_cls = getattr(selectors_mod, "SelectSelector", None) if selectors_mod is not None else None
    original_selector_select = getattr(select_selector_cls, "select", None) if select_selector_cls is not None else None

    def _instrumented_selector_select(self: object, timeout: object = None):  # noqa: ANN001,ANN202
        if not callable(original_selector_select):
            raise OSError("selectors.SelectSelector.select unavailable")
        with stats_lock:
            _increment_stat(stats, "select_calls")
            timeout_samples = stats["select_timeout_samples"]
            if isinstance(timeout_samples, list) and len(timeout_samples) < 16:
                timeout_samples.append(repr(timeout))
            _record_selector_read_fds(stats=stats, selector=self, io_probe=io_probe)
        try:
            ready = original_selector_select(self, timeout)
        except Exception:
            with stats_lock:
                _increment_stat(stats, "select_errors")
            raise
        ready_r: list[object] = list(ready) if isinstance(ready, list) else []
        with stats_lock:
            if ready_r:
                _increment_stat(stats, "select_ready_calls")
            else:
                _increment_stat(stats, "select_not_ready_calls")
            _record_selector_ready_fds(stats=stats, ready=ready_r, io_probe=io_probe)
        return ready

    def _instrumented_os_read(fd: int, n: int) -> bytes:
        if not callable(original_os_read):
            raise OSError("os.read unavailable")
        try:
            chunk = cast(bytes, original_os_read(fd, n))
        except Exception:
            with stats_lock:
                _increment_stat(stats, "read_errors")
            raise
        with stats_lock:
            _record_textual_read(stats=stats, fd=fd, chunk=chunk, io_probe=io_probe)
        return chunk

    setattr(linux_driver_mod, "XTermParser", _InstrumentedXTermParser)
    if callable(original_selector_select) and select_selector_cls is not None:
        try:
            setattr(select_selector_cls, "select", _instrumented_selector_select)
        except Exception:
            pass
    if callable(original_os_read):
        try:
            setattr(linux_driver_mod.os, "read", _instrumented_os_read)
        except Exception:
            pass
    emit_selector_debug(
        emit,
        enabled=deep_debug,
        event="ui.selector.key.driver.install",
        selector_id=selector_id,
    )

    def _snapshot() -> dict[str, object]:
        return textual_driver_snapshot(
            stats=stats,
            stats_lock=stats_lock,
            io_probe=io_probe,
            stdin_fd=stdin_fd,
            stdout_fd=stdout_fd,
        )

    try:
        yield _snapshot
    finally:
        try:
            setattr(linux_driver_mod, "XTermParser", original_parser)
        except Exception:
            pass
        if callable(original_selector_select) and select_selector_cls is not None:
            try:
                setattr(select_selector_cls, "select", original_selector_select)
            except Exception:
                pass
        if callable(original_os_read):
            try:
                setattr(linux_driver_mod.os, "read", original_os_read)
            except Exception:
                pass
        emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.summary",
            selector_id=selector_id,
            **_snapshot(),
        )


def _record_selector_read_fds(
    *,
    stats: dict[str, object],
    selector: object,
    io_probe: SelectorIoProbe,
) -> None:
    read_fd_counts = stats["select_read_fd_counts"]
    if not isinstance(read_fd_counts, dict):
        return
    try:
        get_map = getattr(selector, "get_map", None)
        if not callable(get_map):
            return
        mapping = get_map()
        if not isinstance(mapping, Mapping):
            return
        for fd_raw in mapping.keys():
            fd_val = io_probe.fd_value(fd_raw)
            if fd_val is None and isinstance(fd_raw, int):
                fd_val = fd_raw
            if fd_val is None:
                continue
            _increment_counter(read_fd_counts, fd_val)
    except Exception:
        pass


def _record_selector_ready_fds(
    *,
    stats: dict[str, object],
    ready: list[object],
    io_probe: SelectorIoProbe,
) -> None:
    ready_fd_counts = stats["select_ready_fd_counts"]
    if not isinstance(ready_fd_counts, dict):
        return
    try:
        for item in list(ready):
            fd_val = io_probe.fd_value(item)
            if fd_val is None:
                key_obj = item[0] if isinstance(item, tuple) and item else None
                fd_val = io_probe.fd_value(key_obj)
            if fd_val is None:
                key_obj = item[0] if isinstance(item, tuple) and item else None
                fd_raw = getattr(key_obj, "fd", None)
                if isinstance(fd_raw, int):
                    fd_val = fd_raw
            if fd_val is None:
                continue
            _increment_counter(ready_fd_counts, fd_val)
    except Exception:
        pass


def _record_textual_read(
    *,
    stats: dict[str, object],
    fd: int,
    chunk: bytes,
    io_probe: SelectorIoProbe,
) -> None:
    _increment_stat(stats, "read_calls")
    _increment_stat(stats, "read_bytes", len(chunk))
    if not chunk:
        _increment_stat(stats, "read_zero_reads")
    stats["last_read_mono_ns"] = time.monotonic_ns()
    read_samples = stats["read_samples"]
    if isinstance(read_samples, list) and len(read_samples) < 24:
        read_samples.append(repr(chunk[:64]))
    thread_counts = stats["read_thread_counts"]
    if isinstance(thread_counts, dict):
        thread_name = threading.current_thread().name or "<unknown>"
        _increment_counter(thread_counts, thread_name)
    fd_counts = stats["read_fd_counts"]
    if isinstance(fd_counts, dict):
        _increment_counter(fd_counts, fd)
    fd_termios_initial = stats["read_fd_termios_initial"]
    if isinstance(fd_termios_initial, dict):
        fd_int = int(fd)
        if fd_int not in fd_termios_initial:
            fd_termios_initial[fd_int] = io_probe.termios_snapshot(fd_int)


def textual_driver_snapshot(
    *,
    stats: dict[str, object],
    stats_lock: threading.Lock,
    io_probe: SelectorIoProbe,
    stdin_fd: int | None,
    stdout_fd: int | None,
) -> dict[str, object]:
    with stats_lock:
        read_fd_counts = dict(cast(dict[int, int], stats["read_fd_counts"]))
        read_fd_termios_initial = dict(cast(dict[int, dict[str, object]], stats["read_fd_termios_initial"]))
        select_read_fd_counts = dict(cast(dict[int, int], stats["select_read_fd_counts"]))
        select_ready_fd_counts = dict(cast(dict[int, int], stats["select_ready_fd_counts"]))
        last_read_mono_ns = _stat_int(stats, "last_read_mono_ns")
        snapshot: dict[str, object] = {
            "select_calls": _stat_int(stats, "select_calls"),
            "select_ready_calls": _stat_int(stats, "select_ready_calls"),
            "select_not_ready_calls": _stat_int(stats, "select_not_ready_calls"),
            "select_errors": _stat_int(stats, "select_errors"),
            "select_timeout_samples": list(cast(list[str], stats["select_timeout_samples"])),
            "select_read_fd_counts": {str(fd): int(count) for fd, count in select_read_fd_counts.items()},
            "select_ready_fd_counts": {str(fd): int(count) for fd, count in select_ready_fd_counts.items()},
            "read_calls": _stat_int(stats, "read_calls"),
            "read_bytes": _stat_int(stats, "read_bytes"),
            "read_samples": list(cast(list[str], stats["read_samples"])),
            "read_thread_counts": dict(cast(dict[str, int], stats["read_thread_counts"])),
            "read_fd_counts": {str(fd): int(count) for fd, count in read_fd_counts.items()},
            "read_fd_termios_initial": {str(fd): dict(state) for fd, state in read_fd_termios_initial.items()},
            "read_errors": _stat_int(stats, "read_errors"),
            "read_zero_reads": _stat_int(stats, "read_zero_reads"),
            "feed_calls": _stat_int(stats, "feed_calls"),
            "feed_chars": _stat_int(stats, "feed_chars"),
            "escape_bytes": _stat_int(stats, "escape_bytes"),
            "messages_total": _stat_int(stats, "messages_total"),
            "key_events_total": _stat_int(stats, "key_events_total"),
            "key_events_by_name": dict(cast(dict[str, int], stats["key_events_by_name"])),
            "non_key_messages": dict(cast(dict[str, int], stats["non_key_messages"])),
            "feed_samples": list(cast(list[str], stats["feed_samples"])),
        }
    if last_read_mono_ns > 0:
        snapshot["read_idle_ms"] = int(max(0, time.monotonic_ns() - last_read_mono_ns) / 1_000_000)
    read_fd_termios_current: dict[str, dict[str, object]] = {}
    for fd_raw in read_fd_counts:
        fd_int = int(fd_raw)
        read_fd_termios_current[str(fd_int)] = io_probe.termios_snapshot(fd_int)
    snapshot["read_fd_termios_current"] = read_fd_termios_current
    snapshot["stdin_termios_current"] = io_probe.termios_snapshot(stdin_fd)
    snapshot["stdout_termios_current"] = io_probe.termios_snapshot(stdout_fd)
    snapshot["stdin_pending_bytes"] = io_probe.pending_bytes_snapshot(stdin_fd)
    snapshot["stdout_pending_bytes"] = io_probe.pending_bytes_snapshot(stdout_fd)
    read_fd_pending_bytes: dict[str, int] = {}
    for fd_raw in read_fd_counts:
        fd_int = int(fd_raw)
        pending = io_probe.pending_bytes_snapshot(fd_int)
        if isinstance(pending, int):
            read_fd_pending_bytes[str(fd_int)] = pending
    snapshot["read_fd_pending_bytes"] = read_fd_pending_bytes
    return snapshot


_instrument_textual_parser_keys = instrument_textual_parser_keys
