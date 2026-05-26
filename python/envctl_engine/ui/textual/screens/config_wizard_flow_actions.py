from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from ....config.persistence import ManagedConfigValues


_VALIDATED_STEPS = {
    "components",
    "service_startup",
    "additional_services",
    "directories",
    "commands",
    "ports",
    "review",
}
_LIST_SUPPRESSION_STEPS = {"default_mode", "components", "service_startup"}


@dataclass(slots=True)
class ConfigWizardFlowActions:
    values: ManagedConfigValues
    steps: Callable[[], Sequence[str]]
    step_index: Callable[[], int]
    set_step_index: Callable[[int], None]
    set_suppress_list_selected_once: Callable[[bool], None]
    set_save_result: Callable[[Any], None]
    current_step: Callable[[], str]
    list_has_focus: Callable[[], bool]
    refresh_all: Callable[[], None]
    refresh_status: Callable[..., None]
    apply_directory_inputs: Callable[[], bool]
    apply_additional_service_inputs: Callable[[], bool]
    apply_port_inputs: Callable[[], bool]
    validate_values: Callable[..., Any]
    save_config: Callable[[], Any]
    exit_with_result: Callable[[Any], None]
    result_factory: Callable[[ManagedConfigValues, Any], Any]

    def go_back(self) -> None:
        if self.step_index() <= 0:
            return
        self.set_step_index(self.step_index() - 1)
        self.refresh_all()

    def submit_or_next(self) -> None:
        if self.current_step() in _LIST_SUPPRESSION_STEPS and self.list_has_focus():
            self.set_suppress_list_selected_once(True)
        self.advance()

    def advance(self) -> None:
        step = self.current_step()
        if step in {"directories", "commands"} and not self.apply_directory_inputs():
            return
        if step == "additional_services" and not self.apply_additional_service_inputs():
            return
        if step == "ports" and not self.apply_port_inputs():
            return
        if not self._validate_current_step(step):
            return
        if step == self.steps()[-1]:
            self._save_and_exit()
            return
        self.set_step_index(self.step_index() + 1)
        self.refresh_all()

    def _validate_current_step(self, step: str) -> bool:
        if step not in _VALIDATED_STEPS:
            return True
        validation = self.validate_values(
            values=self.values,
            require_directories=step in {"directories", "commands", "ports", "review"},
            require_entrypoints=step in {"commands", "ports", "review"},
        )
        if bool(getattr(validation, "valid", False)):
            return True
        errors = list(getattr(validation, "errors", []) or [])
        self.refresh_status(errors[0] if errors else "Configuration is invalid.")
        return False

    def _save_and_exit(self) -> None:
        save_result = self.save_config()
        self.set_save_result(save_result)
        self.exit_with_result(self.result_factory(self.values, save_result))
