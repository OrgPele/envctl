from __future__ import annotations

import os
import re
import subprocess
import termios
import time
from typing import Any, Callable, cast


def read_planning_menu_key(*, fd: int, selector: Callable[..., object]) -> str:
    first = os.read(fd, 1)
    if not first:
        return "noop"
    mapped = map_single_byte_key(first)
    if mapped is not None:
        return mapped
    if first in {b"[", b"O"}:
        return "noop"
    if first != b"\x1b":
        return "noop"

    sequence = read_escape_sequence(fd=fd, selector=selector, timeout=0.03, max_bytes=16)
    if not sequence:
        return "esc"
    decoded = decode_escape(sequence)
    if decoded is not None:
        return decoded
    printable = decode_modified_printable(sequence)
    if printable is not None:
        mapped_printable = map_single_byte_key(printable.encode("latin-1", errors="ignore"))
        if mapped_printable is not None:
            return mapped_printable
    return "noop"


def map_single_byte_key(first: bytes) -> str | None:
    if first in {b"\r", b"\n"}:
        return "enter"
    if first == b" ":
        return "space"
    if first in {b"q", b"Q", b"\x03"}:
        return "quit"
    if first in {b"a", b"A"}:
        return "all"
    if first in {b"n", b"N"}:
        return "none"
    if first in {b"k", b"K", b"w", b"W"}:
        return "up"
    if first in {b"j", b"J", b"s", b"S"}:
        return "down"
    if first in {b"h", b"H"}:
        return "left"
    if first in {b"l", b"L", b"d", b"D"}:
        return "right"
    if first in {b"x", b"X", b"t", b"T"}:
        return "space"
    if first in {b"+", b"="}:
        return "inc"
    if first in {b"-", b"_"}:
        return "dec"
    return None


def read_escape_sequence(
    *,
    fd: int,
    selector: Callable[..., object],
    timeout: float,
    max_bytes: int,
) -> bytes:
    collected = bytearray()
    deadline = time.monotonic() + max(timeout, 0.0)
    while len(collected) < max_bytes:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        ready = cast(tuple[list[int], list[int], list[int]], selector([fd], [], [], remaining))
        readable = bool(ready and ready[0])
        if not readable:
            break
        chunk = os.read(fd, 1)
        if not chunk:
            break
        collected.extend(chunk)
        prefix = bytes(collected[:1])
        if prefix in {b"[", b"O"}:
            if chunk in {b"A", b"B", b"C", b"D", b"~", b"u"}:
                break
            if len(collected) > 1 and re.fullmatch(rb"[A-Za-z]", chunk):
                break
    return bytes(collected)


def decode_escape(sequence: bytes) -> str | None:
    if not sequence:
        return None
    text = sequence.decode("latin-1", errors="ignore")
    if not text or text[0] not in {"[", "O"}:
        return None
    final = text[-1]
    mapping = {
        "A": "up",
        "B": "down",
        "C": "right",
        "D": "left",
    }
    if final not in mapping:
        return None
    if text[0] == "O":
        return mapping[final]
    body = text[1:-1]
    if not body or re.fullmatch(r"[0-9;]*", body):
        return mapping[final]
    return None


def decode_modified_printable(sequence: bytes) -> str | None:
    if not sequence:
        return None
    text = sequence.decode("latin-1", errors="ignore")
    if len(text) == 1 and " " <= text <= "~":
        return text
    if not (text.startswith("[") and text.endswith("u")):
        return None
    body = text[1:-1]
    match = re.fullmatch(r"([0-9]{1,6})(?:;[0-9]{1,6})*", body)
    if not match:
        return None
    codepoint = int(match.group(1))
    if 32 <= codepoint <= 126:
        return chr(codepoint)
    return None


def flush_pending_input(*, fd: int) -> None:
    import select as _select

    try:
        termios.tcflush(fd, termios.TCIFLUSH)
        return
    except Exception:
        pass

    drained = 0
    max_bytes = 4096
    while drained < max_bytes:
        ready, _, _ = _select.select([fd], [], [], 0)
        if not ready:
            break
        chunk = os.read(fd, 1)
        if not chunk:
            break
        drained += 1


def flush_input_buffer(*, fd: int, fallback_flush: Callable[..., None] | None = None) -> None:
    try:
        termios.tcflush(fd, termios.TCIFLUSH)
        return
    except Exception:
        pass
    try:
        (fallback_flush or flush_pending_input)(fd=fd)
    except Exception:
        pass


def restore_terminal_state(*, fd: int, original_state: Any) -> None:
    for mode in (termios.TCSADRAIN, termios.TCSAFLUSH):
        try:
            termios.tcsetattr(fd, mode, original_state)
            return
        except Exception:
            continue
    try:
        subprocess.run(
            ["stty", "sane"],
            stdin=fd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except Exception:
        return
