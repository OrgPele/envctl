from __future__ import annotations

import unittest

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.help_topics import COMMAND_HELP_TOPICS, help_text_for_route, render_command_help


class HelpTopicsTests(unittest.TestCase):
    def test_command_topics_own_command_specific_help_catalog(self) -> None:
        self.assertIn("playwright", COMMAND_HELP_TOPICS)
        text = render_command_help(COMMAND_HELP_TOPICS["playwright"])

        self.assertIn("envctl playwright - run a browser-test command", text)
        self.assertIn("Default interactivity:", text)
        self.assertIn("pass a concrete executable after `--`", text)

    def test_help_text_for_route_resolves_prefix_and_suffix_help(self) -> None:
        suffix_text = help_text_for_route(parse_route(["playwright", "--help"], env={}))
        prefix_text = help_text_for_route(parse_route(["help", "playwright"], env={}))

        self.assertEqual(suffix_text, prefix_text)
        self.assertIn("envctl playwright - run a browser-test command", suffix_text)

    def test_pr_preview_controller_help_topic_is_available(self) -> None:
        self.assertIn("pr-preview-controller", COMMAND_HELP_TOPICS)
        text = render_command_help(COMMAND_HELP_TOPICS["pr-preview-controller"])

        self.assertIn("envctl pr-preview-controller - run the GitHub PR-label preview controller", text)
        self.assertIn("--command <name>", text)

    def test_help_text_for_route_returns_none_for_general_help(self) -> None:
        self.assertIsNone(help_text_for_route(parse_route(["--help"], env={})))


if __name__ == "__main__":
    unittest.main()
