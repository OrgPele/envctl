from __future__ import annotations

import codecs
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
import importlib
import os
import re
import select
import subprocess
import sys
import termios
import time
from typing import Any, cast

from envctl_engine.runtime.runtime_dependency_contract import python_dependency_available
from .capabilities import prompt_toolkit_disabled
from .debug_flight_recorder import DebugFlightRecorder

_PUSHBACK_BYTES: dict[int, bytearray] = {}


def can_interactive_tty() -> bool:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    term = os.environ.get("TERM", "")
    if term.strip().lower() == "dumb":
        return False
    return True


def prompt_toolkit_available() -> bool:
    return python_dependency_available("prompt_toolkit")


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


def _read_line_from_fd(
    fd: int,
    *,
    on_bytes: Callable[[bytes], None] | None = None,
) -> str:
    chunks: list[bytes] = []
    while True:
        data = _read_byte(fd=fd)
        if callable(on_bytes):
            on_bytes(data)
        if data == b"":
            raise EOFError
        if data in {b"\n", b"\r"}:
            _consume_paired_line_ending(fd=fd, first=data, on_bytes=on_bytes)
            _preserve_immediate_followup_input(fd=fd, on_bytes=on_bytes)
            break
        chunks.append(data)
    return b"".join(chunks).decode("utf-8", errors="ignore")


def _read_line_from_fd_graceful(
    fd: int,
    *,
    on_bytes: Callable[[bytes], None] | None = None,
    emit: Callable[..., None] | None = None,
) -> tuple[str, int]:
    try:
        original_state = termios.tcgetattr(fd)
    except Exception:
        return _read_line_from_fd(fd, on_bytes=on_bytes), 0

    if not _set_tty_character_mode(fd=fd, original_state=original_state):
        return _read_line_from_fd(fd, on_bytes=on_bytes), 0

    out = getattr(sys, "__stdout__", None) or sys.stdout
    write = getattr(out, "write", None)
    flush = getattr(out, "flush", None)
    decoder = codecs.getincrementaldecoder("utf-8")()
    text_chars: list[str] = []
    dropped_escape_sequences = 0
    try:
        while True:
            data = _read_byte(fd=fd)
            if callable(on_bytes):
                on_bytes(data)
            if data == b"":
                raise EOFError
            if data in {b"\n", b"\r"}:
                _consume_paired_line_ending(fd=fd, first=data, on_bytes=on_bytes)
                _preserve_immediate_followup_input(fd=fd, on_bytes=on_bytes)
                if callable(write):
                    write("\n")
                if callable(flush):
                    flush()
                return "".join(text_chars), dropped_escape_sequences
            if data == b"\x03":
                raise KeyboardInterrupt
            if data == b"\x04":
                if not text_chars:
                    raise EOFError
                continue
            if data in {b"\x7f", b"\x08"}:
                decoder.reset()
                if text_chars:
                    text_chars.pop()
                    if callable(write):
                        write("\b \b")
                    if callable(flush):
                        flush()
                continue
            if data == b"\x1b":
                sequence = _read_escape_sequence_nonblocking(fd=fd, on_bytes=on_bytes, timeout=0.025, max_bytes=64)
                printable = _decode_escape_printable(sequence)
                if printable is not None:
                    text_chars.append(printable)
                    if callable(write):
                        write(printable)
                    if callable(flush):
                        flush()
                else:
                    dropped_escape_sequences += 1
                decoder.reset()
                continue
            byte = int(data[0])
            if byte < 32 or byte == 127:
                decoder.reset()
                continue
            rendered = decoder.decode(data, final=False)
            if not rendered:
                continue
            for ch in rendered:
                if not ch.isprintable():
                    continue
                text_chars.append(ch)
                if callable(write):
                    write(ch)
            if callable(flush):
                flush()
    finally:
        restore_terminal_after_input(fd=fd, original_state=original_state, emit=emit)


def _consume_paired_line_ending(
    *,
    fd: int,
    first: bytes,
    on_bytes: Callable[[bytes], None] | None = None,
) -> None:
    """Drain a queued CR/LF counterpart so it doesn't become the next empty command."""
    counterpart = b"\n" if first == b"\r" else b"\r" if first == b"\n" else b""
    if not counterpart:
        return
    try:
        ready, _, _ = select.select([fd], [], [], 0)
    except Exception:
        return
    if not ready:
        return
    try:
        data = _read_byte(fd=fd)
    except Exception:
        return
    if data != counterpart:
        _pushback_byte(fd=fd, data=data)
        return
    if callable(on_bytes):
        on_bytes(data)


