from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ....config import LocalConfigState, StartupProfile
from ....config.persistence import (
    ConfigSaveResult,
    ManagedConfigValues,
    managed_values_from_local_state,
    save_local_config_with_ignore_policy,
    validate_managed_values,
)
from envctl_engine.ui.textual.compat import (
    apply_textual_driver_compat,
    handle_text_edit_key_alias,
    textual_run_policy,
)
from envctl_engine.ui.textual.list_row_styles import focus_selectable_list
from . import config_wizard_components as component_policy
from . import config_wizard_values as value_policy
from .config_wizard_action_bundle import ConfigWizardActionBundle
from .config_wizard_components import ComponentRow, ConfigWizardComponentInteraction
from .config_wizard_fields import (
    _SERVICE_STARTUP_FIELDS,
    _STEP_HELP_TEXT,
    _STEP_TITLES,
    _directory_field_name_from_input_id,
    _hydrate_wizard_values,
    _visible_command_fields,
    _visible_directory_fields,
    _visible_port_fields,
)
from .config_wizard_form import ConfigWizardFormController
from .config_wizard_hints import ConfigWizardHintResolver
from .config_wizard_layout import CONFIG_WIZARD_APP_CSS, compose_config_wizard_layout
from .config_wizard_list_rendering import (
    render_additional_services_list,
    render_choice_list,
    render_components_list,
    render_service_startup_list,
)
from .config_wizard_navigation import resolve_config_wizard_key
from .config_wizard_status import (
    resolve_config_wizard_action_state,
    resolve_config_wizard_status,
)
from .config_wizard_step_flow import should_show_service_startup_step, sync_wizard_steps
from .config_wizard_suggestions import (
    build_config_wizard_suggestions,
    emit_detected_config_wizard_suggestions,
)


def _emit(emit: Callable[..., None] | None, event: str, **payload: object) -> None:
    if callable(emit):
        emit(event, component="ui.textual.config_wizard", **payload)


@dataclass(slots=True)
class ConfigWizardResult:
    values: ManagedConfigValues
    save_result: ConfigSaveResult


