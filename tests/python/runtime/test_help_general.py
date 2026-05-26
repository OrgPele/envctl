from __future__ import annotations

import unittest

from envctl_engine.runtime.command_router import list_supported_commands
from envctl_engine.runtime.help_general import render_general_help


class HelpGeneralTests(unittest.TestCase):
    def test_general_help_lists_command_families_and_full_inventory(self) -> None:
        text = render_general_help()

        self.assertIn("envctl - run, inspect, test, and ship repo services/worktrees", text)
        self.assertIn("Command families:", text)
        self.assertIn("Workflow commands", text)
        self.assertIn("Specific action commands", text)
        self.assertIn("Inspection and diagnostics:", text)
        command_line = next(line for line in text.splitlines() if line.startswith("  all commands: "))
        help_commands = {item.strip() for item in command_line.split("all commands: ", 1)[1].split(",") if item.strip()}
        self.assertEqual(help_commands, set(list_supported_commands()))


if __name__ == "__main__":
    unittest.main()
