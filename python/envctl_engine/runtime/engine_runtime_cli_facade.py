from __future__ import annotations

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.engine_runtime_cli_support import (
    migrate_hooks as runtime_migrate_hooks,
    print_help as runtime_print_help,
    render_help_text as runtime_render_help_text,
    run_config as runtime_run_config,
    unsupported_command as runtime_unsupported_command,
)


def render_help_text(route: Route | None) -> str:
    return runtime_render_help_text(route)


class RuntimeCliFacadeMixin:
    @staticmethod
    def _render_help_text(route: Route | None) -> str:
        return runtime_render_help_text(route)

    def _print_help(self, route: Route | None = None) -> None:
        runtime_print_help(route)

    def _config(self, route: Route) -> int:
        return runtime_run_config(self, route)

    def _migrate_hooks(self, route: Route) -> int:
        return runtime_migrate_hooks(self, route)

    def _unsupported_command(self, command: str) -> int:
        return runtime_unsupported_command(command)
