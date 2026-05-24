from __future__ import annotations

from typing import Any

from envctl_engine.config.command_support import run_config_command
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.help_text import render_help_text as _render_help_text
from envctl_engine.runtime.hook_migration_support import run_hook_migration


def render_help_text(route: Route | None) -> str:
    return _render_help_text(route)


def print_help(route: Route | None = None) -> None:
    print(render_help_text(route))


def run_config(runtime: Any, route: Route) -> int:
    return run_config_command(runtime, route)


def migrate_hooks(runtime: Any, route: Route) -> int:
    return run_hook_migration(runtime, route)


def unsupported_command(command: str) -> int:
    print(f"Command is not yet fully implemented in the Python runtime: {command}.")
    return 1
