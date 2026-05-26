from __future__ import annotations

from envctl_engine.ui.textual.screens.config_wizard_navigation import (
    ConfigWizardKeyDecision,
    move_config_wizard_list_index,
    resolve_config_wizard_key,
)


def test_key_policy_submits_enter_when_button_is_not_focused() -> None:
    assert resolve_config_wizard_key(
        "enter",
        text_input_focused=False,
        button_focused=False,
        suggestion_field_focused=False,
    ) == ConfigWizardKeyDecision(action="submit_or_next", stop_event=True, prevent_default=True)


def test_key_policy_ignores_enter_when_button_is_focused() -> None:
    assert resolve_config_wizard_key(
        "enter",
        text_input_focused=False,
        button_focused=True,
        suggestion_field_focused=False,
    ) == ConfigWizardKeyDecision()


def test_key_policy_leaves_horizontal_navigation_alone_in_text_inputs() -> None:
    assert resolve_config_wizard_key(
        "right",
        text_input_focused=True,
        button_focused=False,
        suggestion_field_focused=False,
    ) == ConfigWizardKeyDecision()
    assert resolve_config_wizard_key(
        "left",
        text_input_focused=True,
        button_focused=False,
        suggestion_field_focused=False,
    ) == ConfigWizardKeyDecision()


def test_key_policy_cycles_suggestions_on_down_from_suggestion_input() -> None:
    assert resolve_config_wizard_key(
        "down",
        text_input_focused=True,
        button_focused=False,
        suggestion_field_focused=True,
    ) == ConfigWizardKeyDecision(action="cycle_command_suggestion", stop_event=True, prevent_default=True)


def test_key_policy_maps_component_split_and_emit_fallback() -> None:
    assert resolve_config_wizard_key(
        "d",
        text_input_focused=False,
        button_focused=False,
        suggestion_field_focused=False,
    ) == ConfigWizardKeyDecision(action="toggle_component_split", stop_event=True, prevent_default=True)
    assert resolve_config_wizard_key(
        "x",
        text_input_focused=False,
        button_focused=False,
        suggestion_field_focused=False,
    ) == ConfigWizardKeyDecision(emit_key=True)


def test_move_config_wizard_list_index_preserves_existing_cursor_rules() -> None:
    assert move_config_wizard_list_index(None, count=0, step=-1) == 0
    assert move_config_wizard_list_index(3, count=0, step=-1) == 2
    assert move_config_wizard_list_index(None, count=3, step=1) == 0
    assert move_config_wizard_list_index(2, count=3, step=1) == 2
    assert move_config_wizard_list_index(1, count=3, step=1) == 2
