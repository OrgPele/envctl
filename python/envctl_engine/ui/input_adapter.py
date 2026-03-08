from __future__ import annotations

from typing import Literal

InputAction = Literal["submit", "cancel", "up", "down", "left", "right", "noop", "other"]


def action_for_key(key: str) -> InputAction:
    normalized = str(key or "").lower()
    if normalized in {"enter", "submit", "\r", "\n"}:
        return "submit"
    if normalized in {"esc", "escape", "q", "quit", "cancel"}:
        return "cancel"
    if normalized in {"up", "[a"}:
        return "up"
    if normalized in {"down", "[b"}:
        return "down"
    if normalized in {"left", "[d"}:
        return "left"
    if normalized in {"right", "[c"}:
        return "right"
    if not normalized:
        return "noop"
    return "other"
