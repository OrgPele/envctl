from __future__ import annotations

from typing import Any

from envctl_engine.config.command_support import run_config_command
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.help_text import render_help_text as _render_help_text
from envctl_engine.shared.hooks import migrate_legacy_shell_hooks
from envctl_engine.ui.path_links import render_path_for_terminal


def render_help_text(route: Route | None) -> str:
    return _render_help_text(route)


def print_help(route: Route | None = None) -> None:
    print(render_help_text(route))


def run_config(runtime: Any, route: Route) -> int:
    return run_config_command(runtime, route)


def migrate_hooks(runtime: Any, route: Route) -> int:
    return run_hook_migration(runtime, route)


def run_hook_migration(runtime: Any, route: Any) -> int:
    result = migrate_legacy_shell_hooks(runtime.config.base_dir, force=bool(getattr(route, "flags", {}).get("force")))
    if result.error:
        print(result.error)
        if result.starter_stub:
            print("")
            print(f"Starter stub for {result.python_hook_path.name}:")
            print(result.starter_stub, end="" if result.starter_stub.endswith("\n") else "\n")
        return 1 if result.skipped_hooks else 0
    print(f"Wrote {render_path_for_terminal(result.python_hook_path, env=getattr(runtime, 'env', {}))}")
    if result.migrated_hooks:
        print("Migrated hooks: " + ", ".join(result.migrated_hooks))
    return 0


def unsupported_command(command: str) -> int:
    print(f"Command is not yet fully implemented in the Python runtime: {command}.")
    return 1
