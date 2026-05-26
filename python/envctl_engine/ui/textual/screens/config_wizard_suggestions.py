from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from ....actions.actions_test import (
    TestCommandSuggestion,
    TestPathSuggestion,
    frontend_test_path_suggestions,
    test_command_suggestions,
)


ConfigWizardSuggestion = TestCommandSuggestion | TestPathSuggestion
ConfigWizardSuggestionsByField = Mapping[str, tuple[ConfigWizardSuggestion, ...]]


@dataclass(frozen=True, slots=True)
class ConfigWizardSuggestionCycle:
    suggestion: ConfigWizardSuggestion
    value: str


def build_config_wizard_suggestions(base_dir: Path) -> dict[str, tuple[ConfigWizardSuggestion, ...]]:
    return {
        "backend_test_cmd": tuple(
            test_command_suggestions(
                base_dir,
                include_backend=True,
                include_frontend=False,
            )
        ),
        "frontend_test_cmd": tuple(
            test_command_suggestions(
                base_dir,
                include_backend=False,
                include_frontend=True,
            )
        ),
        "frontend_test_path": tuple(frontend_test_path_suggestions(base_dir)),
    }


def emit_detected_config_wizard_suggestions(
    suggestions_by_field: ConfigWizardSuggestionsByField,
    *,
    emit: Callable[..., None] | None,
) -> None:
    if not callable(emit):
        return
    for field_name, suggestions in suggestions_by_field.items():
        for suggestion in suggestions:
            emit(
                "ui.config_wizard.suggestion.detected",
                field=field_name,
                source=suggestion.source,
                confidence=suggestion.confidence,
            )


def suggestion_value(suggestion: ConfigWizardSuggestion) -> str:
    if isinstance(suggestion, TestCommandSuggestion):
        return suggestion.command_text
    return suggestion.path


def cycle_config_wizard_suggestion(
    suggestions_by_field: ConfigWizardSuggestionsByField,
    *,
    field_name: str,
    current_value: str,
) -> ConfigWizardSuggestionCycle | None:
    suggestions = suggestions_by_field.get(field_name, ())
    if not suggestions:
        return None
    values = [suggestion_value(suggestion) for suggestion in suggestions]
    try:
        current_index = values.index(str(current_value or "").strip())
    except ValueError:
        current_index = -1
    suggestion = suggestions[(current_index + 1) % len(suggestions)]
    return ConfigWizardSuggestionCycle(suggestion=suggestion, value=suggestion_value(suggestion))
