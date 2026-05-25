from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
import importlib
import os
import select
import sys
import termios
from typing import cast

from envctl_engine.runtime.runtime_dependency_contract import python_dependency_available
from . import terminal_input_stream
from .capabilities import prompt_toolkit_disabled
from .terminal_command_readers import (
    TerminalCommandReaderDeps,
    read_command_line_basic,
    read_command_line_fallback,
)
from .debug_flight_recorder import DebugFlightRecorder
from .terminal_tty_modes import (
    _canonical_line_state as _canonical_line_state,
    _clear_pendin as _clear_pendin,
    _clear_standard_tty_pendin as _clear_standard_tty_pendin,
    _ensure_tty_line_mode as _ensure_tty_line_mode,
    _set_pendin as _set_pendin,
    _set_tty_character_mode as _set_tty_character_mode,
    _strip_pendin as _strip_pendin,
    normalize_standard_tty_state as normalize_standard_tty_state,
    restore_terminal_after_input as restore_terminal_after_input,
    temporary_standard_output_pendin as temporary_standard_output_pendin,
    temporary_tty_character_mode as temporary_tty_character_mode,
)

_PUSHBACK_BYTES = terminal_input_stream.DEFAULT_INPUT_BUFFER.pushback_bytes


def can_interactive_tty() -> bool:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    term = os.environ.get("TERM", "")
    if term.strip().lower() == "dumb":
        return False
    return True


def prompt_toolkit_available() -> bool:
    return python_dependency_available("prompt_toolkit")


def _read_line_from_fd(
    fd: int,
    *,
    on_bytes: Callable[[bytes], None] | None = None,
) -> str:
    return terminal_input_stream.read_line_from_fd(fd, on_bytes=on_bytes, read_fn=os.read, select_fn=select.select)


def _read_line_from_fd_graceful(
    fd: int,
    *,
    on_bytes: Callable[[bytes], None] | None = None,
    emit: Callable[..., None] | None = None,
) -> tuple[str, int]:
    return terminal_input_stream.read_line_from_fd_graceful(
        fd,
        on_bytes=on_bytes,
        emit=emit,
        read_fn=os.read,
        select_fn=select.select,
        stdout=(getattr(sys, "__stdout__", None) or sys.stdout),
        tcgetattr=termios.tcgetattr,
        set_character_mode=_set_tty_character_mode,
        restore_input=restore_terminal_after_input,
    )


def _consume_paired_line_ending(
    *,
    fd: int,
    first: bytes,
    on_bytes: Callable[[bytes], None] | None = None,
) -> None:
    terminal_input_stream.DEFAULT_INPUT_BUFFER.consume_paired_line_ending(
        fd=fd,
        first=first,
        on_bytes=on_bytes,
        read_fn=os.read,
        select_fn=select.select,
    )


def _preserve_immediate_followup_input(
    *,
    fd: int,
    on_bytes: Callable[[bytes], None] | None = None,
    timeout: float = 0.35,
    max_bytes: int = 64,
) -> None:
    terminal_input_stream.DEFAULT_INPUT_BUFFER.preserve_immediate_followup_input(
        fd=fd,
        on_bytes=on_bytes,
        timeout=timeout,
        max_bytes=max_bytes,
        read_fn=os.read,
        select_fn=select.select,
    )


def _read_byte(*, fd: int) -> bytes:
    return terminal_input_stream.DEFAULT_INPUT_BUFFER.read_byte(fd=fd, read_fn=os.read)


def _pushback_byte(*, fd: int, data: bytes) -> None:
    terminal_input_stream.DEFAULT_INPUT_BUFFER.pushback_byte(fd=fd, data=data)


def _append_pushback_byte(*, fd: int, data: bytes) -> None:
    terminal_input_stream.DEFAULT_INPUT_BUFFER.append_pushback_byte(fd=fd, data=data)


def consume_preserved_input() -> bytes:
    return terminal_input_stream.DEFAULT_INPUT_BUFFER.consume_preserved_input()


def _read_escape_sequence_nonblocking(
    *,
    fd: int,
    on_bytes: Callable[[bytes], None] | None = None,
    timeout: float,
    max_bytes: int,
) -> bytes:
    return terminal_input_stream.DEFAULT_INPUT_BUFFER.read_escape_sequence_nonblocking(
        fd=fd,
        on_bytes=on_bytes,
        timeout=timeout,
        max_bytes=max_bytes,
        read_fn=os.read,
        select_fn=select.select,
    )


