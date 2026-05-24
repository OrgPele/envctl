from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime_cli_support import (
    migrate_hooks,
    print_help,
    render_help_text,
    run_config,
    unsupported_command,
)


class EngineRuntimeCliSupportTests(unittest.TestCase):
    def test_render_help_text_uses_runtime_help_contract(self) -> None:
        route = parse_route(["--help"], env={})

        text = render_help_text(route)

        self.assertIn("Usage:", text)
        self.assertIn("show-config", text)

    def test_print_help_writes_rendered_help(self) -> None:
        buffer = StringIO()

        with redirect_stdout(buffer):
            print_help(None)

        self.assertIn("Usage:", buffer.getvalue())

    def test_run_config_delegates_to_config_command_support(self) -> None:
        runtime = SimpleNamespace(name="runtime")
        route = parse_route(["show-config"], env={})

        with patch("envctl_engine.runtime.engine_runtime_cli_support.run_config_command", return_value=17) as command:
            code = run_config(runtime, route)

        self.assertEqual(code, 17)
        command.assert_called_once_with(runtime, route)

    def test_migrate_hooks_delegates_to_hook_migration_support(self) -> None:
        runtime = SimpleNamespace(name="runtime")
        route = parse_route(["migrate-hooks"], env={})

        with patch("envctl_engine.runtime.engine_runtime_cli_support.run_hook_migration", return_value=23) as command:
            code = migrate_hooks(runtime, route)

        self.assertEqual(code, 23)
        command.assert_called_once_with(runtime, route)

    def test_unsupported_command_preserves_user_facing_message_and_exit_code(self) -> None:
        buffer = StringIO()

        with redirect_stdout(buffer):
            code = unsupported_command("ship")

        self.assertEqual(code, 1)
        self.assertEqual(
            buffer.getvalue().strip(),
            "Command is not yet fully implemented in the Python runtime: ship.",
        )


if __name__ == "__main__":
    unittest.main()
