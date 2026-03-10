from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.ui.color_policy import colors_enabled


class ColorPolicyTests(unittest.TestCase):
    def test_no_color_disables_when_non_interactive(self) -> None:
        enabled = colors_enabled({"NO_COLOR": "1"}, interactive_tty=False)
        self.assertFalse(enabled)

    def test_no_color_is_overridden_in_interactive_mode(self) -> None:
        enabled = colors_enabled({"NO_COLOR": "1"}, interactive_tty=True)
        self.assertTrue(enabled)

    def test_mode_off_disables_colors(self) -> None:
        enabled = colors_enabled({"ENVCTL_UI_COLOR_MODE": "off"}, interactive_tty=True)
        self.assertFalse(enabled)

    def test_mode_on_enables_colors(self) -> None:
        enabled = colors_enabled({"ENVCTL_UI_COLOR_MODE": "on"}, interactive_tty=False)
        self.assertTrue(enabled)


if __name__ == "__main__":
    unittest.main()
