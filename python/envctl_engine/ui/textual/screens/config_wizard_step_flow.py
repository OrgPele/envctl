from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from envctl_engine.config.persistence import ManagedConfigValues

from .config_wizard_fields import _wizard_steps


@dataclass(frozen=True, slots=True)
class ConfigWizardStepState:
    steps: list[str]
    step_index: int

    @property
    def current_step(self) -> str:
        return self.steps[self.step_index]


def should_show_service_startup_step(values: ManagedConfigValues) -> bool:
    profiles = (values.main_profile, values.trees_profile)
    backend_enabled = any(profile.backend_enable for profile in profiles)
    frontend_enabled = any(profile.frontend_enable for profile in profiles)
    return backend_enabled and not frontend_enabled


def sync_wizard_steps(
    values: ManagedConfigValues,
    *,
    current_steps: Sequence[str],
    step_index: int,
    current_step: str | None = None,
    include_additional_services: bool,
) -> ConfigWizardStepState:
    target_step = current_step
    if target_step is None and current_steps:
        target_step = current_steps[min(step_index, len(current_steps) - 1)]
    steps = _wizard_steps(
        values,
        include_service_startup=should_show_service_startup_step(values),
        include_additional_services=include_additional_services,
    )
    if not steps:
        return ConfigWizardStepState(steps=[], step_index=0)
    if target_step is None:
        return ConfigWizardStepState(steps=steps, step_index=min(step_index, len(steps) - 1))
    if target_step in steps:
        return ConfigWizardStepState(steps=steps, step_index=steps.index(target_step))
    if target_step == "service_startup":
        fallback = "directories"
        return ConfigWizardStepState(
            steps=steps,
            step_index=steps.index(fallback if fallback in steps else steps[-1]),
        )
    return ConfigWizardStepState(steps=steps, step_index=min(step_index, len(steps) - 1))
