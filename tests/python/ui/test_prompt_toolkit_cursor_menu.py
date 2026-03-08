from __future__ import annotations

import importlib.util
import unittest
from unittest.mock import patch

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.ui.prompt_toolkit_cursor_menu import CursorMenuResult, run_prompt_toolkit_cursor_menu
from envctl_engine.ui.selector_model import SelectorItem


class PromptToolkitCursorMenuTests(unittest.TestCase):
    @staticmethod
    def _prompt_toolkit_available() -> bool:
        return importlib.util.find_spec("prompt_toolkit") is not None

    def test_returns_empty_when_no_enabled_options(self) -> None:
        result = run_prompt_toolkit_cursor_menu(
            prompt="Restart",
            options=[],
            multi=True,
            emit=None,
            selector_id="restart",
            deep_debug=True,
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.values, [])
        self.assertFalse(result.cancelled)

    def test_returns_application_result_and_emits_lifecycle(self) -> None:
        if not self._prompt_toolkit_available():
            self.skipTest("prompt_toolkit is not installed")
        events: list[tuple[str, dict[str, object]]] = []

        def emit(event: str, **payload: object) -> None:
            events.append((event, dict(payload)))

        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
                section="Services",
            )
        ]

        with patch(
            "prompt_toolkit.application.Application.run",
            return_value=CursorMenuResult(values=["alpha"], cancelled=False),
        ):
            result = run_prompt_toolkit_cursor_menu(
                prompt="Restart",
                options=options,
                multi=True,
                emit=emit,
                selector_id="restart",
                deep_debug=True,
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.values, ["alpha"])
        names = [name for name, _payload in events]
        self.assertIn("ui.selector.lifecycle", names)
        self.assertIn("ui.selector.key.summary", names)
        self.assertIn("ui.screen.enter", names)
        self.assertIn("ui.screen.exit", names)

    def test_keyboard_interrupt_is_treated_as_cancel(self) -> None:
        if not self._prompt_toolkit_available():
            self.skipTest("prompt_toolkit is not installed")
        options = [
            SelectorItem(
                id="service:alpha",
                label="Alpha",
                kind="service",
                token="alpha",
                scope_signature=("service:alpha",),
                section="Services",
            )
        ]

        with patch("prompt_toolkit.application.Application.run", side_effect=KeyboardInterrupt):
            result = run_prompt_toolkit_cursor_menu(
                prompt="Restart",
                options=options,
                multi=True,
                emit=None,
                selector_id="restart",
                deep_debug=False,
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertIsNone(result.values)
        self.assertTrue(result.cancelled)


if __name__ == "__main__":
    unittest.main()
