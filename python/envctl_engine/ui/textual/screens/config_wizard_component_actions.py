from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ....config.persistence import ManagedConfigValues
from envctl_engine.ui.textual.list_row_styles import apply_selectable_list_index, focus_selectable_list
from . import config_wizard_components as component_policy
from .config_wizard_components import ConfigWizardComponentInteraction
from .config_wizard_navigation import move_config_wizard_list_index


@dataclass(slots=True)
class ConfigWizardComponentActions:
    app: Any
    values: ManagedConfigValues
    component_interaction: ConfigWizardComponentInteraction
    service_startup_fields: Sequence[tuple[str, str, str]]
    current_step: Callable[[], str]
    list_view: Callable[[], Any]
    focused_widget: Callable[[], Any]
    sync_steps: Callable[..., None]
    sync_startup_enable_flags: Callable[[], None]
    refresh_body: Callable[[], None]
    refresh_status: Callable[..., None]
    refresh_actions: Callable[[], None]

    def cursor_up(self) -> None:
        if self.current_step() not in {"default_mode", "components", "service_startup"}:
            return
        list_view = self.list_view()
        list_view.index = move_config_wizard_list_index(list_view.index, count=len(list_view.children), step=-1)
        if self.current_step() == "components":
            list_view.index = self.nearest_selectable_component_index(list_view.index or 0, step=-1)
        self.sync_focus_driven_selection()
        self.refresh_status()

    def cursor_down(self) -> None:
        if self.current_step() not in {"default_mode", "components", "service_startup"}:
            return
        list_view = self.list_view()
        next_index = move_config_wizard_list_index(list_view.index, count=len(list_view.children), step=1)
        if next_index is None:
            return
        list_view.index = next_index
        if self.current_step() == "components":
            list_view.index = self.nearest_selectable_component_index(list_view.index or 0, step=1)
        self.sync_focus_driven_selection()
        self.refresh_status()

    def sync_focus_driven_selection(self) -> None:
        if self.current_step() != "default_mode":
            return
        list_view = self.list_view()
        index = list_view.index or 0
        self.values.default_mode = "trees" if index == 1 else "main"
        self.refresh_body()
        self.refresh_status()

    def toggle_item(self) -> None:
        step = self.current_step()
        if step == "components":
            self.toggle_components_row()
            return
        if step == "service_startup":
            self.toggle_service_startup_row()

    def toggle_service_startup_row(self) -> None:
        list_view = self.list_view()
        index = list_view.index or 0
        field_name, mode, _label = self.service_startup_fields[index]
        component_policy.toggle_service_startup_value(self.values, field_name, mode)
        self.sync_steps(current_step="service_startup")
        self.refresh_body()
        self.refresh_status()
        self.refresh_actions()
        list_view = self.list_view()
        self._focus_list_index(list_view, min(index, max(len(list_view.children) - 1, 0)))

    def toggle_components_row(self) -> None:
        list_view = self.list_view()
        index = list_view.index or 0
        result = self.component_interaction.toggle_component_at(index)
        if not result.changed:
            return
        self.sync_startup_enable_flags()
        self.sync_steps(current_step="components")
        self.refresh_body()
        self.refresh_status()
        self.refresh_actions()
        list_view = self.list_view()
        self._focus_list_index(list_view, min(result.target_index, max(len(list_view.children) - 1, 0)))

    def toggle_component_split(self) -> None:
        if not self.component_split_available():
            return
        list_view = self.list_view()
        index = list_view.index or 0
        result = self.component_interaction.toggle_split_at(index)
        if not result.changed:
            if result.error_message is not None:
                self.refresh_status(result.error_message)
            return
        self.refresh_body()
        self.refresh_status()
        list_view = self.list_view()
        self._focus_list_index(list_view, result.target_index)

    def component_split_available(self) -> bool:
        if self.current_step() != "components":
            return False
        list_view = self.list_view()
        if self.focused_widget() is not list_view:
            return False
        rows = self.component_interaction.rows()
        if not rows:
            return False
        index = list_view.index or 0
        if index < 0 or index >= len(rows):
            return False
        return rows[index].selectable

    def list_view_selected(self, *, index: int) -> None:
        step = self.current_step()
        if step not in {"default_mode", "components", "service_startup"}:
            return
        list_view = self.list_view()
        list_view.index = index
        if step == "default_mode":
            self.sync_focus_driven_selection()
            return
        if step == "components":
            self.toggle_components_row()
            return
        self.toggle_service_startup_row()

    def nearest_selectable_component_index(self, index: int, *, step: int) -> int:
        return self.component_interaction.nearest_selectable_index(index, step=step)

    def _focus_list_index(self, list_view: Any, index: int | None) -> None:
        apply_selectable_list_index(list_view, index)
        focus_selectable_list(self.app, list_view, list_view.index)
