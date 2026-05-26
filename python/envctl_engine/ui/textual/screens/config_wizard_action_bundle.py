from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ....config.persistence import ManagedConfigValues
from .config_wizard_body_actions import ConfigWizardBodyActions
from .config_wizard_component_actions import ConfigWizardComponentActions
from .config_wizard_components import ConfigWizardComponentInteraction
from .config_wizard_flow_actions import ConfigWizardFlowActions
from .config_wizard_focus_actions import ConfigWizardFocusActions
from .config_wizard_suggestions import ConfigWizardSuggestionsByField
from .config_wizard_suggestion_actions import ConfigWizardSuggestionActions


@dataclass(slots=True)
class ConfigWizardActionBundle:
    app: Any
    values: ManagedConfigValues
    component_interaction: ConfigWizardComponentInteraction
    service_startup_fields: Sequence[tuple[str, str, str]]
    config_file_path: Path
    source_label: str
    steps: Callable[[], Sequence[str]]
    step_index: Callable[[], int]
    set_step_index: Callable[[int], None]
    set_suppress_list_selected_once: Callable[[bool], None]
    set_save_result: Callable[[Any], None]
    current_step: Callable[[], str]
    list_view: Callable[[], Any]
    focused_widget: Callable[[], Any]
    input_type: type[Any]
    suggestions_by_field: ConfigWizardSuggestionsByField
    field_name_from_input_id: Callable[[object], str | None]
    directory_label: Callable[[str], str]
    refresh_all: Callable[[], None]
    refresh_body: Callable[[], None]
    refresh_status: Callable[..., None]
    refresh_actions: Callable[[], None]
    sync_steps: Callable[..., None]
    sync_startup_enable_flags: Callable[[], None]
    refresh_directory_validation: Callable[..., None]
    refresh_field_hint: Callable[..., None]
    emit: Callable[..., None]
    set_display: Callable[[str, bool], None]
    update_widget: Callable[[str, str], None]
    render_choice_step: Callable[..., None]
    render_components_step: Callable[[], None]
    render_service_startup_step: Callable[[], None]
    sync_additional_service_inputs: Callable[[], None]
    sync_directory_inputs: Callable[[tuple[tuple[str, str], ...]], None]
    sync_port_inputs: Callable[[tuple[tuple[str, str], ...]], None]
    update_review: Callable[[str], None]
    focus_list: Callable[[Any, int | None], None]
    focus_widget: Callable[[str], None]
    apply_directory_inputs: Callable[[], bool]
    apply_additional_service_inputs: Callable[[], bool]
    apply_port_inputs: Callable[[], bool]
    validate_values: Callable[..., Any]
    save_config: Callable[[], Any]
    exit_with_result: Callable[[Any], None]
    result_factory: Callable[[ManagedConfigValues, Any], Any]

    def body(self) -> ConfigWizardBodyActions:
        return ConfigWizardBodyActions(
            values=self.values,
            config_file_path=self.config_file_path,
            source_label=self.source_label,
            current_step=self.current_step,
            set_display=self.set_display,
            update_widget=self.update_widget,
            render_choice_step=self.render_choice_step,
            render_components_step=self.render_components_step,
            render_service_startup_step=self.render_service_startup_step,
            sync_additional_service_inputs=self.sync_additional_service_inputs,
            sync_directory_inputs=self.sync_directory_inputs,
            sync_port_inputs=self.sync_port_inputs,
            update_review=self.update_review,
        )

    def component(self) -> ConfigWizardComponentActions:
        return ConfigWizardComponentActions(
            app=self.app,
            values=self.values,
            component_interaction=self.component_interaction,
            service_startup_fields=self.service_startup_fields,
            current_step=self.current_step,
            list_view=self.list_view,
            focused_widget=self.focused_widget,
            sync_steps=self.sync_steps,
            sync_startup_enable_flags=self.sync_startup_enable_flags,
            refresh_body=self.refresh_body,
            refresh_status=self.refresh_status,
            refresh_actions=self.refresh_actions,
        )

    def suggestions(self) -> ConfigWizardSuggestionActions:
        return ConfigWizardSuggestionActions(
            values=self.values,
            suggestions_by_field=self.suggestions_by_field,
            input_type=self.input_type,
            focused_widget=self.focused_widget,
            field_name_from_input_id=self.field_name_from_input_id,
            directory_label=self.directory_label,
            refresh_directory_validation=self.refresh_directory_validation,
            refresh_field_hint=self.refresh_field_hint,
            refresh_status=self.refresh_status,
            emit=self.emit,
        )

    def flow(self) -> ConfigWizardFlowActions:
        return ConfigWizardFlowActions(
            values=self.values,
            steps=self.steps,
            step_index=self.step_index,
            set_step_index=self.set_step_index,
            set_suppress_list_selected_once=self.set_suppress_list_selected_once,
            set_save_result=self.set_save_result,
            current_step=self.current_step,
            list_has_focus=lambda: bool(getattr(self.list_view(), "has_focus", False)),
            refresh_all=self.refresh_all,
            refresh_status=self.refresh_status,
            apply_directory_inputs=self.apply_directory_inputs,
            apply_additional_service_inputs=self.apply_additional_service_inputs,
            apply_port_inputs=self.apply_port_inputs,
            validate_values=self.validate_values,
            save_config=self.save_config,
            exit_with_result=self.exit_with_result,
            result_factory=self.result_factory,
        )

    def focus(self) -> ConfigWizardFocusActions:
        return ConfigWizardFocusActions(
            values=self.values,
            current_step=self.current_step,
            list_view=self.list_view,
            nearest_selectable_component_index=self.component().nearest_selectable_component_index,
            focus_list=self.focus_list,
            focus_widget=self.focus_widget,
        )