def _preserve_immediate_followup_input(
    *,
    fd: int,
    on_bytes: Callable[[bytes], None] | None = None,
    timeout: float = 0.35,
    max_bytes: int = 64,
) -> None:
    """Capture rapid post-Enter input so the next UI consumer can read it reliably.

    The dashboard -> selector handoff can take a short scheduling hop after the
    command line reader exits, especially under PTY-driven tests and during
    service-launch overlap. Keep a modest buffer window so immediate arrow bursts
    still reach the selector instead of getting stranded between consumers.
    """
    collected = bytearray()
    deadline = time.monotonic() + max(0.0, timeout)
    while len(collected) < max(1, max_bytes):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            ready, _, _ = select.select([fd], [], [], remaining)
        except Exception:
            break
        if not ready:
            break
        try:
            data = os.read(fd, 1)
        except Exception:
            break
        if not data:
            break
        collected.extend(data)
        if callable(on_bytes):
            on_bytes(data)
    if collected:
        _append_pushback_byte(fd=fd, data=bytes(collected))


def _read_byte(*, fd: int) -> bytes:
    queued = _PUSHBACK_BYTES.get(fd)
    if queued:
        value = bytes([queued.pop(0)])
        if not queued:
            _PUSHBACK_BYTES.pop(fd, None)
        return value
    return os.read(fd, 1)


def _pushback_byte(*, fd: int, data: bytes) -> None:
    if not data:
        return
    queued = _PUSHBACK_BYTES.get(fd)
    if queued is None:
        queued = bytearray()
        _PUSHBACK_BYTES[fd] = queued
    queued[:0] = data


def _append_pushback_byte(*, fd: int, data: bytes) -> None:
    if not data:
        return
    queued = _PUSHBACK_BYTES.get(fd)
    if queued is None:
        queued = bytearray()
        _PUSHBACK_BYTES[fd] = queued
    queued.extend(data)


def consume_preserved_input() -> bytes:
    if not _PUSHBACK_BYTES:
        return b""
    collected = bytearray()
    for fd in sorted(_PUSHBACK_BYTES):
        queued = _PUSHBACK_BYTES.get(fd)
        if queued:
            collected.extend(queued)
    _PUSHBACK_BYTES.clear()
    return bytes(collected)


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


def _read_escape_sequence_nonblocking(
    *,
    fd: int,
    on_bytes: Callable[[bytes], None] | None = None,
    timeout: float,
    max_bytes: int,
) -> bytes:
    collected = bytearray()
    deadline = time.monotonic() + max(0.0, timeout)
    while len(collected) < max(1, max_bytes):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            ready, _, _ = select.select([fd], [], [], remaining)
        except Exception:
            break
        if not ready:
            break
        try:
            chunk = _read_byte(fd=fd)
        except Exception:
            break
        if callable(on_bytes):
            on_bytes(chunk)
        if not chunk:
            break
        collected.extend(chunk)
        if _escape_sequence_complete(bytes(collected)):
            break
    return bytes(collected)


def _discard_stale_control_sequences(
    *,
    fd: int,
    on_bytes: Callable[[bytes], None] | None = None,
    max_bytes: int = 64,
) -> int:
    """Discard queued control / escape residue without dropping printable user input."""
    if max_bytes <= 0:
        return 0
    discarded = 0
    while discarded < max_bytes:
        try:
            ready, _, _ = select.select([fd], [], [], 0)
        except Exception:
            break
        if not ready:
            break
        try:
            data = _read_byte(fd=fd)
        except Exception:
            break
        if not data:
            break
        if callable(on_bytes):
            on_bytes(data)
        byte = int(data[0])
        if data in {b"\n", b"\r"} or byte < 32 or byte == 127:
            discarded += 1
            if data == b"\x1b":
                sequence = _read_escape_sequence_nonblocking(
                    fd=fd,
                    on_bytes=on_bytes,
                    timeout=0.001,
                    max_bytes=max(1, max_bytes - discarded),
                )
                discarded += len(sequence)
            continue
        _pushback_byte(fd=fd, data=data)
        break
    return discarded


def _escape_sequence_complete(sequence: bytes) -> bool:
    if not sequence:
        return False
    first = sequence[0]
    if first not in {ord("["), ord("O")}:
        return True
    if len(sequence) == 1:
        return False
    last = int(sequence[-1])
    return 0x40 <= last <= 0x7E


def _decode_escape_printable(sequence: bytes) -> str | None:
    if not sequence:
        return None
    text = sequence.decode("latin-1", errors="ignore")
    if not text:
        return None
    # Meta/alt key style: ESC + printable.
    if len(text) == 1 and " " <= text <= "~":
        return text
    # Kitty keyboard / CSI-u style: ESC [113u (q), ESC [65u (A), optionally with modifiers.
    if text.startswith("[") and text.endswith("u"):
        body = text[1:-1]
        match = re.fullmatch(r"([0-9]{1,6})(?:;[0-9]{1,6})*", body)
        if not match:
            return None
        codepoint = int(match.group(1))
        if 32 <= codepoint <= 126:
            return chr(codepoint)
    return None


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