def _discard_stale_control_sequences(
    *,
    fd: int,
    on_bytes: Callable[[bytes], None] | None = None,
    max_bytes: int = 64,
) -> int:
    return terminal_input_stream.discard_stale_control_sequences(
        fd=fd,
        on_bytes=on_bytes,
        max_bytes=max_bytes,
        read_fn=os.read,
        select_fn=select.select,
    )


def _escape_sequence_complete(sequence: bytes) -> bool:
    return terminal_input_stream.escape_sequence_complete(sequence)


def _decode_escape_printable(sequence: bytes) -> str | None:
    return terminal_input_stream.decode_escape_printable(sequence)


def _prompt_toolkit_prompt(prompt: str) -> str:
    module = importlib.import_module("prompt_toolkit")
    pt_prompt = cast(Callable[[str], str], getattr(module, "prompt"))
    with _prompt_toolkit_no_cpr():
        return pt_prompt(prompt)


@contextmanager
def _prompt_toolkit_no_cpr() -> Iterator[None]:
    key = "PROMPT_TOOLKIT_NO_CPR"
    previous = os.environ.get(key)
    os.environ[key] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def _terminal_command_reader_deps() -> TerminalCommandReaderDeps:
    return TerminalCommandReaderDeps(
        environ=os.environ,
        stdin=sys.stdin,
        stdout=sys.stdout,
        stdout_fallback=(getattr(sys, "__stdout__", None) or sys.stdout),
        can_interactive_tty=can_interactive_tty,
        os_isatty=os.isatty,
        stdin_fileno=sys.stdin.fileno,
        open_tty=lambda tty_path: open(tty_path, "rb", buffering=0),
        ensure_tty_line_mode=_ensure_tty_line_mode,
        discard_stale_control_sequences=_discard_stale_control_sequences,
        read_line_from_fd_graceful=_read_line_from_fd_graceful,
        read_line_from_fd=_read_line_from_fd,
        read_command_line_fallback=_read_command_line_fallback,
        basic_input_fd_enabled=_basic_input_fd_enabled,
        restore_terminal_after_input=restore_terminal_after_input,
        canonical_line_state=_canonical_line_state,
    )


def _read_command_line_fallback(
    prompt: str,
    env: Mapping[str, str],
    input_provider: Callable[[str], str],
    *,
    emit: Callable[..., None] | None = None,
    debug_recorder: DebugFlightRecorder | None = None,
) -> str:
    return read_command_line_fallback(
        prompt,
        env,
        input_provider,
        deps=_terminal_command_reader_deps(),
        emit=emit,
        debug_recorder=debug_recorder,
    )


def _read_command_line_basic(
    prompt: str,
    input_provider: Callable[[str], str],
    *,
    env: Mapping[str, str] | None = None,
    input_provider_is_default: bool = False,
    emit: Callable[..., None] | None = None,
    debug_recorder: DebugFlightRecorder | None = None,
) -> str:
    return read_command_line_basic(
        prompt,
        input_provider,
        deps=_terminal_command_reader_deps(),
        env=env,
        input_provider_is_default=input_provider_is_default,
        emit=emit,
        debug_recorder=debug_recorder,
    )


