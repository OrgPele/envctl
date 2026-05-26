from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from envctl_engine.actions.actions_test_models import TestCommandSuggestion as CommandSuggestion
from envctl_engine.config import PortDefaults, StartupProfile
from envctl_engine.config.persistence import ManagedConfigValues
from envctl_engine.ui.textual.screens.config_wizard_suggestion_actions import (
    ConfigWizardSuggestionActions,
)


class _Input:
    def __init__(self, *, widget_id: str, value: str = "") -> None:
        self.id = widget_id
        self.value = value


class ConfigWizardSuggestionActionsTests(unittest.TestCase):
    def _values(self) -> ManagedConfigValues:
        return ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, True, False, False, False, False),
            trees_profile=StartupProfile(True, True, True, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
        )

    def test_focused_suggestion_field_requires_focused_input_with_suggestions(self) -> None:
        focused = _Input(widget_id="config-backend-test-cmd", value="")
        actions = ConfigWizardSuggestionActions(
            values=self._values(),
            suggestions_by_field={"backend_test_cmd": ()},
            input_type=_Input,
            focused_widget=lambda: focused,
            field_name_from_input_id=lambda widget_id: "backend_test_cmd" if widget_id == focused.id else None,
            directory_label=lambda field_name: field_name,
            refresh_directory_validation=lambda field_name, raw=None: None,
            refresh_field_hint=lambda field_name, raw=None: None,
            refresh_status=lambda message=None: None,
            emit=lambda event, **payload: None,
        )

        self.assertEqual(actions.focused_suggestion_field(), "backend_test_cmd")

    def test_cycle_command_suggestion_updates_input_value_model_and_status(self) -> None:
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
            focused = _Input(widget_id="config-backend-test-cmd", value=first.command_text)
            values = self._values()
            events: list[tuple[str, dict[str, object]]] = []
            refreshed: list[tuple[str, str | None]] = []
            statuses: list[str] = []
            actions = ConfigWizardSuggestionActions(
                values=values,
                suggestions_by_field={"backend_test_cmd": (first, second)},
                input_type=_Input,
                focused_widget=lambda: focused,
                field_name_from_input_id=lambda widget_id: "backend_test_cmd" if widget_id == focused.id else None,
                directory_label=lambda field_name: "Backend test command",
                refresh_directory_validation=lambda field_name, raw=None: refreshed.append((field_name, raw)),
                refresh_field_hint=lambda field_name, raw=None: refreshed.append((f"hint:{field_name}", raw)),
                refresh_status=lambda message=None: statuses.append(str(message or "")),
                emit=lambda event, **payload: events.append((event, payload)),
            )

            actions.cycle_command_suggestion()

        self.assertEqual(focused.value, second.command_text)
        self.assertEqual(values.backend_test_cmd, second.command_text)
        self.assertEqual(
            refreshed,
            [
                ("backend_test_cmd", second.command_text),
                ("hint:backend_test_cmd", second.command_text),
            ],
        )
        self.assertEqual(statuses, ["Accepted suggestion for Backend test command."])
        self.assertEqual(events[0][0], "ui.config_wizard.suggestion.accepted")
        self.assertEqual(events[0][1]["field"], "backend_test_cmd")
        self.assertEqual(events[0][1]["source"], "root")
        self.assertEqual(events[0][1]["confidence"], "medium")

    def test_cycle_command_suggestion_reports_missing_suggestions_for_focused_field(self) -> None:
        focused = _Input(widget_id="config-backend-test-cmd", value="")
        statuses: list[str] = []
        actions = ConfigWizardSuggestionActions(
            values=self._values(),
            suggestions_by_field={"backend_test_cmd": ()},
            input_type=_Input,
            focused_widget=lambda: focused,
            field_name_from_input_id=lambda widget_id: "backend_test_cmd" if widget_id == focused.id else None,
            directory_label=lambda field_name: field_name,
            refresh_directory_validation=lambda field_name, raw=None: None,
            refresh_field_hint=lambda field_name, raw=None: None,
            refresh_status=lambda message=None: statuses.append(str(message or "")),
            emit=lambda event, **payload: None,
        )

        self.assertFalse(actions.cycle_command_suggestion_available())
        actions.cycle_command_suggestion()

        self.assertEqual(statuses, ["No suggestions are available for the focused field."])


if __name__ == "__main__":
    unittest.main()
