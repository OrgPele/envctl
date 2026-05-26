from __future__ import annotations

from collections.abc import Iterable

from envctl_engine.runtime.command_policy import (
    ACTION_COMMANDS,
    DIRECT_INSPECTION_COMMANDS,
    LIFECYCLE_CLEANUP_COMMANDS,
    STATE_ACTION_COMMANDS,
)

WORKFLOW_COMMANDS = frozenset({"start", "restart", "resume", "dashboard", "config", "plan", "import"})
DEBUG_COMMANDS = frozenset({"debug-pack", "debug-report", "debug-last", "doctor"})
UTILITY_COMMANDS = frozenset(
    {"codex-tmux", "ensure-worktree", "install-prompts", "migrate-hooks", "supabase-user", "qa-user", "playwright"}
)
DEFAULT_HEADLESS_COMMANDS = ACTION_COMMANDS | LIFECYCLE_CLEANUP_COMMANDS | STATE_ACTION_COMMANDS
GENERAL_WORKFLOW_ORDER = ("start", "resume", "restart", "dashboard", "config", "plan", "import")
GENERAL_ACTION_ORDER = (
    "stop",
    "stop-all",
    "blast-all",
    "logs",
    "clear-logs",
    "health",
    "errors",
    "test",
    "test-focused",
    "commit",
    "pr",
    "ship",
    "review",
    "migrate",
    "delete-worktree",
    "blast-worktree",
    "self-destruct-worktree",
)
GENERAL_INSPECTION_ORDER = (
    "list-commands",
    "list-targets",
    "list-trees",
    "show-config",
    "show-state",
    "explain-startup",
    "preflight",
    "session",
    "endpoints",
)
GENERAL_DIAGNOSTIC_ORDER = ("doctor", "debug-pack", "debug-report", "debug-last")
GENERAL_UTILITY_ORDER = (
    "install-prompts",
    "codex-tmux",
    "ensure-worktree",
    "supabase-user",
    "qa-user",
    "playwright",
    "migrate-hooks",
)


def default_interactivity(command: str) -> str:
    if command in DEFAULT_HEADLESS_COMMANDS:
        return "headless by default; pass --interactive when you intentionally want prompts/selectors."
    if command in WORKFLOW_COMMANDS:
        return "interactive-capable by default; pass --headless for automation or deterministic CI output."
    if command in DIRECT_INSPECTION_COMMANDS or command in DEBUG_COMMANDS or command in UTILITY_COMMANDS:
        return "prints or performs the specific requested utility/inspection work; use --json where supported."
    return "depends on the selected command path; pass --headless to avoid prompts when supported."


def ordered_known_commands(preferred_order: Iterable[str], commands: Iterable[str]) -> tuple[str, ...]:
    remaining = set(commands)
    ordered = [command for command in preferred_order if command in remaining]
    remaining.difference_update(ordered)
    ordered.extend(sorted(remaining))
    return tuple(ordered)
