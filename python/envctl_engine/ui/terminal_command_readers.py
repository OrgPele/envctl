from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TerminalCommandReaderDeps:
    environ: Mapping[str, str]
    stdin: Any
    stdout: Any
    stdout_fallback: Any
    can_interactive_tty: Callable[[], bool]
    os_isatty: Callable[[int], bool]
    stdin_fileno: Callable[[], int]
    open_tty: Callable[[str], Any]
    ensure_tty_line_mode: Callable[..., None]
    discard_stale_control_sequences: Callable[..., int]
    read_line_from_fd_graceful: Callable[..., tuple[str, int]]
    read_line_from_fd: Callable[..., str]
    read_command_line_fallback: Callable[..., str] | None
    basic_input_fd_enabled: Callable[[], bool]
    restore_terminal_after_input: Callable[..., None]
    canonical_line_state: Callable[..., Any]
    record_input_bytes: Callable[..., None] | None = None


def read_command_line_fallback(
    prompt: str,
    env: Mapping[str, str],
    input_provider: Callable[[str], str],
    *,
    deps: TerminalCommandReaderDeps,
    emit: Callable[..., None] | None = None,
    debug_recorder: Any | None = None,
) -> str:
    if not deps.can_interactive_tty():
        if callable(emit):
            emit("ui.input.read.begin", component="ui.terminal_session", backend="fallback", non_tty=True)
        value = input_provider(prompt)
        if callable(emit):
            emit(
                "ui.input.read.end",
                component="ui.terminal_session",
                backend="fallback",
                bytes_read=len(str(value).encode("utf-8", errors="ignore")),
                non_tty=True,
            )
        return value

    tty_path = env.get("TTY_DEVICE") or deps.environ.get("TTY_DEVICE") or "/dev/tty"
    try:
        handle = deps.open_tty(tty_path)
    except OSError:
        return input_provider(prompt)
    fd = handle.fileno()
    if callable(emit):
        emit("ui.input.read.begin", component="ui.terminal_session", backend="fallback", tty_device=tty_path)
    if debug_recorder is not None:
        debug_recorder.write_tty_context(
            {
                "stdin_tty": bool(deps.stdin.isatty()),
                "stdout_tty": bool(deps.stdout.isatty()),
                "tty_device": tty_path,
                "term": deps.environ.get("TERM", ""),
            }
        )
    try:
        discarded_bytes = _discard_stale_input(
            fd=fd,
            deps=deps,
            emit=emit,
            debug_recorder=debug_recorder,
            backend="fallback",
        )
        deps.ensure_tty_line_mode(fd=fd)
        if debug_recorder is not None:
            debug_recorder.append_tty_state_transition(
                {
                    "event": "ui.tty.transition",
                    "action": "line_mode",
                    "discarded_bytes": discarded_bytes,
                }
            )
        deps.stdout.write(prompt)
        deps.stdout.flush()

        total_bytes = 0
        dropped_escape_sequences = 0
        source = "tty_graceful"

        def on_bytes(data: bytes) -> None:
            nonlocal total_bytes
            total_bytes += len(data)
            _record_input_bytes(deps, debug_recorder, data, backend="fallback")

        try:
            text, dropped_escape_sequences = deps.read_line_from_fd_graceful(
                fd,
                on_bytes=on_bytes,
                emit=emit,
            )
        except Exception:
            source = "tty_line"
            text = deps.read_line_from_fd(fd, on_bytes=on_bytes)
            dropped_escape_sequences = 0
        if callable(emit):
            emit(
                "ui.input.read.end",
                component="ui.terminal_session",
                backend="fallback",
                bytes_read=total_bytes,
                source=source,
                dropped_escape_sequences=dropped_escape_sequences,
            )
        return text
    finally:
        deps.restore_terminal_after_input(fd=fd, original_state=deps.canonical_line_state(fd=fd), emit=emit)
        try:
            handle.close()
        except Exception:
            pass


