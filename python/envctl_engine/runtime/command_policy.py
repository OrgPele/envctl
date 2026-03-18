from __future__ import annotations

from typing import Final

LOAD_STATE_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "stop",
        "stop-all",
        "blast-all",
        "restart",
        "test",
        "logs",
        "clear-logs",
        "health",
        "errors",
        "blast-worktree",
        "pr",
        "commit",
        "review",
        "migrate",
    }
)

SKIP_STARTUP_ONLY_COMMANDS: Final[frozenset[str]] = frozenset({"debug-pack", "debug-report", "debug-last"})

DIRECT_INSPECTION_COMMANDS: Final[frozenset[str]] = frozenset(
    {"list-commands", "list-targets", "list-trees", "show-config", "show-state", "explain-startup"}
)
UTILITY_COMMANDS: Final[frozenset[str]] = frozenset({"install-prompts", "codex-tmux"})
DASHBOARD_ALWAYS_HIDDEN_COMMANDS: Final[frozenset[str]] = frozenset({"install-prompts", "codex-tmux"})

LIFECYCLE_CLEANUP_COMMANDS: Final[frozenset[str]] = frozenset({"stop", "stop-all", "blast-all"})
STATE_ACTION_COMMANDS: Final[frozenset[str]] = frozenset({"logs", "clear-logs", "health", "errors"})
ACTION_COMMANDS: Final[frozenset[str]] = frozenset(
    {"test", "delete-worktree", "blast-worktree", "pr", "commit", "review", "migrate"}
)
STARTUP_COMMANDS: Final[frozenset[str]] = frozenset({"restart", "plan", "start"})


def apply_mode_token(token: str, *, flags: dict[str, object], current_mode: str) -> str:
    if token in {
        "--tree",
        "--tree=true",
        "--trees",
        "--trees=true",
        "tree=true",
        "trees=true",
        "TREE=true",
        "TREES=true",
    }:
        return "trees"
    if token in {"main=false", "MAIN=false"}:
        return "trees"
    if token in {"--main", "--main=true", "main=true", "MAIN=true"}:
        flags["no_resume"] = True
        return "main"
    if token in {"--tree=false", "--trees=false", "tree=false", "trees=false", "TREE=false", "TREES=false"}:
        flags["no_resume"] = True
        return "main"
    return current_mode


def apply_command_policy(flags: dict[str, object], *, command: str, token: str | None = None) -> str | None:
    forced_mode: str | None = None
    if command == "plan":
        forced_mode = "trees"
        if isinstance(token, str):
            if "sequential" in token:
                flags["sequential"] = True
                flags["parallel_trees"] = False
            if "parallel" in token:
                flags["parallel_trees"] = True
            if token == "--planning-prs" or "planning_prs" in token:
                flags["planning_prs"] = True
    if command in LOAD_STATE_COMMANDS:
        flags["skip_startup"] = True
        flags["load_state"] = True
    elif command in SKIP_STARTUP_ONLY_COMMANDS:
        flags["skip_startup"] = True
    return forced_mode


def dispatch_family_for_command(command: str) -> str | None:
    if command == "help":
        return "help"
    if command in DIRECT_INSPECTION_COMMANDS:
        return "direct_inspection"
    if command in UTILITY_COMMANDS:
        return "utility"
    if command in SKIP_STARTUP_ONLY_COMMANDS:
        return "debug"
    if command in LIFECYCLE_CLEANUP_COMMANDS:
        return "lifecycle_cleanup"
    if command == "resume":
        return "resume"
    if command == "doctor":
        return "doctor"
    if command == "dashboard":
        return "dashboard"
    if command == "config":
        return "config"
    if command == "migrate-hooks":
        return "migrate_hooks"
    if command in STATE_ACTION_COMMANDS:
        return "state_action"
    if command in ACTION_COMMANDS:
        return "action"
    if command in STARTUP_COMMANDS:
        return "startup"
    return None
