from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConfigWizardKeyDecision:
    action: str | None = None
    stop_event: bool = False
    prevent_default: bool = False
    emit_key: bool = False


def resolve_config_wizard_key(
    key: str,
    *,
    text_input_focused: bool,
    button_focused: bool,
    suggestion_field_focused: bool,
) -> ConfigWizardKeyDecision:
    if key == "enter":
        if button_focused:
            return ConfigWizardKeyDecision()
        return _action_decision("submit_or_next")
    if key == "right":
        return ConfigWizardKeyDecision() if text_input_focused else _action_decision("submit_or_next")
    if key == "left":
        return ConfigWizardKeyDecision() if text_input_focused else _action_decision("go_back")
    if key == "up":
        return _action_decision("cursor_up")
    if key == "down":
        if text_input_focused and suggestion_field_focused:
            return _action_decision("cycle_command_suggestion")
        return _action_decision("cursor_down")
    if key == "space":
        return _action_decision("toggle_item")
    if key == "d":
        return _action_decision("toggle_component_split")
    return ConfigWizardKeyDecision(emit_key=True)


def move_config_wizard_list_index(current_index: int | None, *, count: int, step: int) -> int | None:
    if step < 0:
        return 0 if current_index is None else max(current_index - 1, 0)
    if count <= 0:
        return None
    return 0 if current_index is None else min(current_index + 1, count - 1)


def _action_decision(action: str) -> ConfigWizardKeyDecision:
    return ConfigWizardKeyDecision(action=action, stop_event=True, prevent_default=True)
