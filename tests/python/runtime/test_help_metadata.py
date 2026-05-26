from __future__ import annotations

import unittest

from envctl_engine.runtime.help_metadata import (
    DEFAULT_HEADLESS_COMMANDS,
    default_interactivity,
    ordered_known_commands,
)


class HelpMetadataTests(unittest.TestCase):
    def test_action_commands_are_headless_by_default(self) -> None:
        self.assertIn("pr", DEFAULT_HEADLESS_COMMANDS)
        self.assertIn("headless by default", default_interactivity("pr"))
        self.assertIn("--interactive", default_interactivity("pr"))

    def test_workflow_commands_are_interactive_capable(self) -> None:
        self.assertIn("interactive-capable", default_interactivity("start"))
        self.assertIn("--headless", default_interactivity("start"))

    def test_ordered_known_commands_preserves_preferred_order_then_sorts_remaining(self) -> None:
        self.assertEqual(
            ordered_known_commands(("start", "resume"), {"zeta", "resume", "alpha", "start"}),
            ("start", "resume", "alpha", "zeta"),
        )


if __name__ == "__main__":
    unittest.main()
