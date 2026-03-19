from __future__ import annotations

import unittest
from unittest.mock import patch

from envctl_engine.ui.capabilities import prompt_toolkit_available, textual_importable
from envctl_engine.ui.terminal_session import prompt_toolkit_available as terminal_prompt_toolkit_available


class UiDependencyContractTests(unittest.TestCase):
    def test_textual_importable_returns_false_when_dependency_probe_fails(self) -> None:
        with patch("importlib.util.find_spec", return_value=None):
            self.assertFalse(textual_importable())

    def test_prompt_toolkit_availability_checks_are_consistent(self) -> None:
        with patch("importlib.util.find_spec", return_value=None):
            self.assertFalse(prompt_toolkit_available())
            self.assertFalse(terminal_prompt_toolkit_available())


if __name__ == "__main__":
    unittest.main()
