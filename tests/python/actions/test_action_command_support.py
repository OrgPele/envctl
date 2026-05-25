from __future__ import annotations

import unittest

from envctl_engine.actions.action_command_support import build_action_extra_env
from envctl_engine.runtime.command_router import parse_route


class ActionCommandSupportTests(unittest.TestCase):
    def test_ship_inline_commit_message_is_forwarded_to_action_process(self) -> None:
        route = parse_route(["ship", "-m", "Ship focused workflow polish", "--json"], env={})

        extra = build_action_extra_env(route)

        self.assertEqual(extra["ENVCTL_COMMIT_MESSAGE"], "Ship focused workflow polish")
        self.assertEqual(extra["ENVCTL_ACTION_JSON"], "true")
        self.assertNotIn("ENVCTL_COMMIT_MESSAGE_FILE", extra)


if __name__ == "__main__":
    unittest.main()
