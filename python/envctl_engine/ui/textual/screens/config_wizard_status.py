from __future__ import annotations

from collections.abc import Callable

from ....config.persistence import ManagedConfigValues, validate_managed_values
from .config_wizard_fields import _visible_command_fields, _visible_directory_fields, _visible_port_fields

FieldRows = tuple[tuple[str, str], ...]
FirstDirectoryError = Callable[[FieldRows], str | None]


def component_step_status(*, component_split_available: bool) -> str:
    if component_split_available:
        return (
            "Configure components for Main + Trees together, "
            "or split a row when they should differ. "
            "Use Space to toggle rows, D to split/merge, and Enter only moves forward."
        )
    return "Configure components for Main + Trees together. Use Space to toggle rows and Enter only moves forward."


def service_startup_step_status() -> str:
    return (
        "Decide whether envctl should auto-start this backend-only service "
        "and whether it should wait for a listener before continuing. "
        "Disable listener waiting for long-running scripts or workers "
        "that do not open a port. Use Space to toggle rows; Enter only moves forward."
    )


def additional_services_step_status() -> str:
    return "Edit the first additional app service. Leave the slug blank to keep no services configured."


def status_for_valid_config_step(step: str, *, component_split_available: bool) -> str:
    if step == "components":
        return component_step_status(component_split_available=component_split_available)
    if step == "service_startup":
        return service_startup_step_status()
    if step == "additional_services":
        return additional_services_step_status()
    return "Configuration is valid."


def directory_step_status(*, visible_fields: FieldRows, first_error: str | None) -> str:
    if not visible_fields:
        return "No directories are needed for the components currently configured in main or trees."
    if first_error is not None:
        return first_error
    return "Only directories for components configured in main or trees are shown."


def command_step_status(*, visible_fields: FieldRows, first_error: str | None) -> str:
    if not visible_fields:
        return "No entrypoints or test commands are needed for the configured components."
    if first_error is not None:
        return first_error
    return (
        "Test commands are optional; detected suggestions are shown under each field. "
        "Use Ctrl+S or Down on a focused suggestion field to cycle alternatives."
    )


def port_step_status(*, visible_fields: FieldRows) -> str:
    if visible_fields:
        return "Only canonical ports for configured components are shown."
    return "No ports are needed for the components currently configured in main or trees."


def fallback_step_status() -> str:
    return "Use Enter for Next/Save, Space to toggle, Escape to cancel."


def resolve_config_wizard_status(
    step: str,
    values: ManagedConfigValues,
    *,
    component_split_available: bool,
    first_directory_error: FirstDirectoryError,
) -> str:
    if step in {"components", "service_startup", "additional_services", "review"}:
        validation = validate_managed_values(
            values,
            require_entrypoints=step == "review",
        )
        if validation.valid:
            return status_for_valid_config_step(
                step,
                component_split_available=component_split_available,
            )
        return validation.errors[0]
    if step == "directories":
        visible_fields = _visible_directory_fields(values)
        return directory_step_status(
            visible_fields=visible_fields,
            first_error=first_directory_error(visible_fields) if visible_fields else None,
        )
    if step == "commands":
        visible_fields = _visible_command_fields(values)
        return command_step_status(
            visible_fields=visible_fields,
            first_error=first_directory_error(visible_fields) if visible_fields else None,
        )
    if step == "ports":
        visible_fields = _visible_port_fields(values)
        return port_step_status(visible_fields=visible_fields)
    return fallback_step_status()


def resolve_config_wizard_action_state(*, step_index: int, step_count: int) -> tuple[bool, str]:
    return step_index == 0, "Save" if step_index == step_count - 1 else "Next"
