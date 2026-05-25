from __future__ import annotations

import codecs
from collections.abc import Callable
import os
import re
import select
import sys
import termios
import time
from typing import Any

from .terminal_tty_modes import restore_terminal_after_input

ReadFn = Callable[[int, int], bytes]
SelectFn = Callable[[list[int], list[int], list[int], float], tuple[list[int], list[int], list[int]]]


class TerminalInputBuffer:
    def __init__(self) -> None:
        self.pushback_bytes: dict[int, bytearray] = {}

    def read_byte(self, *, fd: int, read_fn: ReadFn = os.read) -> bytes:
        queued = self.pushback_bytes.get(fd)
        if queued:
            value = bytes([queued.pop(0)])
            if not queued:
                self.pushback_bytes.pop(fd, None)
            return value
        return read_fn(fd, 1)

    def pushback_byte(self, *, fd: int, data: bytes) -> None:
        if not data:
            return
        queued = self.pushback_bytes.get(fd)
        if queued is None:
            queued = bytearray()
            self.pushback_bytes[fd] = queued
        queued[:0] = data

    def append_pushback_byte(self, *, fd: int, data: bytes) -> None:
        if not data:
            return
        queued = self.pushback_bytes.get(fd)
        if queued is None:
            queued = bytearray()
            self.pushback_bytes[fd] = queued
        queued.extend(data)

    def consume_preserved_input(self) -> bytes:
        if not self.pushback_bytes:
            return b""
        collected = bytearray()
        for fd in sorted(self.pushback_bytes):
            queued = self.pushback_bytes.get(fd)
            if queued:
                collected.extend(queued)
        self.pushback_bytes.clear()
        return bytes(collected)

    def read_line_from_fd(
        self,
        fd: int,
        *,
        on_bytes: Callable[[bytes], None] | None = None,
        read_fn: ReadFn = os.read,
        select_fn: SelectFn = select.select,
    ) -> str:
        chunks: list[bytes] = []
        while True:
            data = self.read_byte(fd=fd, read_fn=read_fn)
            if callable(on_bytes):
                on_bytes(data)
            if data == b"":
                raise EOFError
            if data in {b"\n", b"\r"}:
                self.consume_paired_line_ending(
                    fd=fd,
                    first=data,
                    on_bytes=on_bytes,
                    read_fn=read_fn,
                    select_fn=select_fn,
                )
                self.preserve_immediate_followup_input(
                    fd=fd,
                    on_bytes=on_bytes,
                    read_fn=read_fn,
                    select_fn=select_fn,
                )
                break
            chunks.append(data)
        return b"".join(chunks).decode("utf-8", errors="ignore")

    def read_line_from_fd_graceful(
        self,
        fd: int,
        *,
        on_bytes: Callable[[bytes], None] | None = None,
        emit: Callable[..., None] | None = None,
        read_fn: ReadFn = os.read,
        select_fn: SelectFn = select.select,
        stdout: Any | None = None,
        tcgetattr: Callable[[int], Any] = termios.tcgetattr,
        set_character_mode: Callable[..., bool] | None = None,
        restore_input: Callable[..., None] = restore_terminal_after_input,
    ) -> tuple[str, int]:
        try:
            original_state = tcgetattr(fd)
        except Exception:
            return self.read_line_from_fd(fd, on_bytes=on_bytes, read_fn=read_fn, select_fn=select_fn), 0

        if set_character_mode is None or not set_character_mode(fd=fd, original_state=original_state):
            return self.read_line_from_fd(fd, on_bytes=on_bytes, read_fn=read_fn, select_fn=select_fn), 0

        out = stdout if stdout is not None else (getattr(sys, "__stdout__", None) or sys.stdout)
        write = getattr(out, "write", None)
        flush = getattr(out, "flush", None)
        decoder = codecs.getincrementaldecoder("utf-8")()
        text_chars: list[str] = []
        dropped_escape_sequences = 0
        try:
            while True:
                data = self.read_byte(fd=fd, read_fn=read_fn)
                if callable(on_bytes):
                    on_bytes(data)
                if data == b"":
                    raise EOFError
                if data in {b"\n", b"\r"}:
                    self.consume_paired_line_ending(
                        fd=fd,
                        first=data,
                        on_bytes=on_bytes,
                        read_fn=read_fn,
                        select_fn=select_fn,
                    )
                    self.preserve_immediate_followup_input(
                        fd=fd,
                        on_bytes=on_bytes,
                        read_fn=read_fn,
                        select_fn=select_fn,
                    )
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
                    sequence = self.read_escape_sequence_nonblocking(
                        fd=fd,
                        on_bytes=on_bytes,
                        timeout=0.025,
                        max_bytes=64,
                        read_fn=read_fn,
                        select_fn=select_fn,
                    )
                    printable = decode_escape_printable(sequence)
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
            restore_input(fd=fd, original_state=original_state, emit=emit)

    def consume_paired_line_ending(
        self,
        *,
        fd: int,
        first: bytes,
        on_bytes: Callable[[bytes], None] | None = None,
        read_fn: ReadFn = os.read,
        select_fn: SelectFn = select.select,
    ) -> None:
        counterpart = b"\n" if first == b"\r" else b"\r" if first == b"\n" else b""
        if not counterpart:
            return
        try:
            ready, _, _ = select_fn([fd], [], [], 0)
        except Exception:
            return
        if not ready:
            return
        try:
            data = self.read_byte(fd=fd, read_fn=read_fn)
        except Exception:
            return
        if data != counterpart:
            self.pushback_byte(fd=fd, data=data)
            return
        if callable(on_bytes):
            on_bytes(data)

    def preserve_immediate_followup_input(
        self,
        *,
        fd: int,
        on_bytes: Callable[[bytes], None] | None = None,
        timeout: float = 0.35,
        max_bytes: int = 64,
        read_fn: ReadFn = os.read,
        select_fn: SelectFn = select.select,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        collected = bytearray()
        deadline = monotonic_fn() + max(0.0, timeout)
        while len(collected) < max(1, max_bytes):
            remaining = deadline - monotonic_fn()
            if remaining <= 0:
                break
            try:
                ready, _, _ = select_fn([fd], [], [], remaining)
            except Exception:
                break
            if not ready:
                break
            try:
                data = read_fn(fd, 1)
            except Exception:
                break
            if not data:
                break
            collected.extend(data)
            if callable(on_bytes):
                on_bytes(data)
        if collected:
            self.append_pushback_byte(fd=fd, data=bytes(collected))

    def read_escape_sequence_nonblocking(
        self,
        *,
        fd: int,
        on_bytes: Callable[[bytes], None] | None = None,
        timeout: float,
        max_bytes: int,
        read_fn: ReadFn = os.read,
        select_fn: SelectFn = select.select,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ) -> bytes:
        collected = bytearray()
        deadline = monotonic_fn() + max(0.0, timeout)
        while len(collected) < max(1, max_bytes):
            remaining = deadline - monotonic_fn()
            if remaining <= 0:
                break
            try:
                ready, _, _ = select_fn([fd], [], [], remaining)
            except Exception:
                break
            if not ready:
                break
            try:
                chunk = self.read_byte(fd=fd, read_fn=read_fn)
            except Exception:
                break
            if callable(on_bytes):
                on_bytes(chunk)
            if not chunk:
                break
            collected.extend(chunk)
            if escape_sequence_complete(bytes(collected)):
                break
        return bytes(collected)

    def discard_stale_control_sequences(
        self,
        *,
        fd: int,
        on_bytes: Callable[[bytes], None] | None = None,
        max_bytes: int = 64,
        read_fn: ReadFn = os.read,
        select_fn: SelectFn = select.select,
    ) -> int:
        if max_bytes <= 0:
            return 0
        discarded = 0
        while discarded < max_bytes:
            try:
                ready, _, _ = select_fn([fd], [], [], 0)
            except Exception:
                break
            if not ready:
                break
            try:
                data = self.read_byte(fd=fd, read_fn=read_fn)
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
                    sequence = self.read_escape_sequence_nonblocking(
                        fd=fd,
                        on_bytes=on_bytes,
                        timeout=0.001,
                        max_bytes=max(1, max_bytes - discarded),
                        read_fn=read_fn,
                        select_fn=select_fn,
                    )
                    discarded += len(sequence)
                continue
            self.pushback_byte(fd=fd, data=data)
            break
        return discarded


def escape_sequence_complete(sequence: bytes) -> bool:
    if not sequence:
        return False
    first = sequence[0]
    if first not in {ord("["), ord("O")}:
        return True
    if len(sequence) == 1:
        return False
    last = int(sequence[-1])
    return 0x40 <= last <= 0x7E


def decode_escape_printable(sequence: bytes) -> str | None:
    if not sequence:
        return None
    text = sequence.decode("latin-1", errors="ignore")
    if not text:
        return None
    if len(text) == 1 and " " <= text <= "~":
        return text
    if text.startswith("[") and text.endswith("u"):
        body = text[1:-1]
        match = re.fullmatch(r"([0-9]{1,6})(?:;[0-9]{1,6})*", body)
        if not match:
            return None
        codepoint = int(match.group(1))
        if 32 <= codepoint <= 126:
            return chr(codepoint)
    return None


DEFAULT_INPUT_BUFFER = TerminalInputBuffer()


def read_line_from_fd(
    fd: int,
    *,
    on_bytes: Callable[[bytes], None] | None = None,
    read_fn: ReadFn = os.read,
    select_fn: SelectFn = select.select,
) -> str:
    return DEFAULT_INPUT_BUFFER.read_line_from_fd(fd, on_bytes=on_bytes, read_fn=read_fn, select_fn=select_fn)


def read_line_from_fd_graceful(
    fd: int,
    *,
    on_bytes: Callable[[bytes], None] | None = None,
    emit: Callable[..., None] | None = None,
    read_fn: ReadFn = os.read,
    select_fn: SelectFn = select.select,
    stdout: Any | None = None,
    tcgetattr: Callable[[int], Any] = termios.tcgetattr,
    set_character_mode: Callable[..., bool] | None = None,
    restore_input: Callable[..., None] = restore_terminal_after_input,
) -> tuple[str, int]:
    return DEFAULT_INPUT_BUFFER.read_line_from_fd_graceful(
        fd,
        on_bytes=on_bytes,
        emit=emit,
        read_fn=read_fn,
        select_fn=select_fn,
        stdout=stdout,
        tcgetattr=tcgetattr,
        set_character_mode=set_character_mode,
        restore_input=restore_input,
    )


def discard_stale_control_sequences(
    *,
    fd: int,
    on_bytes: Callable[[bytes], None] | None = None,
    max_bytes: int = 64,
    read_fn: ReadFn = os.read,
    select_fn: SelectFn = select.select,
) -> int:
    return DEFAULT_INPUT_BUFFER.discard_stale_control_sequences(
        fd=fd,
        on_bytes=on_bytes,
        max_bytes=max_bytes,
        read_fn=read_fn,
        select_fn=select_fn,
    )
