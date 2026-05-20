from __future__ import annotations

import re
import shlex
from collections.abc import Iterable

from envctl_engine.runtime.command_router import (
    MODE_FORCE_MAIN_TOKENS,
    MODE_FORCE_TREES_TOKENS,
    MODE_MAIN_TOKENS,
    MODE_TREE_TOKENS,
)


def sanitize_interactive_input(raw: str) -> str:
    if not isinstance(raw, str) or not raw:
        return ""
    cleaned = re.sub(r"\x1bO[ -~]", "", raw)
    cleaned = re.sub(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", cleaned)
    cleaned = re.sub(r"(?:(?<=^)|(?<=\s))\[(?:\d{1,3}(?:;\d{1,3})*)?[ABCD~]", " ", cleaned)
    cleaned = re.sub(r"(?:(?<=^)|(?<=\s))O[A-D](?=$|[a-z]|\s)", " ", cleaned)
    cleaned = re.sub(r"(?:(?<=^)|(?<=\s))\[(?=[a-z])", "", cleaned)
    cleaned = cleaned.replace("\x1b", "")
    cleaned = cleaned.replace("\r", " ").replace("\n", " ")
    cleaned = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip()
    if cleaned:
        return cleaned
    return recover_single_letter_command_from_escape_fragment(raw)


def recover_single_letter_command_from_escape_fragment(raw: str) -> str:
    if not isinstance(raw, str):
        return ""
    stripped = raw.strip()
    if not stripped:
        return ""
    allowed = {"s", "r", "t", "p", "c", "a", "m", "l", "h", "e", "d", "q"}

    ss3_match = re.fullmatch(r"\x1bO([A-Za-z])", stripped)
    if ss3_match:
        candidate = ss3_match.group(1).lower()
        return candidate if candidate in allowed else ""

    ss3_suffix_match = re.fullmatch(r"\x1bO[A-D]([A-Za-z])", stripped)
    if ss3_suffix_match:
        candidate = ss3_suffix_match.group(1).lower()
        return candidate if candidate in allowed else ""

    csi_modifier_match = re.fullmatch(r"\x1b\[[0-9;?]+([A-Za-z])", stripped)
    if csi_modifier_match:
        candidate = csi_modifier_match.group(1).lower()
        return candidate if candidate in allowed else ""

    csi_suffix_match = re.fullmatch(r"\x1b\[[A-D]([A-Za-z])", stripped)
    if csi_suffix_match:
        candidate = csi_suffix_match.group(1).lower()
        return candidate if candidate in allowed else ""

    partial_csi_suffix_match = re.fullmatch(r"\[[A-D]([A-Za-z])", stripped)
    if partial_csi_suffix_match:
        candidate = partial_csi_suffix_match.group(1).lower()
        return candidate if candidate in allowed else ""

    bracket_suffix_match = re.fullmatch(r"\[([a-z])", stripped)
    if bracket_suffix_match:
        candidate = bracket_suffix_match.group(1).lower()
        return candidate if candidate in allowed else ""
    return ""


def parse_interactive_command(raw: str) -> list[str] | None:
    try:
        return shlex.split(raw)
    except ValueError as exc:
        print(f"Invalid command syntax: {exc}")
        return None


def tokens_set_mode(tokens: Iterable[str]) -> bool:
    explicit_mode_tokens = MODE_TREE_TOKENS | MODE_MAIN_TOKENS | MODE_FORCE_MAIN_TOKENS | MODE_FORCE_TREES_TOKENS
    for token in tokens:
        if str(token).strip().lower() in {value.strip().lower() for value in explicit_mode_tokens}:
            return True
    return False
