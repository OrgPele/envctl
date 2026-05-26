from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ....config.persistence import ManagedConfigValues
from .config_wizard_suggestions import ConfigWizardSuggestionsByField, cycle_config_wizard_suggestion


@dataclass(slots=True)
class ConfigWizardSuggestionActions:
    values: ManagedConfigValues
    suggestions_by_field: ConfigWizardSuggestionsByField
    input_type: type[Any]
    focused_widget: Callable[[], Any]
    field_name_from_input_id: Callable[[object], str | None]
    directory_label: Callable[[str], str]
    refresh_directory_validation: Callable[..., None]
    refresh_field_hint: Callable[..., None]
    refresh_status: Callable[..., None]
    emit: Callable[..., None]

    def focused_suggestion_field(self) -> str | None:
        focused = self.focused_widget()
        if not isinstance(focused, self.input_type):
            return None
        field_name = self.field_name_from_input_id(getattr(focused, "id", None))
        if field_name in self.suggestions_by_field:
            return field_name
        return None

    def cycle_command_suggestion_available(self) -> bool:
        field_name = self.focused_suggestion_field()
        return field_name is not None and bool(self.suggestions_by_field.get(field_name))

    def cycle_command_suggestion(self) -> None:
        field_name = self.focused_suggestion_field()
        if field_name is None:
            return
        suggestions = self.suggestions_by_field.get(field_name, ())
        if not suggestions:
            self.refresh_status("No suggestions are available for the focused field.")
            return
        focused = self.focused_widget()
        if not isinstance(focused, self.input_type):
            return
        result = cycle_config_wizard_suggestion(
            self.suggestions_by_field,
            field_name=field_name,
            current_value=str(getattr(focused, "value", "") or ""),
        )
        if result is None:
            return
        suggestion = result.suggestion
        next_value = result.value
        focused.value = next_value
        setattr(self.values, field_name, next_value)
        self.refresh_directory_validation(field_name, raw=next_value)
        self.refresh_field_hint(field_name, raw=next_value)
        self.emit(
            "ui.config_wizard.suggestion.accepted",
            field=field_name,
            source=suggestion.source,
            confidence=suggestion.confidence,
        )
        self.refresh_status(f"Accepted suggestion for {self.directory_label(field_name)}.")
