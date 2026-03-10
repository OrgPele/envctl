from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
import re
import sys
import threading
import time
import traceback
from typing import Any, Callable, Mapping, Sequence, cast

from envctl_engine.ui.capabilities import (
    prompt_toolkit_selector_enabled as _prompt_toolkit_selector_enabled_impl,
    textual_importable as _textual_importable_impl,
)
from envctl_engine.ui.selector_model import (
    SelectorItem,
)
from envctl_engine.ui.terminal_session import can_interactive_tty, prompt_toolkit_available


@dataclass(slots=True)
class _RowRef:
    item: SelectorItem
    selected: bool = False
    visible: bool = True


def _emit(emit: Callable[..., None] | None, event: str, **payload: object) -> None:
    if not callable(emit):
        return
    emit(event, component="ui.textual.selector", **payload)


def _selector_id(prompt: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(prompt).strip().lower()).strip("_")
    return normalized or "selector"


def _selector_impl() -> str:
    simple_menus = str(os.environ.get("ENVCTL_UI_SIMPLE_MENUS", "")).strip().lower()
    if simple_menus in {"1", "true", "yes", "on"}:
        return "planning_style"
    if simple_menus in {"0", "false", "no", "off"}:
        return "textual"
    raw = str(os.environ.get("ENVCTL_UI_SELECTOR_IMPL", "")).strip().lower()
    if raw in {"planning_style", "prompt_toolkit", "prompt-toolkit", "ptk"}:
        return "planning_style"
    if raw in {"textual", "textual_plan_style", "legacy"}:
        return "textual"
    return "textual"


def _prompt_toolkit_selector_enabled(*, build_only: bool = False) -> bool:
    if build_only:
        return False
    return _prompt_toolkit_selector_enabled_impl(os.environ)


def _textual_importable() -> bool:
    return _textual_importable_impl()


def _deep_debug_enabled(emit: Callable[..., None] | None) -> bool:
    runtime = getattr(emit, "__self__", None)
    env = getattr(runtime, "env", None)
    value = ""
    if isinstance(env, Mapping):
        value = str(env.get("ENVCTL_DEBUG_UI_MODE", "")).strip().lower()
    if not value:
        value = str(os.environ.get("ENVCTL_DEBUG_UI_MODE", "")).strip().lower()
    return value == "deep"


def _selector_key_trace_enabled(emit: Callable[..., None] | None) -> bool:
    if not _deep_debug_enabled(emit):
        return False
    runtime = getattr(emit, "__self__", None)
    env = getattr(runtime, "env", None)
    value = ""
    if isinstance(env, Mapping):
        value = str(env.get("ENVCTL_DEBUG_SELECTOR_KEYS", "")).strip().lower()
    if not value:
        value = str(os.environ.get("ENVCTL_DEBUG_SELECTOR_KEYS", "")).strip().lower()
    if value in {"0", "false", "no", "off"}:
        return False
    # Default in deep mode: collect lightweight key counters and emit one summary.
    return True


