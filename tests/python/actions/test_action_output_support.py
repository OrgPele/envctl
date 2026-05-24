from __future__ import annotations

from types import SimpleNamespace
import unittest

from envctl_engine.actions.action_output_support import action_colors_enabled, colorize_action_text


class ActionOutputSupportTests(unittest.TestCase):
    def test_action_colors_enabled_uses_runtime_tty_probe(self) -> None:
        runtime = SimpleNamespace(
            env={"ENVCTL_COLOR": "always"},
            raw_runtime=SimpleNamespace(_can_interactive_tty=lambda: True),
        )

        self.assertTrue(action_colors_enabled(runtime))

    def test_action_colors_enabled_treats_tty_probe_errors_as_noninteractive(self) -> None:
        def fail_probe() -> bool:
            raise RuntimeError("not available")

        runtime = SimpleNamespace(
            env={"ENVCTL_COLOR": "auto"},
            raw_runtime=SimpleNamespace(_can_interactive_tty=fail_probe),
        )

        self.assertFalse(action_colors_enabled(runtime))

    def test_colorize_action_text_applies_known_styles_when_enabled(self) -> None:
        rendered = colorize_action_text("passed", enabled=True, fg="green", bold=True, dim=True)

        self.assertEqual(rendered, "\033[1;2;32mpassed\033[0m")

    def test_colorize_action_text_returns_plain_text_when_disabled_or_unknown_style(self) -> None:
        self.assertEqual(colorize_action_text("plain", enabled=False, fg="green", bold=True), "plain")
        self.assertEqual(colorize_action_text("plain", enabled=True, fg="unknown"), "plain")


if __name__ == "__main__":
    unittest.main()
