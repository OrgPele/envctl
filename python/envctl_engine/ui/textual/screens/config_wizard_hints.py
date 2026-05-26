from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ....actions.actions_test import TestCommandSuggestion, TestPathSuggestion
from ....config import LocalConfigState
from .config_wizard_fields import (
    _COMMAND_FIELDS,
    _DIRECTORY_FIELDS,
    _directory_validation_message,
    _entrypoint_validation_message,
)


_CONFIG_KEYS_BY_FIELD = {
    "backend_start_cmd": "ENVCTL_BACKEND_START_CMD",
    "frontend_start_cmd": "ENVCTL_FRONTEND_START_CMD",
    "backend_test_cmd": "ENVCTL_BACKEND_TEST_CMD",
    "frontend_test_cmd": "ENVCTL_FRONTEND_TEST_CMD",
    "frontend_test_path": "ENVCTL_FRONTEND_TEST_PATH",
}


@dataclass(slots=True)
class ConfigWizardHintResolver:
    base_dir: Path
    parsed_values: Mapping[str, object]
    suggestions_by_field: Mapping[str, tuple[TestCommandSuggestion | TestPathSuggestion, ...]]
    field_value: Callable[[str], Any]

    @classmethod
    def from_local_state(
        cls,
        local_state: LocalConfigState,
        *,
        suggestions_by_field: Mapping[str, tuple[TestCommandSuggestion | TestPathSuggestion, ...]],
        field_value: Callable[[str], Any],
    ) -> ConfigWizardHintResolver:
        return cls(
            base_dir=local_state.base_dir,
            parsed_values=local_state.parsed_values,
            suggestions_by_field=suggestions_by_field,
            field_value=field_value,
        )

    def directory_label(self, field_name: str) -> str:
        for candidate, label in (*_DIRECTORY_FIELDS, *_COMMAND_FIELDS):
            if candidate == field_name:
                return label
        return "Directory"

    def config_key_for_field(self, field_name: str) -> str | None:
        return _CONFIG_KEYS_BY_FIELD.get(field_name)

    def field_has_existing_config_value(self, field_name: str) -> bool:
        key = self.config_key_for_field(field_name)
        if not key or key not in self.parsed_values:
            return False
        return bool(str(self.parsed_values.get(key) or "").strip())

    def suggestion_value(self, suggestion: TestCommandSuggestion | TestPathSuggestion) -> str:
        if isinstance(suggestion, TestCommandSuggestion):
            return suggestion.command_text
        return suggestion.path

    def matching_suggestion(
        self,
        field_name: str,
        value: str,
    ) -> TestCommandSuggestion | TestPathSuggestion | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        for suggestion in self.suggestions_by_field.get(field_name, ()):
            if self.suggestion_value(suggestion) == normalized:
                return suggestion
        return None

    def field_hint_text(self, field_name: str, *, raw: str | None = None) -> str:
        value = str(self.field_value(field_name)) if raw is None else str(raw)
        if field_name in {"backend_test_cmd", "frontend_test_cmd"}:
            return self.test_command_hint(field_name, value=value)
        if field_name == "frontend_test_path":
            return self.frontend_test_path_hint(value=value)
        if field_name in {"backend_start_cmd", "frontend_start_cmd"} and not value.strip():
            return "No entrypoint detected; enter the command envctl should run for this service."
        return ""

    def test_command_hint(self, field_name: str, *, value: str) -> str:
        suggestions = self.suggestions_by_field.get(field_name, ())
        if self.field_has_existing_config_value(field_name):
            return "Existing value from .envctl; detection will not overwrite it."
        stripped = value.strip()
        if stripped:
            match = self.matching_suggestion(field_name, stripped)
            if isinstance(match, TestCommandSuggestion):
                suffix = (
                    " Multiple suggestions available; press Ctrl+S or Down to cycle." if len(suggestions) > 1 else ""
                )
                return f"Detected: {match.label} — {match.reason}{suffix}"
            return "Manual value; detection will not overwrite it."
        if suggestions:
            first = suggestions[0]
            if isinstance(first, TestCommandSuggestion):
                if len(suggestions) > 1:
                    return (
                        "Multiple suggestions available; press Ctrl+S or Down to accept "
                        f"{first.label}: {first.command_text}"
                    )
                return f"Detected suggestion available; press Ctrl+S or Down to accept {first.label}."
        return (
            "No test command detected; leave blank to let envctl try runtime defaults when `envctl test` runs, "
            "or enter one manually."
        )

    def frontend_test_path_hint(self, *, value: str) -> str:
        suggestions = self.suggestions_by_field.get("frontend_test_path", ())
        if self.field_has_existing_config_value("frontend_test_path"):
            return "Existing value from .envctl; detection will not overwrite it."
        stripped = value.strip()
        if stripped:
            match = self.matching_suggestion("frontend_test_path", stripped)
            if isinstance(match, TestPathSuggestion):
                suffix = (
                    " Multiple suggestions available; press Ctrl+S or Down to cycle." if len(suggestions) > 1 else ""
                )
                return f"Detected: {match.path} — {match.reason}{suffix}"
            return "Manual frontend test path; detection will not overwrite it."
        if suggestions:
            first = suggestions[0]
            if isinstance(first, TestPathSuggestion):
                if any(isinstance(item, TestPathSuggestion) and item.confidence == "high" for item in suggestions):
                    return f"Frontend test path suggestions available; press Ctrl+S or Down to accept {first.path}."
                return (
                    "No high-confidence frontend test directory detected; leave blank unless you want to scope "
                    f"frontend tests. Press Ctrl+S or Down to cycle suggestions such as {first.path}."
                )
        return "No frontend test directory detected; leave blank when the package test script scopes tests itself."

    def directory_validation_error(self, field_name: str, *, raw: str | None = None) -> str | None:
        label = self.directory_label(field_name)
        value = str(self.field_value(field_name)) if raw is None else str(raw)
        if field_name in {"backend_start_cmd", "frontend_start_cmd"}:
            return _entrypoint_validation_message(label, value)
        if field_name in {"backend_test_cmd", "frontend_test_cmd"}:
            return None
        if field_name == "frontend_test_path":
            if not value.strip():
                return None
            return _directory_validation_message(self.base_dir, label, value)
        return _directory_validation_message(self.base_dir, label, value)