def build_config_wizard_app(
    *,
    local_state: LocalConfigState,
    initial_values: ManagedConfigValues | None = None,
    emit: Callable[..., None] | None = None,
    default_wizard_type: str = "simple",
) -> tuple[object, object]:
    values = initial_values or managed_values_from_local_state(local_state)
    source_label = _source_label(local_state)
    run_policy = textual_run_policy(screen="config_wizard")

    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.events import Key
    from textual.widgets import Button, Footer, Input, Label, ListItem, ListView, Static

    class ConfigWizardApp(App[ConfigWizardResult | None]):
        BINDINGS = [
            Binding("q", "cancel", "Cancel"),
            Binding("ctrl+c", "cancel", "Cancel"),
            Binding("escape", "cancel", "Cancel"),
            Binding("d", "toggle_component_split", "Split"),
            Binding("ctrl+s", "cycle_command_suggestion", "Suggest"),
            Binding("tab", "focus_next", "Next"),
            Binding("shift+tab", "focus_previous", "Prev"),
        ]
        CSS = CONFIG_WIZARD_APP_CSS

        def __init__(self) -> None:
            super().__init__()
            self.step_index = 0
            self.values = _hydrate_wizard_values(values, base_dir=local_state.base_dir)
            self._suggestions_by_field = self._build_suggestions_by_field()
            self._field_hints = ConfigWizardHintResolver.from_local_state(
                local_state,
                suggestions_by_field=self._suggestions_by_field,
                field_value=self._field_value,
            )
            self._form_controller = ConfigWizardFormController(
                app=self,
                values=self.values,
                base_dir=local_state.base_dir,
                hints=self._field_hints,
                input_cls=Input,
                label_cls=Label,
                static_cls=Static,
                refresh_status=self._refresh_status,
                current_step=self._current_step,
            )
            self._save_result: ConfigSaveResult | None = None
            self._steps: list[str] = []
            self._suppress_list_selected_once = False
            self._last_status_message = ""
            self.values.main_profile.backend_enable = bool(self.values.main_profile.backend_enable)
            self.values.main_profile.frontend_enable = bool(self.values.main_profile.frontend_enable)
            self.values.trees_profile.backend_enable = bool(self.values.trees_profile.backend_enable)
            self.values.trees_profile.frontend_enable = bool(self.values.trees_profile.frontend_enable)
            self._sync_startup_enable_flags()
            self._component_interaction = ConfigWizardComponentInteraction.from_values(self.values)
            self._emit_detected_suggestions()
            self._sync_steps(current_step="welcome")

        def _build_suggestions_by_field(self):
            return build_config_wizard_suggestions(local_state.base_dir)

        def _emit_detected_suggestions(self) -> None:
            emit_detected_config_wizard_suggestions(
                self._suggestions_by_field,
                emit=lambda event, **payload: _emit(emit, event, **payload),
            )

        def compose(self) -> ComposeResult:
            yield from compose_config_wizard_layout(
                values=self.values,
                field_value=self._field_value,
                horizontal_cls=Horizontal,
                vertical_cls=Vertical,
                vertical_scroll_cls=VerticalScroll,
                button_cls=Button,
                footer_cls=Footer,
                input_cls=Input,
                label_cls=Label,
                list_view_cls=ListView,
                static_cls=Static,
            )

        def on_mount(self) -> None:
            _emit(emit, "ui.screen.enter", screen="config_wizard", source=local_state.config_source)
            try:
                apply_textual_driver_compat(
                    driver=getattr(self.app, "_driver", None),
                    screen="config_wizard",
                    mouse_enabled=run_policy.mouse,
                    disable_focus_reporting=True,
                    emit=emit,
                )
            except Exception:
                pass
            self._refresh_all()

        def on_unmount(self) -> None:
            _emit(emit, "ui.screen.exit", screen="config_wizard")

        def on_key(self, event: Key) -> None:
            if self._text_input_has_focus() and handle_text_edit_key_alias(widget=self.focused, event=event):
                return
            decision = resolve_config_wizard_key(
                event.key,
                text_input_focused=self._text_input_has_focus(),
                button_focused=self._button_has_focus(),
                suggestion_field_focused=self._focused_suggestion_field() is not None,
            )
            if decision.stop_event:
                event.stop()
            if decision.prevent_default:
                event.prevent_default()
            if decision.action is not None:
                getattr(self, f"action_{decision.action}")()
                return
            if decision.emit_key:
                _emit(emit, "ui.key", screen="config_wizard", key=event.key, character=event.character)

        def _text_input_has_focus(self) -> bool:
            focused = self.focused
            return isinstance(focused, Input)

        def _focused_suggestion_field(self) -> str | None:
            return self._action_bundle().suggestions().focused_suggestion_field()

        def _button_has_focus(self) -> bool:
            focused = self.focused
            return isinstance(focused, Button)

        def on_input_changed(self, event: Input.Changed) -> None:
            field_name = _directory_field_name_from_input_id(getattr(event.input, "id", None))
            if field_name is None:
                return
            self._refresh_directory_validation(field_name, raw=event.value)
            self._refresh_field_hint(field_name, raw=event.value)
            if self._current_step() in {"directories", "commands"}:
                self._refresh_status()

        def _current_step(self) -> str:
            return self._steps[self.step_index]

        def _profile_for_mode(self, mode: str) -> StartupProfile:
            return component_policy.profile_for_mode(self.values, mode)

        def _should_show_service_startup_step(self) -> bool:
            return should_show_service_startup_step(self.values)

        def _sync_steps(self, *, current_step: str | None = None) -> None:
            state = sync_wizard_steps(
                self.values,
                current_steps=self._steps,
                step_index=self.step_index,
                current_step=current_step,
                include_additional_services=str(default_wizard_type).strip().lower() == "advanced",
            )
            self._steps = state.steps
            self.step_index = state.step_index

        def _refresh_all(self) -> None:
            self._sync_steps()
            current_step = self._current_step()
            source_widget = self.query_one("#config-source", Static)
            if current_step == "welcome":
                source_widget.display = True
                source_widget.update(
                    f"Path: {local_state.config_file_path} | Source: {source_label} | CLI/env overrides still apply"
                )
            else:
                source_widget.display = False
                source_widget.update("")
            self.query_one("#config-step-title", Static).update(_STEP_TITLES[current_step])
            self.query_one("#config-step-help", Static).update(_STEP_HELP_TEXT[current_step])
            self._refresh_body()
            self._refresh_status()
            self._refresh_actions()
            self.refresh_bindings()
            self._focus_current_step()

        def _refresh_body(self) -> None:
            self._action_bundle().body().refresh_body()

        def _action_bundle(self) -> ConfigWizardActionBundle:
            return ConfigWizardActionBundle(
                app=self,
                values=self.values,
                component_interaction=self._component_interaction,
                service_startup_fields=_SERVICE_STARTUP_FIELDS,
                config_file_path=local_state.config_file_path,
                source_label=source_label,
                steps=lambda: self._steps,
                step_index=lambda: self.step_index,
                set_step_index=lambda value: setattr(self, "step_index", value),
                set_suppress_list_selected_once=lambda value: setattr(self, "_suppress_list_selected_once", value),
                set_save_result=lambda value: setattr(self, "_save_result", value),
                current_step=self._current_step,
                list_view=lambda: self.query_one("#config-list", ListView),
                focused_widget=lambda: self.focused,
                input_type=Input,
                suggestions_by_field=self._suggestions_by_field,
                field_name_from_input_id=_directory_field_name_from_input_id,
                directory_label=self._directory_label,
                refresh_all=self._refresh_all,
                refresh_body=self._refresh_body,
                refresh_status=self._refresh_status,
                refresh_actions=self._refresh_actions,
                sync_steps=self._sync_steps,
                sync_startup_enable_flags=self._sync_startup_enable_flags,
                refresh_directory_validation=self._refresh_directory_validation,
                refresh_field_hint=self._refresh_field_hint,
                emit=lambda event, **payload: _emit(emit, event, **payload),
                set_display=lambda widget_id, display: setattr(self.query_one(f"#{widget_id}"), "display", display),
                update_widget=lambda widget_id, text: self.query_one(f"#{widget_id}", Static).update(text),
                render_choice_step=lambda *, selected, options: self._render_choice_step(
                    self.query_one("#config-list", ListView),
                    selected=selected,
                    options=options,
                ),
                render_components_step=lambda: self._render_components_step(self.query_one("#config-list", ListView)),
                render_service_startup_step=lambda: self._render_service_startup_step(
                    self.query_one("#config-list", ListView)
                ),
                sync_additional_service_inputs=self._sync_additional_service_inputs,
                sync_directory_inputs=self._sync_directory_inputs,
                sync_port_inputs=self._sync_port_inputs,
                update_review=lambda text: self.query_one("#config-review", Static).update(text),
                apply_directory_inputs=self._apply_directory_inputs,
                apply_additional_service_inputs=self._apply_additional_service_inputs,
                apply_port_inputs=self._apply_port_inputs,
                validate_values=lambda *, values, require_directories, require_entrypoints: validate_managed_values(
                    values,
                    require_directories=require_directories,
                    require_entrypoints=require_entrypoints,
                ),
                save_config=lambda: save_local_config_with_ignore_policy(
                    local_state=local_state,
                    values=self.values,
                    update_global_ignores=True,
                ),
                exit_with_result=self.exit,
                result_factory=lambda values, save_result: ConfigWizardResult(values=values, save_result=save_result),
                focus_list=lambda list_view, index: focus_selectable_list(self, list_view, index),
                focus_widget=lambda widget_id: self.query_one(f"#{widget_id}").focus(),
            )

        def _render_additional_services_step(self, list_view) -> None:
            render_additional_services_list(
                list_view,
                services=self.values.additional_services,
                label_cls=Label,
                list_item_cls=ListItem,
            )

        def _render_choice_step(self, list_view, *, selected: str, options: tuple[tuple[str, str], ...]) -> None:
            render_choice_list(
                list_view,
                selected=selected,
                options=options,
                label_cls=Label,
                list_item_cls=ListItem,
            )

        def _component_rows(self) -> list[ComponentRow]:
            return self._component_interaction.rows()

        def _render_components_step(self, list_view) -> None:
            rows = self._component_rows()
            selected_flags = self._component_interaction.selected_flags(rows)
            render_components_list(
                list_view,
                rows=rows,
                selected_flags=selected_flags,
                default_index=self._component_interaction.default_index(rows, selected_flags),
                label_cls=Label,
                list_item_cls=ListItem,
            )

        def _render_service_startup_step(self, list_view) -> None:
            render_service_startup_list(
                list_view,
                rows=_SERVICE_STARTUP_FIELDS,
                enabled_flags=[
                    self._service_startup_value(field_name, mode)
                    for field_name, mode, _label in _SERVICE_STARTUP_FIELDS
                ],
                label_cls=Label,
                list_item_cls=ListItem,
            )

        def _service_startup_value(self, field_name: str, mode: str) -> bool:
            return component_policy.service_startup_value(self.values, field_name, mode)

        def _toggle_service_startup_value(self, field_name: str, mode: str) -> None:
            component_policy.toggle_service_startup_value(self.values, field_name, mode)

        def _sync_directory_inputs(self, visible_fields: tuple[tuple[str, str], ...]) -> None:
            self._form_controller.sync_directory_inputs(visible_fields)

        def _sync_port_inputs(self, visible_fields: tuple[tuple[str, str], ...]) -> None:
            self._form_controller.sync_port_inputs(visible_fields)

        def _sync_additional_service_inputs(self) -> None:
            self._form_controller.sync_additional_service_inputs()

        def _additional_service_input_value(self, field_name: str) -> str:
            return self._form_controller.additional_service_input_value(field_name)

        def _apply_additional_service_inputs(self) -> bool:
            return self._form_controller.apply_additional_service_inputs()

        def _refresh_actions(self) -> None:
            back = self.query_one("#btn-back", Button)
            next_button = self.query_one("#btn-next", Button)
            back.disabled, next_button.label = resolve_config_wizard_action_state(
                step_index=self.step_index,
                step_count=len(self._steps),
            )

        def _refresh_status(self, message: str | None = None) -> None:
            status = self.query_one("#config-status", Static)
            if message is not None:
                self._last_status_message = message
                status.update(message)
                self.refresh_bindings()
                return
            status.update(
                resolve_config_wizard_status(
                    self._current_step(),
                    self.values,
                    component_split_available=self._component_split_available(),
                    first_directory_error=lambda visible_fields: self._first_directory_error(
                        visible_fields=visible_fields
                    ),
                )
            )
            self.refresh_bindings()

        def _focus_current_step(self) -> None:
            self._action_bundle().focus().focus_current_step()

        def _field_value(self, field_name: str) -> int | str:
            return value_policy.wizard_field_value(self.values, field_name)

        def _sync_startup_enable_flags(self) -> None:
            component_policy.sync_startup_enable_flags(
                self.values,
                include_service_startup=self._should_show_service_startup_step(),
            )

        def _nearest_selectable_component_index(self, index: int, *, step: int) -> int:
            return self._action_bundle().component().nearest_selectable_component_index(index, step=step)

        def _directory_label(self, field_name: str) -> str:
            return self._form_controller.directory_label(field_name)

        def _refresh_field_hint(self, field_name: str, *, raw: str | None = None) -> None:
            self._form_controller.refresh_field_hint(field_name, raw=raw)

        def _field_hint_text(self, field_name: str, *, raw: str | None = None) -> str:
            return self._form_controller.field_hint_text(field_name, raw=raw)

        def _directory_validation_error(self, field_name: str, *, raw: str | None = None) -> str | None:
            return self._form_controller.directory_validation_error(field_name, raw=raw)

        def _refresh_directory_validation(self, field_name: str, *, raw: str | None = None) -> None:
            self._form_controller.refresh_directory_validation(field_name, raw=raw)

        def _first_directory_error(self, *, visible_fields: tuple[tuple[str, str], ...] | None = None) -> str | None:
            return self._form_controller.first_directory_error(visible_fields=visible_fields)

        def action_cursor_up(self) -> None:
            self._action_bundle().component().cursor_up()

        def action_cursor_down(self) -> None:
            self._action_bundle().component().cursor_down()

        def _sync_focus_driven_selection(self) -> None:
            self._action_bundle().component().sync_focus_driven_selection()

        def action_toggle_item(self) -> None:
            self._action_bundle().component().toggle_item()

        def _toggle_service_startup_row(self) -> None:
            self._action_bundle().component().toggle_service_startup_row()

        def _toggle_components_row(self) -> None:
            self._action_bundle().component().toggle_components_row()

        def _toggle_component_split(self) -> None:
            self._action_bundle().component().toggle_component_split()

        def _component_split_available(self) -> bool:
            return self._action_bundle().component().component_split_available()

        def on_list_view_selected(self, event: ListView.Selected) -> None:
            if self._suppress_list_selected_once:
                self._suppress_list_selected_once = False
                return
            step = self._current_step()
            if step not in {"default_mode", "components", "service_startup"}:
                return
            self._action_bundle().component().list_view_selected(index=event.index)

        def action_focus_next(self) -> None:
            self.screen.focus_next()
            self._refresh_status()

        def action_focus_previous(self) -> None:
            self.screen.focus_previous()
            self._refresh_status()

        def action_cycle_command_suggestion(self) -> None:
            self._action_bundle().suggestions().cycle_command_suggestion()

        def action_cancel(self) -> None:
            self.exit(None)

        def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
            if action == "toggle_component_split":
                return True if self._component_split_available() else False
            if action == "cycle_command_suggestion":
                return True if self._action_bundle().suggestions().cycle_command_suggestion_available() else False
            return super().check_action(action, parameters)

        def action_go_back(self) -> None:
            self._go_back()

        def action_toggle_component_split(self) -> None:
            self._toggle_component_split()

        def action_submit_or_next(self) -> None:
            self._action_bundle().flow().submit_or_next()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            button_id = event.button.id or ""
            if button_id == "btn-cancel":
                self.action_cancel()
                return
            if button_id == "btn-back":
                self._go_back()
                return
            if button_id == "btn-next":
                self.action_submit_or_next()

        def _go_back(self) -> None:
            self._action_bundle().flow().go_back()

        def _advance(self) -> None:
            self._action_bundle().flow().advance()

        def _apply_directory_inputs(self) -> bool:
            visible_fields = (
                _visible_directory_fields(self.values)
                if self._current_step() == "directories"
                else _visible_command_fields(self.values)
            )
            return self._form_controller.apply_directory_inputs(visible_fields)

        def _apply_port_inputs(self) -> bool:
            visible_fields = _visible_port_fields(self.values)
            return self._form_controller.apply_port_inputs(visible_fields)

    return ConfigWizardApp(), run_policy


def _source_label(local_state: LocalConfigState) -> str:
    if local_state.config_source == "envctl":
        return "existing .envctl"
    if local_state.config_source == "legacy_prefill":
        source_path = local_state.legacy_source_path or local_state.active_source_path
        if source_path is not None:
            return f"legacy import from {source_path.name}"
        return "legacy import"
    return "defaults"
