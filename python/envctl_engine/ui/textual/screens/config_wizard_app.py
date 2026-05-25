from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ....config import LocalConfigState, StartupProfile
from ....config.persistence import (
    ConfigSaveResult,
    ManagedConfigValues,
    config_review_text,
    managed_values_from_local_state,
    save_local_config_with_ignore_policy,
    validate_managed_values,
)
from envctl_engine.ui.textual.compat import (
    apply_textual_driver_compat,
    handle_text_edit_key_alias,
    textual_run_policy,
)
from envctl_engine.ui.textual.list_row_styles import apply_selectable_list_index, focus_selectable_list
from . import config_wizard_components as component_policy
from . import config_wizard_values as value_policy
from .config_wizard_components import ComponentRow, ConfigWizardComponentInteraction
from .config_wizard_fields import (
    _SERVICE_STARTUP_FIELDS,
    _STEP_HELP_TEXT,
    _STEP_TITLES,
    _additional_service_input_id,
    _directory_field_name_from_input_id,
    _directory_input_id,
    _hydrate_wizard_values,
    _port_input_id,
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
from .config_wizard_navigation import move_config_wizard_list_index, resolve_config_wizard_key
from .config_wizard_status import (
    command_step_status,
    directory_step_status,
    fallback_step_status,
    port_step_status,
    status_for_valid_config_step,
)
from .config_wizard_step_flow import should_show_service_startup_step, sync_wizard_steps
from .config_wizard_suggestions import (
    build_config_wizard_suggestions,
    cycle_config_wizard_suggestion,
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
            focused = self.focused
            if not isinstance(focused, Input):
                return None
            field_name = _directory_field_name_from_input_id(getattr(focused, "id", None))
            if field_name in self._suggestions_by_field:
                return field_name
            return None

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
            step = self._current_step()
            welcome = self.query_one("#config-welcome", Static)
            list_view = self.query_one("#config-list", ListView)
            empty = self.query_one("#config-empty", Static)
            directories = self.query_one("#config-directories", VerticalScroll)
            ports = self.query_one("#config-ports", VerticalScroll)
            additional_services = self.query_one("#config-additional-services", VerticalScroll)
            review_scroll = self.query_one("#config-review-scroll", VerticalScroll)
            review = self.query_one("#config-review", Static)
            welcome.display = step == "welcome"
            list_view.display = step not in {
                "welcome",
                "additional_services",
                "directories",
                "commands",
                "ports",
                "review",
            }
            directories.display = step in {"directories", "commands"}
            ports.display = step == "ports"
            additional_services.display = step == "additional_services"
            review_scroll.display = step == "review"
            empty.display = False
            if step == "welcome":
                welcome.update(
                    "envctl is the CLI for configuring, planning, and operating "
                    "this repository's local environments.\n\n"
                    "This wizard will guide you through:\n"
                    "- selecting the default mode (main or trees)\n"
                    "- deciding which components envctl should manage\n"
                    "- reviewing directories, ports, and the generated .envctl file\n\n"
                    f"The configuration will be written to {local_state.config_file_path}.\n"
                    f"Starting values are loaded from: {source_label}."
                )
                return
            if step == "default_mode":
                self._render_choice_step(
                    list_view,
                    selected=self.values.default_mode,
                    options=(("main", "Main"), ("trees", "Trees")),
                )
                return
            if step == "components":
                self._render_components_step(list_view)
                return
            if step == "service_startup":
                self._render_service_startup_step(list_view)
                return
            if step == "additional_services":
                self._sync_additional_service_inputs()
                return
            if step == "directories":
                visible_fields = _visible_directory_fields(self.values)
                self._sync_directory_inputs(visible_fields)
                if not visible_fields:
                    empty.update(
                        "No directories need configuration for the components currently configured in main or trees."
                    )
                    empty.display = True
                return
            if step == "commands":
                visible_fields = _visible_command_fields(self.values)
                self._sync_directory_inputs(visible_fields)
                if not visible_fields:
                    empty.update(
                        "No entrypoints or test commands need configuration "
                        "for the components currently configured in main or trees."
                    )
                    empty.display = True
                return
            if step == "ports":
                visible_fields = _visible_port_fields(self.values)
                self._sync_port_inputs(visible_fields)
                if not visible_fields:
                    empty.update(
                        "No ports need configuration for the components currently configured in main or trees."
                    )
                    empty.display = True
                return
            if step == "review":
                review.update(
                    config_review_text(
                        path=local_state.config_file_path,
                        values=self.values,
                        source_label=source_label,
                        ignore_warning=(
                            "envctl local artifacts are managed through Git global excludes instead of repo "
                            ".gitignore. On save, envctl configures or updates core.excludesFile to keep "
                            ".envctl, MAIN_TASK.md, OLD_TASK_*.md, trees/, and trees-* out of git status."
                        ),
                    )
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
            back.disabled = self.step_index == 0
            next_button.label = "Save" if self.step_index == len(self._steps) - 1 else "Next"

        def _refresh_status(self, message: str | None = None) -> None:
            status = self.query_one("#config-status", Static)
            if message is not None:
                self._last_status_message = message
                status.update(message)
                self.refresh_bindings()
                return
            step = self._current_step()
            if step in {"components", "service_startup", "additional_services", "review"}:
                validation = validate_managed_values(
                    self.values,
                    require_entrypoints=step == "review",
                )
                if validation.valid:
                    status.update(
                        status_for_valid_config_step(
                            step,
                            component_split_available=self._component_split_available(),
                        )
                    )
                else:
                    status.update(validation.errors[0])
                self.refresh_bindings()
                return
            if step == "directories":
                visible_fields = _visible_directory_fields(self.values)
                status.update(
                    directory_step_status(
                        visible_fields=visible_fields,
                        first_error=(
                            self._first_directory_error(visible_fields=visible_fields) if visible_fields else None
                        ),
                    )
                )
                self.refresh_bindings()
                return
            if step == "commands":
                visible_fields = _visible_command_fields(self.values)
                status.update(
                    command_step_status(
                        visible_fields=visible_fields,
                        first_error=(
                            self._first_directory_error(visible_fields=visible_fields) if visible_fields else None
                        ),
                    )
                )
                self.refresh_bindings()
                return
            if step == "ports":
                visible_fields = _visible_port_fields(self.values)
                status.update(port_step_status(visible_fields=visible_fields))
                self.refresh_bindings()
                return
            status.update(fallback_step_status())
            self.refresh_bindings()

        def _focus_current_step(self) -> None:
            step = self._current_step()
            if step in {"default_mode", "components", "service_startup"}:
                list_view = self.query_one("#config-list", ListView)
                if step == "components":
                    list_view.index = self._nearest_selectable_component_index(list_view.index or 0, step=1)
                focus_selectable_list(self, list_view, list_view.index)
            elif step in {"directories", "commands"}:
                visible_fields = (
                    _visible_directory_fields(self.values)
                    if step == "directories"
                    else _visible_command_fields(self.values)
                )
                if visible_fields:
                    self.query_one(f"#{_directory_input_id(visible_fields[0][0])}", Input).focus()
                else:
                    self.query_one("#btn-next", Button).focus()
            elif step == "ports":
                visible_fields = _visible_port_fields(self.values)
                if visible_fields:
                    self.query_one(f"#{_port_input_id(visible_fields[0][0])}", Input).focus()
                else:
                    self.query_one("#btn-next", Button).focus()
            elif step == "additional_services":
                self.query_one(f"#{_additional_service_input_id('slug')}", Input).focus()
            elif step == "review":
                self.query_one("#config-review-scroll", VerticalScroll).focus()
            else:
                self.query_one("#btn-next", Button).focus()

        def _field_value(self, field_name: str) -> int | str:
            return value_policy.wizard_field_value(self.values, field_name)

        def _sync_startup_enable_flags(self) -> None:
            component_policy.sync_startup_enable_flags(
                self.values,
                include_service_startup=self._should_show_service_startup_step(),
            )

        def _nearest_selectable_component_index(self, index: int, *, step: int) -> int:
            return self._component_interaction.nearest_selectable_index(index, step=step)

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
            if self._current_step() not in {"default_mode", "components", "service_startup"}:
                return
            list_view = self.query_one("#config-list", ListView)
            list_view.index = move_config_wizard_list_index(list_view.index, count=len(list_view.children), step=-1)
            if self._current_step() == "components":
                list_view.index = self._nearest_selectable_component_index(list_view.index or 0, step=-1)
            self._sync_focus_driven_selection()
            self._refresh_status()

        def action_cursor_down(self) -> None:
            if self._current_step() not in {"default_mode", "components", "service_startup"}:
                return
            list_view = self.query_one("#config-list", ListView)
            count = len(list_view.children)
            next_index = move_config_wizard_list_index(list_view.index, count=count, step=1)
            if next_index is None:
                return
            list_view.index = next_index
            if self._current_step() == "components":
                list_view.index = self._nearest_selectable_component_index(list_view.index or 0, step=1)
            self._sync_focus_driven_selection()
            self._refresh_status()

        def _sync_focus_driven_selection(self) -> None:
            if self._current_step() != "default_mode":
                return
            list_view = self.query_one("#config-list", ListView)
            index = list_view.index or 0
            self.values.default_mode = "trees" if index == 1 else "main"
            self._refresh_body()
            self._refresh_status()

        def action_toggle_item(self) -> None:
            step = self._current_step()
            if step == "components":
                self._toggle_components_row()
                return
            if step == "service_startup":
                self._toggle_service_startup_row()

        def _toggle_service_startup_row(self) -> None:
            list_view = self.query_one("#config-list", ListView)
            index = list_view.index or 0
            field_name, mode, _label = _SERVICE_STARTUP_FIELDS[index]
            self._toggle_service_startup_value(field_name, mode)
            self._sync_steps(current_step="service_startup")
            self._refresh_body()
            self._refresh_status()
            self._refresh_actions()
            list_view = self.query_one("#config-list", ListView)
            apply_selectable_list_index(list_view, min(index, max(len(list_view.children) - 1, 0)))
            focus_selectable_list(self, list_view, list_view.index)

        def _toggle_components_row(self) -> None:
            list_view = self.query_one("#config-list", ListView)
            index = list_view.index or 0
            result = self._component_interaction.toggle_component_at(index)
            if not result.changed:
                return
            self._sync_startup_enable_flags()
            self._sync_steps(current_step="components")
            self._refresh_body()
            self._refresh_status()
            self._refresh_actions()
            list_view = self.query_one("#config-list", ListView)
            apply_selectable_list_index(list_view, min(result.target_index, max(len(list_view.children) - 1, 0)))
            focus_selectable_list(self, list_view, list_view.index)

        def _toggle_component_split(self) -> None:
            if not self._component_split_available():
                return
            list_view = self.query_one("#config-list", ListView)
            index = list_view.index or 0
            result = self._component_interaction.toggle_split_at(index)
            if not result.changed:
                if result.error_message is not None:
                    self._refresh_status(result.error_message)
                return
            self._refresh_body()
            self._refresh_status()
            list_view = self.query_one("#config-list", ListView)
            apply_selectable_list_index(list_view, result.target_index)
            focus_selectable_list(self, list_view, list_view.index)

        def _component_split_available(self) -> bool:
            if self._current_step() != "components":
                return False
            list_view = self.query_one("#config-list", ListView)
            if self.focused is not list_view:
                return False
            rows = self._component_rows()
            if not rows:
                return False
            index = list_view.index or 0
            if index < 0 or index >= len(rows):
                return False
            return rows[index].selectable

        def on_list_view_selected(self, event: ListView.Selected) -> None:
            if self._suppress_list_selected_once:
                self._suppress_list_selected_once = False
                return
            step = self._current_step()
            if step not in {"default_mode", "components", "service_startup"}:
                return
            list_view = self.query_one("#config-list", ListView)
            list_view.index = event.index
            if step == "default_mode":
                self._sync_focus_driven_selection()
            elif step == "components":
                self._toggle_components_row()
            else:
                self._toggle_service_startup_row()

        def action_focus_next(self) -> None:
            self.screen.focus_next()
            self._refresh_status()

        def action_focus_previous(self) -> None:
            self.screen.focus_previous()
            self._refresh_status()

        def action_cycle_command_suggestion(self) -> None:
            field_name = self._focused_suggestion_field()
            if field_name is None:
                return
            suggestions = self._suggestions_by_field.get(field_name, ())
            if not suggestions:
                self._refresh_status("No suggestions are available for the focused field.")
                return
            focused = self.focused
            if not isinstance(focused, Input):
                return
            result = cycle_config_wizard_suggestion(
                self._suggestions_by_field,
                field_name=field_name,
                current_value=str(focused.value or ""),
            )
            if result is None:
                return
            suggestion = result.suggestion
            next_value = result.value
            focused.value = next_value
            setattr(self.values, field_name, next_value)
            self._refresh_directory_validation(field_name, raw=next_value)
            self._refresh_field_hint(field_name, raw=next_value)
            _emit(
                emit,
                "ui.config_wizard.suggestion.accepted",
                field=field_name,
                source=suggestion.source,
                confidence=suggestion.confidence,
            )
            self._refresh_status(f"Accepted suggestion for {self._directory_label(field_name)}.")

        def action_cancel(self) -> None:
            self.exit(None)

        def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
            if action == "toggle_component_split":
                return True if self._component_split_available() else False
            if action == "cycle_command_suggestion":
                field_name = self._focused_suggestion_field()
                return True if field_name is not None and bool(self._suggestions_by_field.get(field_name)) else False
            return super().check_action(action, parameters)

        def action_go_back(self) -> None:
            self._go_back()

        def action_toggle_component_split(self) -> None:
            self._toggle_component_split()

        def action_submit_or_next(self) -> None:
            if self._current_step() in {"default_mode", "components", "service_startup"}:
                list_view = self.query_one("#config-list", ListView)
                if list_view.has_focus:
                    self._suppress_list_selected_once = True
            self._advance()

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
            if self.step_index <= 0:
                return
            self.step_index -= 1
            self._refresh_all()

        def _advance(self) -> None:
            step = self._current_step()
            if step in {"directories", "commands"} and not self._apply_directory_inputs():
                return
            if step == "additional_services" and not self._apply_additional_service_inputs():
                return
            if step == "ports" and not self._apply_port_inputs():
                return
            if step in {
                "components",
                "service_startup",
                "additional_services",
                "directories",
                "commands",
                "ports",
                "review",
            }:
                validation = validate_managed_values(
                    self.values,
                    require_directories=step in {"directories", "commands", "ports", "review"},
                    require_entrypoints=step in {"commands", "ports", "review"},
                )
                if not validation.valid:
                    self._refresh_status(validation.errors[0])
                    return
            if step == self._steps[-1]:
                save_result = save_local_config_with_ignore_policy(
                    local_state=local_state,
                    values=self.values,
                    update_global_ignores=True,
                )
                self._save_result = save_result
                self.exit(ConfigWizardResult(values=self.values, save_result=save_result))
                return
            self.step_index += 1
            self._refresh_all()

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