def read_command_line_basic(
    prompt: str,
    input_provider: Callable[[str], str],
    *,
    deps: TerminalCommandReaderDeps,
    env: Mapping[str, str] | None = None,
    input_provider_is_default: bool = False,
    emit: Callable[..., None] | None = None,
    debug_recorder: Any | None = None,
) -> str:
    if callable(emit):
        emit("ui.input.read.begin", component="ui.terminal_session", backend="basic_input")
    if debug_recorder is not None:
        debug_recorder.write_tty_context(
            {
                "stdin_tty": bool(deps.stdin.isatty()),
                "stdout_tty": bool(deps.stdout.isatty()),
                "term": deps.environ.get("TERM", ""),
                "backend": "basic_input",
            }
        )
    text = ""
    used_fd_reader = False
    used_tty_fallback = False
    if input_provider_is_default and deps.can_interactive_tty() and deps.basic_input_fd_enabled():
        try:
            fd = deps.stdin_fileno()
            if not deps.os_isatty(fd):
                raise OSError
            deps.ensure_tty_line_mode(fd=fd)
            deps.discard_stale_control_sequences(fd=fd)
            deps.stdout.write(prompt)
            deps.stdout.flush()
            total_bytes = 0

            def on_bytes(data: bytes) -> None:
                nonlocal total_bytes
                total_bytes += len(data)
                if _debug_mode(debug_recorder) == "deep":
                    _record_input_bytes(deps, debug_recorder, data, backend="basic_input")

            text, dropped_escape_sequences = deps.read_line_from_fd_graceful(
                fd,
                on_bytes=on_bytes,
                emit=emit,
            )
            used_fd_reader = True
            if callable(emit):
                emit(
                    "ui.input.read.end",
                    component="ui.terminal_session",
                    backend="basic_input",
                    bytes_read=total_bytes,
                    source="fd",
                    dropped_escape_sequences=dropped_escape_sequences,
                )
        except Exception:
            used_fd_reader = False

    if not used_fd_reader:
        if input_provider_is_default and deps.can_interactive_tty():
            try:
                fallback_reader = deps.read_command_line_fallback or read_command_line_fallback
                text = fallback_reader(
                    prompt,
                    (env or {}),
                    input_provider,
                    emit=emit,
                    debug_recorder=debug_recorder,
                )
                used_tty_fallback = True
            except Exception:
                used_tty_fallback = False

        if not used_tty_fallback:
            value = input_provider(prompt)
            text = str(value)
            if _debug_mode(debug_recorder) == "deep":
                _record_input_bytes(
                    deps,
                    debug_recorder,
                    (text + "\n").encode("utf-8", errors="ignore"),
                    backend="basic_input",
                )
            if callable(emit):
                emit(
                    "ui.input.read.end",
                    component="ui.terminal_session",
                    backend="basic_input",
                    bytes_read=len(text.encode("utf-8", errors="ignore")),
                    source="provider",
                )
        elif callable(emit):
            emit(
                "ui.input.read.end",
                component="ui.terminal_session",
                backend="basic_input",
                bytes_read=len(text.encode("utf-8", errors="ignore")),
                source="tty_fallback",
            )

    if _debug_mode(debug_recorder) == "deep":
        debug_recorder.append_tty_state_transition(
            {
                "event": "ui.tty.transition",
                "action": "basic_input_read",
                "source": ("fd" if used_fd_reader else ("tty_fallback" if used_tty_fallback else "provider")),
                "stdin_tty": bool(deps.stdin.isatty()),
            }
        )
    return text


def _discard_stale_input(
    *,
    fd: int,
    deps: TerminalCommandReaderDeps,
    emit: Callable[..., None] | None,
    debug_recorder: Any | None,
    backend: str,
) -> int:
    try:
        discarded_bytes = deps.discard_stale_control_sequences(fd=fd)
        if callable(emit):
            emit(
                "ui.input.flush",
                component="ui.terminal_session",
                backend=backend,
                result="ok",
                discarded_bytes=discarded_bytes,
            )
        return discarded_bytes
    except Exception:
        if callable(emit):
            emit(
                "ui.input.flush",
                component="ui.terminal_session",
                backend=backend,
                result="failed",
                discarded_bytes=0,
            )
        if debug_recorder is not None:
            debug_recorder.append_anomaly(
                {
                    "event": "ui.anomaly.tcflush_failed",
                    "severity": "low",
                    "backend": backend,
                }
            )
        return 0


def _debug_mode(debug_recorder: Any | None) -> str:
    return str(getattr(getattr(debug_recorder, "config", None), "mode", ""))


def _record_input_bytes(
    deps: TerminalCommandReaderDeps,
    debug_recorder: Any | None,
    data: bytes,
    *,
    backend: str,
) -> None:
    if deps.record_input_bytes is not None:
        deps.record_input_bytes(data, component="ui.terminal_session", backend=backend)
        return
    if debug_recorder is not None:
        debug_recorder.record_input_bytes(data, component="ui.terminal_session", backend=backend)


def basic_input_fd_enabled(environ: Mapping[str, str]) -> bool:
    raw = environ.get("ENVCTL_UI_BASIC_INPUT_FD")
    if raw is None:
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}