class TerminalSession:
    def __init__(
        self,
        env: Mapping[str, str],
        *,
        input_provider: Callable[[str], str] | None = None,
        prefer_basic_input: bool = False,
        emit: Callable[..., None] | None = None,
        debug_recorder: DebugFlightRecorder | None = None,
    ) -> None:
        self.env: Mapping[str, str] = env
        self._input_provider: Callable[[str], str] = input_provider or input
        self._input_provider_is_default: bool = input_provider is None
        self._prefer_basic_input: bool = prefer_basic_input
        self._emit: Callable[..., None] | None = emit
        self._debug_recorder: DebugFlightRecorder | None = debug_recorder

    def read_command_line(self, prompt: str) -> str:
        if not can_interactive_tty():
            if self._debug_recorder is not None:
                self._debug_recorder.write_tty_context(
                    {
                        "stdin_tty": bool(sys.stdin.isatty()),
                        "stdout_tty": bool(sys.stdout.isatty()),
                        "term": os.environ.get("TERM", ""),
                        "backend": "fallback",
                    }
                )
            if self._emit is not None:
                self._emit("ui.input.read.begin", component="ui.terminal_session", backend="fallback", non_tty=True)
            text = self._normalize_command(self._input_provider(prompt))
            if self._emit is not None:
                self._emit(
                    "ui.input.read.end",
                    component="ui.terminal_session",
                    backend="fallback",
                    bytes_read=len(text.encode("utf-8", errors="ignore")),
                )
            self._emit_backend("fallback")
            return text
        _restore_stdin_terminal_sane(emit=self._emit)
        force_basic = (
            self._prefer_basic_input or _force_basic_input_backend(self.env) or prompt_toolkit_disabled(self.env)
        )
        if force_basic:
            text = _read_command_line_basic(
                prompt,
                self._input_provider,
                env=self.env,
                input_provider_is_default=self._input_provider_is_default,
                emit=self._emit,
                debug_recorder=self._debug_recorder,
            )
            normalized = self._normalize_command(text)
            self._emit_backend("basic_input")
            return normalized
        if prompt_toolkit_available():
            try:
                if self._emit is not None:
                    self._emit("ui.input.read.begin", component="ui.terminal_session", backend="prompt_toolkit")
                text = _prompt_toolkit_prompt(prompt)
                normalized = self._normalize_command(text)
                if self._emit is not None:
                    self._emit(
                        "ui.input.read.end",
                        component="ui.terminal_session",
                        backend="prompt_toolkit",
                        bytes_read=len(text.encode("utf-8", errors="ignore")),
                    )
                self._emit_backend("prompt_toolkit")
                return normalized
            except Exception:
                pass
        text = _read_command_line_fallback(
            prompt,
            self.env,
            self._input_provider,
            emit=self._emit,
            debug_recorder=self._debug_recorder,
        )
        normalized = self._normalize_command(text)
        self._emit_backend("fallback")
        return normalized

    def _emit_backend(self, backend: str) -> None:
        emit = self._emit
        if emit is None:
            return
        try:
            emit("ui.input.backend", backend=backend)
        except Exception:
            return

    @staticmethod
    def _normalize_command(value: object) -> str:
        if not isinstance(value, str):
            return ""
        return value.replace("\r", "").replace("\n", "")


def _restore_stdin_terminal_sane(*, emit: Callable[..., None] | None = None) -> None:
    if not can_interactive_tty():
        return
    try:
        fd = sys.stdin.fileno()
    except (OSError, ValueError):
        return
    _ensure_tty_line_mode(fd=fd)
    _reset_terminal_escape_modes(emit=emit)


def _reset_terminal_escape_modes(*, emit: Callable[..., None] | None = None) -> None:
    mode_raw = str(os.environ.get("ENVCTL_UI_RESET_ESCAPE_MODES", "auto")).strip().lower()
    if mode_raw in {"0", "false", "no", "off"}:
        return
    if mode_raw not in {"1", "true", "yes", "on"}:
        if str(os.environ.get("TERM_PROGRAM", "")) != "Apple_Terminal":
            return
    try:
        out = getattr(sys, "__stdout__", None) or sys.stdout
        write = getattr(out, "write", None)
        flush = getattr(out, "flush", None)
        if not callable(write):
            return
        # Ensure stale tracking / protocol modes from prior TUI sessions are disabled.
        # Also restore cursor and keypad modes for shell line editing.
        write(
            "\x1b[?1l\x1b>\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1005l\x1b[?1006l\x1b[?1004l\x1b[<u\x1b[?2004l\x1b[?25h"
        )
        if callable(flush):
            flush()
        if callable(emit):
            emit(
                "ui.tty.transition",
                component="ui.terminal_session",
                action="reset_escape_modes",
                result="ok",
            )
    except Exception as exc:
        if callable(emit):
            emit(
                "ui.tty.transition",
                component="ui.terminal_session",
                action="reset_escape_modes",
                result="failed",
                error=type(exc).__name__,
            )


def _force_basic_input_backend(env: Mapping[str, str]) -> bool:
    raw = env.get("ENVCTL_UI_BASIC_INPUT")
    if raw is None:
        raw = os.environ.get("ENVCTL_UI_BASIC_INPUT")
    if raw is None:
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _basic_input_fd_enabled() -> bool:
    raw = os.environ.get("ENVCTL_UI_BASIC_INPUT_FD")
    if raw is None:
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}
