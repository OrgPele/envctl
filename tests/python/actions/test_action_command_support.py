from __future__ import annotations

import unittest

from envctl_engine.actions.action_command_support import build_action_extra_env
from envctl_engine.runtime.command_router import parse_route


class ActionCommandSupportTests(unittest.TestCase):
    def test_ship_inline_commit_message_defaults_to_json_action_output(self) -> None:
        route = parse_route(["ship", "-m", "Ship focused workflow polish"], env={})

        extra = build_action_extra_env(route)

        self.assertEqual(extra["ENVCTL_COMMIT_MESSAGE"], "Ship focused workflow polish")
        self.assertEqual(extra["ENVCTL_ACTION_JSON"], "true")
        self.assertNotIn("ENVCTL_ACTION_HUMAN", extra)
        self.assertNotIn("ENVCTL_COMMIT_MESSAGE_FILE", extra)

    def test_ship_json_flag_is_accepted_as_no_op_compatibility(self) -> None:
        route = parse_route(["ship", "-m", "Ship focused workflow polish", "--json"], env={})

        extra = build_action_extra_env(route)

        self.assertEqual(extra["ENVCTL_COMMIT_MESSAGE"], "Ship focused workflow polish")
        self.assertEqual(extra["ENVCTL_ACTION_JSON"], "true")
        self.assertNotIn("ENVCTL_ACTION_HUMAN", extra)

    def test_ship_human_flag_requests_compact_action_output(self) -> None:
        route = parse_route(["ship", "-m", "Ship focused workflow polish", "--human"], env={})

        extra = build_action_extra_env(route)

        self.assertEqual(extra["ENVCTL_COMMIT_MESSAGE"], "Ship focused workflow polish")
        self.assertEqual(extra["ENVCTL_ACTION_HUMAN"], "true")
        self.assertNotIn("ENVCTL_ACTION_JSON", extra)


if __name__ == "__main__":
    unittest.main()
