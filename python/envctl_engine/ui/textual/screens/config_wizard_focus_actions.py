from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ....config.persistence import ManagedConfigValues
from .config_wizard_fields import (
    _additional_service_input_id,
    _directory_input_id,
    _port_input_id,
    _visible_command_fields,
    _visible_directory_fields,
    _visible_port_fields,
)


_LIST_FOCUS_STEPS = {"default_mode", "components", "service_startup"}


@dataclass(slots=True)
class ConfigWizardFocusActions:
    values: ManagedConfigValues
    current_step: Callable[[], str]
    list_view: Callable[[], Any]
    nearest_selectable_component_index: Callable[..., int]
    focus_list: Callable[[Any, int | None], None]
    focus_widget: Callable[[str], None]

    def focus_current_step(self) -> None:
        step = self.current_step()
        if step in _LIST_FOCUS_STEPS:
            self._focus_choice_list(step)
            return
        if step in {"directories", "commands"}:
            self._focus_first_directory_or_command_field(step)
            return
        if step == "ports":
            self._focus_first_port_field()
            return
        if step == "additional_services":
            self.focus_widget(_additional_service_input_id("slug"))
            return
        if step == "review":
            self.focus_widget("config-review-scroll")
            return
        self._focus_next_button()

    def _focus_choice_list(self, step: str) -> None:
        list_view = self.list_view()
        if step == "components":
            list_view.index = self.nearest_selectable_component_index(list_view.index or 0, step=1)
        self.focus_list(list_view, list_view.index)

    def _focus_first_directory_or_command_field(self, step: str) -> None:
        visible_fields = (
            _visible_directory_fields(self.values) if step == "directories" else _visible_command_fields(self.values)
        )
        if not visible_fields:
            self._focus_next_button()
            return
        self.focus_widget(_directory_input_id(visible_fields[0][0]))

    def _focus_first_port_field(self) -> None:
        visible_fields = _visible_port_fields(self.values)
        if not visible_fields:
            self._focus_next_button()
            return
        self.focus_widget(_port_input_id(visible_fields[0][0]))

    def _focus_next_button(self) -> None:
        self.focus_widget("btn-next")
