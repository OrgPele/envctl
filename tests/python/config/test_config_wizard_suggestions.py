from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from envctl_engine.actions.actions_test_models import (
    TestCommandSuggestion as CommandSuggestion,
    TestPathSuggestion as PathSuggestion,
)
from envctl_engine.ui.textual.screens.config_wizard_suggestions import (
    cycle_config_wizard_suggestion,
    emit_detected_config_wizard_suggestions,
    suggestion_value,
)


class ConfigWizardSuggestionTests(unittest.TestCase):
    def test_suggestion_value_supports_command_and_path_suggestions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            command = CommandSuggestion(
                command_text="python -m pytest tests",
                command=["python", "-m", "pytest", "tests"],
                cwd=Path(tmpdir),
                source="backend",
                label="Pytest",
                confidence="high",
                reason="pytest tests were detected",
                target="backend",
            )
            path = PathSuggestion(
                path="frontend/src",
                source="frontend",
                label="Frontend tests",
                confidence="medium",
                reason="test files were detected",
            )

            self.assertEqual(suggestion_value(command), "python -m pytest tests")
            self.assertEqual(suggestion_value(path), "frontend/src")

    def test_cycle_config_wizard_suggestion_advances_from_current_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            first = CommandSuggestion(
                command_text="python -m pytest tests",
                command=["python", "-m", "pytest", "tests"],
                cwd=Path(tmpdir),
                source="backend",
                label="Pytest",
                confidence="high",
                reason="pytest tests were detected",
                target="backend",
            )
            second = CommandSuggestion(
                command_text="python -m unittest discover",
                command=["python", "-m", "unittest", "discover"],
                cwd=Path(tmpdir),
                source="root",
                label="Unittest",
                confidence="medium",
                reason="unittest tests were detected",
                target="backend",
            )

            result = cycle_config_wizard_suggestion(
                {"backend_test_cmd": (first, second)},
                field_name="backend_test_cmd",
                current_value=first.command_text,
            )

            self.assertIsNotNone(result)
            self.assertEqual(result.value, second.command_text)
            self.assertEqual(result.suggestion, second)

    def test_cycle_config_wizard_suggestion_uses_first_when_current_value_is_manual(self) -> None:
        suggestion = PathSuggestion(
            path="frontend/src",
            source="frontend",
            label="Frontend tests",
            confidence="high",
            reason="test files were detected",
        )

        result = cycle_config_wizard_suggestion(
            {"frontend_test_path": (suggestion,)},
            field_name="frontend_test_path",
            current_value="custom/path",
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.value, "frontend/src")

    def test_emit_detected_config_wizard_suggestions_uses_stable_event_payloads(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        suggestion = PathSuggestion(
            path="frontend/src",
            source="frontend",
            label="Frontend tests",
            confidence="high",
            reason="test files were detected",
        )

        emit_detected_config_wizard_suggestions(
            {"frontend_test_path": (suggestion,)},
            emit=lambda event, **payload: events.append((event, payload)),
        )

        self.assertEqual(len(events), 1)
        event, payload = events[0]
        self.assertEqual(event, "ui.config_wizard.suggestion.detected")
        self.assertEqual(payload["field"], "frontend_test_path")
        self.assertEqual(payload["source"], "frontend")
        self.assertEqual(payload["confidence"], "high")


if __name__ == "__main__":
    unittest.main()
