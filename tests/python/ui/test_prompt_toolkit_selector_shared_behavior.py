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

from envctl_engine.ui.prompt_toolkit_list import (
    PromptToolkitListConfig,
    PromptToolkitListResult,
    run_prompt_toolkit_list_selector,
)
from envctl_engine.ui.selector_model import SelectorItem


class PromptToolkitSelectorSharedBehaviorTests(unittest.TestCase):
    @staticmethod
    def _prompt_toolkit_available() -> bool:
        return importlib.util.find_spec("prompt_toolkit") is not None

    def test_runner_returns_empty_without_enabled_rows(self) -> None:
        result = run_prompt_toolkit_list_selector(
            PromptToolkitListConfig(
                prompt="Restart",
                options=[],
                multi=True,
                selector_id="restart",
                backend_label="prompt_toolkit",
                screen_name="selector_prompt_toolkit",
                focused_widget_id="selector-prompt-toolkit",
                deep_debug=False,
                driver_trace_enabled=False,
                wrap_navigation=False,
                cancel_on_escape=False,
            )
        )
        self.assertEqual(result, PromptToolkitListResult(values=[], cancelled=False))

    def test_runner_emits_lifecycle_for_configured_backend(self) -> None:
        if not self._prompt_toolkit_available():
            self.skipTest("prompt_toolkit is not installed")

        events: list[tuple[str, dict[str, object]]] = []
        debug_events: list[tuple[str, dict[str, object]]] = []
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
            return_value=PromptToolkitListResult(values=["alpha"], cancelled=False),
        ):
            result = run_prompt_toolkit_list_selector(
                PromptToolkitListConfig(
                    prompt="Restart",
                    options=options,
                    multi=True,
                    selector_id="restart",
                    backend_label="prompt_toolkit",
                    screen_name="selector_prompt_toolkit",
                    focused_widget_id="selector-prompt-toolkit",
                    deep_debug=True,
                    driver_trace_enabled=False,
                    wrap_navigation=False,
                    cancel_on_escape=False,
                    emit_event=lambda event, **payload: events.append((event, dict(payload))),
                    emit_debug=lambda event, **payload: debug_events.append((event, dict(payload))),
                )
            )

        self.assertEqual(result, PromptToolkitListResult(values=["alpha"], cancelled=False))
        self.assertIn("ui.screen.enter", [name for name, _payload in events])
        self.assertIn("ui.screen.exit", [name for name, _payload in events])
        self.assertIn("ui.selector.lifecycle", [name for name, _payload in debug_events])
        self.assertIn("ui.selector.key.summary", [name for name, _payload in debug_events])


if __name__ == "__main__":
    unittest.main()