def _selector_key_trace_verbose_enabled(emit: Callable[..., None] | None) -> bool:
    runtime = getattr(emit, "__self__", None)
    env = getattr(runtime, "env", None)
    value = ""
    if isinstance(env, Mapping):
        value = str(env.get("ENVCTL_DEBUG_SELECTOR_KEYS_VERBOSE", "")).strip().lower()
    if not value:
        value = str(os.environ.get("ENVCTL_DEBUG_SELECTOR_KEYS_VERBOSE", "")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _selector_driver_trace_enabled(emit: Callable[..., None] | None) -> bool:
    deep_debug = _deep_debug_enabled(emit)
    runtime = getattr(emit, "__self__", None)
    env = getattr(runtime, "env", None)
    value = ""
    if isinstance(env, Mapping):
        value = str(env.get("ENVCTL_DEBUG_SELECTOR_DRIVER_KEYS", "")).strip().lower()
    if not value:
        value = str(os.environ.get("ENVCTL_DEBUG_SELECTOR_DRIVER_KEYS", "")).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    # Default in deep mode so incident bundles include parser ingress evidence.
    return deep_debug


def _selector_thread_stack_enabled(emit: Callable[..., None] | None) -> bool:
    if not _deep_debug_enabled(emit):
        return False
    runtime = getattr(emit, "__self__", None)
    env = getattr(runtime, "env", None)
    value = ""
    if isinstance(env, Mapping):
        value = str(env.get("ENVCTL_DEBUG_SELECTOR_THREAD_STACK", "")).strip().lower()
    if not value:
        value = str(os.environ.get("ENVCTL_DEBUG_SELECTOR_THREAD_STACK", "")).strip().lower()
    return value in {"1", "true", "yes", "on"}


def _selector_disable_focus_reporting_enabled(emit: Callable[..., None] | None) -> bool:
    runtime = getattr(emit, "__self__", None)
    env = getattr(runtime, "env", None)
    value = ""
    if isinstance(env, Mapping):
        value = str(env.get("ENVCTL_UI_SELECTOR_FOCUS_REPORTING", "")).strip().lower()
    if not value:
        value = str(os.environ.get("ENVCTL_UI_SELECTOR_FOCUS_REPORTING", "")).strip().lower()
    if value in {"1", "true", "yes", "on", "enable", "enabled"}:
        return False
    if value in {"0", "false", "no", "off", "disable", "disabled"}:
        return True
    # Default to disabling focus reports in selector screens to avoid spurious
    # focus-out events swallowing subsequent keyboard interaction on some terminals.
    return True


def _selector_driver_thread_snapshot(app: object, *, include_stack: bool) -> dict[str, object]:
    snapshot: dict[str, object] = {}
    try:
        driver = getattr(app, "_driver", None)
    except Exception:
        driver = None
    if driver is None:
        snapshot["driver_present"] = False
        return snapshot
    snapshot["driver_present"] = True
    exit_event = getattr(driver, "exit_event", None)
    is_set = getattr(exit_event, "is_set", None)
    if callable(is_set):
        try:
            snapshot["driver_exit_event_set"] = bool(is_set())
        except Exception:
            snapshot["driver_exit_event_set"] = None
    key_thread = getattr(driver, "_key_thread", None)
    if key_thread is None:
        snapshot["input_thread_present"] = False
        return snapshot
    snapshot["input_thread_present"] = True
    snapshot["input_thread_name"] = str(getattr(key_thread, "name", "") or "")
    snapshot["input_thread_ident"] = getattr(key_thread, "ident", None)
    snapshot["input_thread_native_id"] = getattr(key_thread, "native_id", None)
    snapshot["input_thread_daemon"] = bool(getattr(key_thread, "daemon", False))
    is_alive = getattr(key_thread, "is_alive", None)
    alive = bool(is_alive()) if callable(is_alive) else False
    snapshot["input_thread_alive"] = alive
    if not include_stack or not alive:
        return snapshot
    ident = getattr(key_thread, "ident", None)
    if not isinstance(ident, int):
        snapshot["input_thread_stack"] = []
        return snapshot
    try:
        frame = sys._current_frames().get(ident)
    except Exception:
        frame = None
    if frame is None:
        snapshot["input_thread_stack"] = []
        return snapshot
    try:
        extracted = traceback.extract_stack(frame, limit=8)
        snapshot["input_thread_stack"] = [f"{entry.filename}:{entry.lineno}:{entry.name}" for entry in extracted]
    except Exception as exc:
        snapshot["input_thread_stack_error"] = type(exc).__name__
    return snapshot


@contextmanager
def _guard_textual_nonblocking_read(
    *,
    emit: Callable[..., None] | None,
    selector_id: str,
    deep_debug: bool,
) -> Any:
    guard_env = str(os.environ.get("ENVCTL_UI_SELECTOR_NONBLOCK_READ_GUARD", "")).strip().lower()
    guard_enabled = guard_env in {"1", "true", "yes", "on"}
    if not guard_enabled:
        _emit_selector_debug(
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
        _emit_selector_debug(
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
        _emit_selector_debug(
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
        _emit_selector_debug(
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
        _emit_selector_debug(
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
        _emit_selector_debug(
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
            # Avoid deadlocking the Textual input thread when select() reports
            # readiness but no bytes are currently readable.
            return b""

    if callable(original_os_read):
        try:
            setattr(linux_driver_mod.os, "read", _safe_os_read)
            patched_read = True
        except Exception:
            patched_read = False

    _emit_selector_debug(
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


@contextmanager
def _instrument_textual_parser_keys(
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
        _emit_selector_debug(
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
        _emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.unavailable",
            selector_id=selector_id,
            reason="missing_xterm_parser",
        )
        yield
        return

    stats: dict[str, object] = {
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
    stats_lock = threading.Lock()

    def _fd_value(item: object) -> int | None:
        if isinstance(item, int):
            return item
        fileno = getattr(item, "fileno", None)
        if not callable(fileno):
            return None
        try:
            value = fileno()
        except Exception:
            return None
        return value if isinstance(value, int) else None

    def _safe_fileno(stream: object) -> int | None:
        fileno = getattr(stream, "fileno", None)
        if not callable(fileno):
            return None
        try:
            value = fileno()
        except Exception:
            return None
        return value if isinstance(value, int) and value >= 0 else None

    def _termios_snapshot(fd: int | None) -> dict[str, object]:
        if not isinstance(fd, int) or fd < 0:
            return {}
        state: dict[str, object] = {"fd": int(fd)}
        try:
            import termios

            attrs = termios.tcgetattr(fd)
            lflag = int(attrs[3])
            state.update(
                {
                    "lflag": lflag,
                    "canonical": bool(lflag & int(termios.ICANON)),
                    "echo": bool(lflag & int(termios.ECHO)),
                    "isig": bool(lflag & int(termios.ISIG)),
                }
            )
        except Exception as exc:
            state["termios_error"] = type(exc).__name__
        return state

    def _pending_bytes_snapshot(fd: int | None) -> int | None:
        if not isinstance(fd, int) or fd < 0:
            return None
        try:
            import array
            import fcntl
            import termios

            request = int(getattr(termios, "FIONREAD"))
            value = array.array("i", [0])
            fcntl.ioctl(fd, request, value, True)
            pending = int(value[0])
            return pending if pending >= 0 else 0
        except Exception:
            return None

    def _tty_name(fd: int | None) -> str:
        if not isinstance(fd, int) or fd < 0:
            return ""
        try:
            return str(os.ttyname(fd))
        except Exception:
            return ""

    stdin_fd = _safe_fileno(sys.stdin)
    stdout_fd = _safe_fileno(sys.stdout)

    _emit_selector_debug(
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
        stdin_tty_name=_tty_name(stdin_fd),
        term=str(os.environ.get("TERM", "")),
        colorterm=str(os.environ.get("COLORTERM", "")),
        term_program=str(os.environ.get("TERM_PROGRAM", "")),
        term_program_version=str(os.environ.get("TERM_PROGRAM_VERSION", "")),
        term_session_id=str(os.environ.get("TERM_SESSION_ID", "")),
        vscode_pid=str(os.environ.get("VSCODE_PID", "")),
        textual_parent_pid=str(os.environ.get("TEXTUAL_PID", "")),
        stdin_termios=_termios_snapshot(stdin_fd),
        stdout_termios=_termios_snapshot(stdout_fd),
    )

    class _InstrumentedXTermParser(original_parser):
        def feed(self, data: str):  # type: ignore[override]
            with stats_lock:
                stats["feed_calls"] = int(stats["feed_calls"]) + 1
                stats["feed_chars"] = int(stats["feed_chars"]) + len(data)
                stats["escape_bytes"] = int(stats["escape_bytes"]) + data.count("\x1b")
                samples = stats["feed_samples"]
                if isinstance(samples, list) and len(samples) < 16:
                    samples.append(repr(data[:48]))
            for message in super().feed(data):
                with stats_lock:
                    stats["messages_total"] = int(stats["messages_total"]) + 1
                    if isinstance(message, textual_events.Key):
                        stats["key_events_total"] = int(stats["key_events_total"]) + 1
                        key = str(getattr(message, "key", "") or "").strip() or "<empty>"
                        by_name = stats["key_events_by_name"]
                        if isinstance(by_name, dict):
                            by_name[key] = int(by_name.get(key, 0)) + 1
                    else:
                        message_name = type(message).__name__
                        non_key = stats["non_key_messages"]
                        if isinstance(non_key, dict):
                            non_key[message_name] = int(non_key.get(message_name, 0)) + 1
                yield message

    original_os_read = getattr(linux_driver_mod.os, "read", None)
    selectors_mod = getattr(linux_driver_mod, "selectors", None)
    select_selector_cls = getattr(selectors_mod, "SelectSelector", None) if selectors_mod is not None else None
    original_selector_select = getattr(select_selector_cls, "select", None) if select_selector_cls is not None else None

    def _instrumented_selector_select(self: object, timeout: object = None):  # noqa: ANN001,ANN202
        if not callable(original_selector_select):
            raise OSError("selectors.SelectSelector.select unavailable")
        with stats_lock:
            stats["select_calls"] = int(stats["select_calls"]) + 1
            timeout_samples = stats["select_timeout_samples"]
            if isinstance(timeout_samples, list) and len(timeout_samples) < 16:
                timeout_samples.append(repr(timeout))
            read_fd_counts = stats["select_read_fd_counts"]
            if isinstance(read_fd_counts, dict):
                try:
                    get_map = getattr(self, "get_map", None)
                    if callable(get_map):
                        mapping = get_map()
                        if isinstance(mapping, Mapping):
                            for fd_raw in mapping.keys():
                                fd_val = _fd_value(fd_raw)
                                if fd_val is None and isinstance(fd_raw, int):
                                    fd_val = fd_raw
                                if fd_val is None:
                                    continue
                                read_fd_counts[fd_val] = int(read_fd_counts.get(fd_val, 0)) + 1
                except Exception:
                    pass
        try:
            ready = original_selector_select(self, timeout)
        except Exception:
            with stats_lock:
                stats["select_errors"] = int(stats["select_errors"]) + 1
            raise
        ready_r: list[object] = list(ready) if isinstance(ready, list) else []
        with stats_lock:
            if ready_r:
                stats["select_ready_calls"] = int(stats["select_ready_calls"]) + 1
            else:
                stats["select_not_ready_calls"] = int(stats["select_not_ready_calls"]) + 1
            ready_fd_counts = stats["select_ready_fd_counts"]
            if isinstance(ready_fd_counts, dict):
                try:
                    for item in list(ready_r):
                        fd_val = _fd_value(item)
                        if fd_val is None:
                            key_obj = item[0] if isinstance(item, tuple) and item else None
                            fd_val = _fd_value(key_obj)
                        if fd_val is None:
                            key_obj = item[0] if isinstance(item, tuple) and item else None
                            fd_raw = getattr(key_obj, "fd", None)
                            if isinstance(fd_raw, int):
                                fd_val = fd_raw
                        if fd_val is None:
                            continue
                        ready_fd_counts[fd_val] = int(ready_fd_counts.get(fd_val, 0)) + 1
                except Exception:
                    pass
        return ready

    def _instrumented_os_read(fd: int, n: int) -> bytes:
        if not callable(original_os_read):
            raise OSError("os.read unavailable")
        try:
            chunk = cast(bytes, original_os_read(fd, n))
        except Exception:
            with stats_lock:
                stats["read_errors"] = int(stats["read_errors"]) + 1
            raise
        with stats_lock:
            stats["read_calls"] = int(stats["read_calls"]) + 1
            stats["read_bytes"] = int(stats["read_bytes"]) + len(chunk)
            if not chunk:
                stats["read_zero_reads"] = int(stats["read_zero_reads"]) + 1
            stats["last_read_mono_ns"] = time.monotonic_ns()
            read_samples = stats["read_samples"]
            if isinstance(read_samples, list) and len(read_samples) < 24:
                read_samples.append(repr(chunk[:64]))
            thread_counts = stats["read_thread_counts"]
            if isinstance(thread_counts, dict):
                thread_name = threading.current_thread().name or "<unknown>"
                thread_counts[thread_name] = int(thread_counts.get(thread_name, 0)) + 1
            fd_counts = stats["read_fd_counts"]
            if isinstance(fd_counts, dict):
                fd_counts[int(fd)] = int(fd_counts.get(int(fd), 0)) + 1
            fd_termios_initial = stats["read_fd_termios_initial"]
            if isinstance(fd_termios_initial, dict):
                fd_int = int(fd)
                if fd_int not in fd_termios_initial:
                    fd_termios_initial[fd_int] = _termios_snapshot(fd_int)
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
    _emit_selector_debug(
        emit,
        enabled=deep_debug,
        event="ui.selector.key.driver.install",
        selector_id=selector_id,
    )

    def _snapshot() -> dict[str, object]:
        with stats_lock:
            read_fd_counts = dict(cast(dict[int, int], stats["read_fd_counts"]))
            read_fd_termios_initial = dict(cast(dict[int, dict[str, object]], stats["read_fd_termios_initial"]))
            select_read_fd_counts = dict(cast(dict[int, int], stats["select_read_fd_counts"]))
            select_ready_fd_counts = dict(cast(dict[int, int], stats["select_ready_fd_counts"]))
            last_read_mono_ns = int(stats["last_read_mono_ns"])
            snapshot: dict[str, object] = {
                "select_calls": int(stats["select_calls"]),
                "select_ready_calls": int(stats["select_ready_calls"]),
                "select_not_ready_calls": int(stats["select_not_ready_calls"]),
                "select_errors": int(stats["select_errors"]),
                "select_timeout_samples": list(cast(list[str], stats["select_timeout_samples"])),
                "select_read_fd_counts": {str(fd): int(count) for fd, count in select_read_fd_counts.items()},
                "select_ready_fd_counts": {str(fd): int(count) for fd, count in select_ready_fd_counts.items()},
                "read_calls": int(stats["read_calls"]),
                "read_bytes": int(stats["read_bytes"]),
                "read_samples": list(cast(list[str], stats["read_samples"])),
                "read_thread_counts": dict(cast(dict[str, int], stats["read_thread_counts"])),
                "read_fd_counts": {str(fd): int(count) for fd, count in read_fd_counts.items()},
                "read_fd_termios_initial": {str(fd): dict(state) for fd, state in read_fd_termios_initial.items()},
                "read_errors": int(stats["read_errors"]),
                "read_zero_reads": int(stats["read_zero_reads"]),
                "feed_calls": int(stats["feed_calls"]),
                "feed_chars": int(stats["feed_chars"]),
                "escape_bytes": int(stats["escape_bytes"]),
                "messages_total": int(stats["messages_total"]),
                "key_events_total": int(stats["key_events_total"]),
                "key_events_by_name": dict(cast(dict[str, int], stats["key_events_by_name"])),
                "non_key_messages": dict(cast(dict[str, int], stats["non_key_messages"])),
                "feed_samples": list(cast(list[str], stats["feed_samples"])),
            }
        if last_read_mono_ns > 0:
            snapshot["read_idle_ms"] = int(max(0, time.monotonic_ns() - last_read_mono_ns) / 1_000_000)
        read_fd_termios_current: dict[str, dict[str, object]] = {}
        for fd_raw in read_fd_counts:
            fd_int = int(fd_raw)
            read_fd_termios_current[str(fd_int)] = _termios_snapshot(fd_int)
        snapshot["read_fd_termios_current"] = read_fd_termios_current
        snapshot["stdin_termios_current"] = _termios_snapshot(stdin_fd)
        snapshot["stdout_termios_current"] = _termios_snapshot(stdout_fd)
        snapshot["stdin_pending_bytes"] = _pending_bytes_snapshot(stdin_fd)
        snapshot["stdout_pending_bytes"] = _pending_bytes_snapshot(stdout_fd)
        read_fd_pending_bytes: dict[str, int] = {}
        for fd_raw in read_fd_counts:
            fd_int = int(fd_raw)
            pending = _pending_bytes_snapshot(fd_int)
            if isinstance(pending, int):
                read_fd_pending_bytes[str(fd_int)] = pending
        snapshot["read_fd_pending_bytes"] = read_fd_pending_bytes
        return snapshot

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
        snapshot = _snapshot()
        _emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.summary",
            selector_id=selector_id,
            **snapshot,
        )


@contextmanager
def _instrument_prompt_toolkit_posix_io(
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
        _emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.unavailable",
            selector_id=selector_id,
            backend="prompt_toolkit",
            reason="prompt_toolkit_posix_utils_missing",
        )
        yield ((lambda: {}),)
        return

    stats: dict[str, object] = {
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
    original_select = getattr(posix_utils.select, "select", None)
    original_read = getattr(posix_utils.os, "read", None)

    def _fd_value(item: object) -> int | None:
        if isinstance(item, int):
            return item
        fileno = getattr(item, "fileno", None)
        if callable(fileno):
            try:
                fd = fileno()
                if isinstance(fd, int):
                    return fd
            except Exception:
                return None
        return None

    def _snapshot_termios(fd: int) -> dict[str, object]:
        try:
            import termios

            attrs = termios.tcgetattr(fd)
            lflag = int(attrs[3])
            return {
                "lflag": lflag,
                "canonical": bool(lflag & int(termios.ICANON)),
                "echo": bool(lflag & int(termios.ECHO)),
                "isig": bool(lflag & int(termios.ISIG)),
            }
        except Exception:
            return {"termios_error": True}

    def _instrumented_select(rlist, wlist, xlist, timeout=None):  # noqa: ANN001,ANN202
        if not callable(original_select):
            raise OSError("select unavailable")
        stats["select_calls"] = int(stats["select_calls"]) + 1
        fd_counts = cast(dict[int, int], stats["select_fd_counts"])
        fd_termios = cast(dict[int, dict[str, object]], stats["select_fd_termios"])
        for item in list(rlist) if rlist is not None else []:
            fd_val = _fd_value(item)
            if fd_val is None:
                continue
            fd_counts[fd_val] = int(fd_counts.get(fd_val, 0)) + 1
            if fd_val not in fd_termios:
                fd_termios[fd_val] = _snapshot_termios(fd_val)
        try:
            ready = original_select(rlist, wlist, xlist, timeout)
        except Exception:
            stats["select_errors"] = int(stats["select_errors"]) + 1
            raise
        ready_r = ready[0] if isinstance(ready, tuple) and len(ready) >= 1 else []
        ready_fd_counts = cast(dict[int, int], stats["select_ready_fd_counts"])
        for item in list(ready_r):
            fd_val = _fd_value(item)
            if fd_val is None:
                continue
            ready_fd_counts[fd_val] = int(ready_fd_counts.get(fd_val, 0)) + 1
        if ready_r:
            stats["select_ready_calls"] = int(stats["select_ready_calls"]) + 1
        else:
            stats["select_not_ready_calls"] = int(stats["select_not_ready_calls"]) + 1
        return ready

    def _instrumented_read(fd: int, count: int):  # noqa: ANN202
        if not callable(original_read):
            raise OSError("os.read unavailable")
        try:
            data = original_read(fd, count)
        except Exception:
            stats["read_errors"] = int(stats["read_errors"]) + 1
            raise
        stats["read_calls"] = int(stats["read_calls"]) + 1
        stats["read_bytes"] = int(stats["read_bytes"]) + len(data)
        fd_counts = cast(dict[int, int], stats["read_fd_counts"])
        fd_counts[int(fd)] = int(fd_counts.get(int(fd), 0)) + 1
        read_samples = cast(list[str], stats["read_samples"])
        if len(read_samples) < 24:
            read_samples.append(repr(data[:64]))
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
    _emit_selector_debug(
        emit,
        enabled=deep_debug,
        event="ui.selector.key.driver.install",
        selector_id=selector_id,
        backend="prompt_toolkit",
        method="posix_utils_io_patch",
    )
    try:

        def _snapshot() -> dict[str, object]:
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
        _emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.summary",
            selector_id=selector_id,
            backend="prompt_toolkit",
            **_snapshot(),
        )


def _selector_backend_decision(*, build_only: bool) -> tuple[bool, dict[str, object]]:
    info: dict[str, object] = {"build_only": bool(build_only)}
    can_tty = can_interactive_tty()
    ptk_available = prompt_toolkit_available()
    backend_pref = str(os.environ.get("ENVCTL_UI_SELECTOR_BACKEND", "")).strip().lower()
    raw_ptk = str(os.environ.get("ENVCTL_UI_PROMPT_TOOLKIT", "")).strip().lower()
    info["can_interactive_tty"] = bool(can_tty)
    info["prompt_toolkit_available"] = bool(ptk_available)
    info["env_selector_backend"] = backend_pref
    info["env_ui_prompt_toolkit"] = raw_ptk

    if build_only:
        info["reason"] = "build_only"
        info["backend"] = "textual"
        return False, info
    if backend_pref in {"textual", "tui"}:
        info["reason"] = "env_forced_textual"
        info["backend"] = "textual"
        return False, info
    if backend_pref in {"prompt_toolkit", "prompt-toolkit", "ptk"}:
        enabled = can_tty and ptk_available
        info["reason"] = "env_forced_prompt_toolkit"
        info["backend"] = "prompt_toolkit" if enabled else "textual"
        return enabled, info
    if raw_ptk in {"1", "true", "yes", "on"}:
        enabled = can_tty and ptk_available
        info["reason"] = "env_prompt_toolkit_enabled"
        info["backend"] = "prompt_toolkit" if enabled else "textual"
        return enabled, info
    if not can_tty:
        info["reason"] = "non_tty"
        info["backend"] = "textual"
        return False, info
    if raw_ptk in {"0", "false", "no", "off"}:
        info["reason"] = "env_prompt_toolkit_disabled"
        info["backend"] = "textual"
        return False, info
    if ptk_available:
        info["reason"] = "default_prompt_toolkit"
        info["backend"] = "prompt_toolkit"
        return True, info
    info["reason"] = "default_textual_prompt_toolkit_missing"
    info["backend"] = "textual"
    return False, info


def _emit_selector_debug(
    emit: Callable[..., None] | None,
    *,
    enabled: bool,
    event: str,
    **payload: object,
) -> None:
    if not enabled:
        return
    _emit(emit, event, **payload)