def _read_command_line_fallback(
    prompt: str,
    env: Mapping[str, str],
    input_provider: Callable[[str], str],
    *,
    emit: Callable[..., None] | None = None,
    debug_recorder: DebugFlightRecorder | None = None,
) -> str:
    if not can_interactive_tty():
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
    tty_path = env.get("TTY_DEVICE") or os.environ.get("TTY_DEVICE") or "/dev/tty"
    try:
        handle = open(tty_path, "rb", buffering=0)
    except OSError:
        return input_provider(prompt)
    fd = handle.fileno()
    if callable(emit):
        emit("ui.input.read.begin", component="ui.terminal_session", backend="fallback", tty_device=tty_path)
    if debug_recorder is not None:
        debug_recorder.write_tty_context(
            {
                "stdin_tty": bool(sys.stdin.isatty()),
                "stdout_tty": bool(sys.stdout.isatty()),
                "tty_device": tty_path,
                "term": os.environ.get("TERM", ""),
            }
        )
    try:
        discarded_bytes = 0
        try:
            discarded_bytes = _discard_stale_control_sequences(fd=fd)
            if callable(emit):
                emit(
                    "ui.input.flush",
                    component="ui.terminal_session",
                    backend="fallback",
                    result="ok",
                    discarded_bytes=discarded_bytes,
                )
        except Exception:
            if callable(emit):
                emit(
                    "ui.input.flush",
                    component="ui.terminal_session",
                    backend="fallback",
                    result="failed",
                    discarded_bytes=0,
                )
            if debug_recorder is not None:
                debug_recorder.append_anomaly(
                    {
                        "event": "ui.anomaly.tcflush_failed",
                        "severity": "low",
                        "backend": "fallback",
                    }
                )
        _ensure_tty_line_mode(fd=fd)
        if debug_recorder is not None:
            debug_recorder.append_tty_state_transition(
                {
                    "event": "ui.tty.transition",
                    "action": "line_mode",
                    "discarded_bytes": discarded_bytes,
                }
            )
        sys.stdout.write(prompt)
        sys.stdout.flush()

        total_bytes = 0
        dropped_escape_sequences = 0
        source = "tty_graceful"

        def on_bytes(data: bytes) -> None:
            nonlocal total_bytes
            total_bytes += len(data)
            if debug_recorder is not None:
                debug_recorder.record_input_bytes(data, component="ui.terminal_session", backend="fallback")

        try:
            text, dropped_escape_sequences = _read_line_from_fd_graceful(
                fd,
                on_bytes=on_bytes,
                emit=emit,
            )
        except Exception:
            source = "tty_line"
            text = _read_line_from_fd(fd, on_bytes=on_bytes)
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
        restore_terminal_after_input(fd=fd, original_state=_canonical_line_state(fd=fd), emit=emit)
        try:
            handle.close()
        except Exception:
            pass


def _read_command_line_basic(
    prompt: str,
    input_provider: Callable[[str], str],
    *,
    env: Mapping[str, str] | None = None,
    input_provider_is_default: bool = False,
    emit: Callable[..., None] | None = None,
    debug_recorder: DebugFlightRecorder | None = None,
) -> str:
    if callable(emit):
        emit("ui.input.read.begin", component="ui.terminal_session", backend="basic_input")
    if debug_recorder is not None:
        debug_recorder.write_tty_context(
            {
                "stdin_tty": bool(sys.stdin.isatty()),
                "stdout_tty": bool(sys.stdout.isatty()),
                "term": os.environ.get("TERM", ""),
                "backend": "basic_input",
            }
        )
    text = ""
    used_fd_reader = False
    used_tty_fallback = False
    if input_provider_is_default and can_interactive_tty() and _basic_input_fd_enabled():
        try:
            fd = sys.stdin.fileno()
            if not os.isatty(fd):
                raise OSError
            _ensure_tty_line_mode(fd=fd)
            _discard_stale_control_sequences(fd=fd)
            sys.stdout.write(prompt)
            sys.stdout.flush()
            total_bytes = 0

            def on_bytes(data: bytes) -> None:
                nonlocal total_bytes
                total_bytes += len(data)
                if debug_recorder is not None and debug_recorder.config.mode == "deep":
                    debug_recorder.record_input_bytes(
                        data,
                        component="ui.terminal_session",
                        backend="basic_input",
                    )

            text, dropped_escape_sequences = _read_line_from_fd_graceful(
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
        if input_provider_is_default and can_interactive_tty():
            try:
                text = _read_command_line_fallback(
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
            if debug_recorder is not None and debug_recorder.config.mode == "deep":
                # Preserve deep-mode input signal without switching to raw /dev/tty fallback.
                debug_recorder.record_input_bytes(
                    (text + "\n").encode("utf-8", errors="ignore"),
                    component="ui.terminal_session",
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

    if debug_recorder is not None and debug_recorder.config.mode == "deep":
        debug_recorder.append_tty_state_transition(
            {
                "event": "ui.tty.transition",
                "action": "basic_input_read",
                "source": ("fd" if used_fd_reader else ("tty_fallback" if used_tty_fallback else "provider")),
                "stdin_tty": bool(sys.stdin.isatty()),
            }
        )
    return text


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
        _clear_pendin(fd=fd, emit=emit, component=component)


@contextmanager
def temporary_standard_output_pendin(
    *,
    emit: Callable[..., None] | None = None,
    component: str = "ui.terminal_session",
) -> Iterator[None]:
    touched: list[tuple[int, list[int]]] = []
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
