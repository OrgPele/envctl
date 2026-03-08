from __future__ import annotations

from collections.abc import Mapping


INTERACTIVE_COMMAND_ALIASES: dict[str, str] = {
    "s": "stop",
    "r": "restart",
    "t": "test",
    "tests": "test",
    "p": "pr",
    "prs": "pr",
    "c": "commit",
    "a": "analyze",
    "m": "migrate",
    "migration": "migrate",
    "migrations": "migrate",
    "l": "logs",
    "x": "clear-logs",
    "clearlogs": "clear-logs",
    "h": "health",
    "e": "errors",
    "dash": "dashboard",
    "g": "config",
    "d": "doctor",
    "stopall": "stop-all",
    "blastall": "blast-all",
    "blastworktree": "blast-worktree",
}


def normalize_interactive_command(token: str, aliases: Mapping[str, str] | None = None) -> str:
    value = str(token or "").strip().lower()
    if not value:
        return value
    mapping = aliases or INTERACTIVE_COMMAND_ALIASES
    return mapping.get(value, value)
