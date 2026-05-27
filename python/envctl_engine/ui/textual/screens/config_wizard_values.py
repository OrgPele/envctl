from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from ....config.persistence import ManagedConfigValues, validate_managed_values
from .config_wizard_fields import _directory_validation_message, _entrypoint_validation_message


@dataclass(frozen=True, slots=True)
class ConfigWizardValueApplyResult:
    valid: bool = True
    error_message: str | None = None
    focus_field: str | None = None


FieldSpec = Sequence[tuple[str, str]]


_VALUE_FIELDS = {
    "backend_dir_name": "backend_dir_name",
    "frontend_dir_name": "frontend_dir_name",
    "backend_start_cmd": "backend_start_cmd",
    "frontend_start_cmd": "frontend_start_cmd",
    "backend_test_cmd": "backend_test_cmd",
    "frontend_test_cmd": "frontend_test_cmd",
    "frontend_test_path": "frontend_test_path",
}


_PORT_FIELDS = {
    "backend_port_base": lambda values: values.port_defaults.backend_port_base,
    "frontend_port_base": lambda values: values.port_defaults.frontend_port_base,
    "db_port_base": lambda values: values.port_defaults.db_port_base,
    "redis_port_base": lambda values: values.port_defaults.redis_port_base,
    "n8n_port_base": lambda values: values.port_defaults.n8n_port_base,
    "port_spacing": lambda values: values.port_defaults.port_spacing,
}


def wizard_field_value(values: ManagedConfigValues, field_name: str) -> int | str:
    if field_name in _VALUE_FIELDS:
        return getattr(values, _VALUE_FIELDS[field_name])
    port_value = _PORT_FIELDS.get(field_name)
    if port_value is not None:
        return port_value(values)
    return 0


def validate_text_field(base_dir: Path, field_name: str, label: str, raw: str) -> str | None:
    if field_name in {"backend_start_cmd", "frontend_start_cmd"}:
        return _entrypoint_validation_message(label, raw)
    if field_name in {"backend_test_cmd", "frontend_test_cmd"}:
        return None
    if field_name == "frontend_test_path":
        return _directory_validation_message(base_dir, label, raw) if raw else None
    return _directory_validation_message(base_dir, label, raw)


def apply_text_field_values(
    values: ManagedConfigValues,
    *,
    base_dir: Path,
    visible_fields: FieldSpec,
    raw_values: Mapping[str, str],
) -> ConfigWizardValueApplyResult:
    validated: dict[str, str] = {}
    for field_name, label in visible_fields:
        raw = raw_values.get(field_name, "").strip()
        error = validate_text_field(base_dir, field_name, label, raw)
        if error is not None:
            return ConfigWizardValueApplyResult(valid=False, error_message=error, focus_field=field_name)
        validated[field_name] = raw
    for field_name, raw in validated.items():
        setattr(values, field_name, raw)
    return ConfigWizardValueApplyResult()


def apply_port_field_values(
    values: ManagedConfigValues,
    *,
    visible_fields: FieldSpec,
    raw_values: Mapping[str, str],
) -> ConfigWizardValueApplyResult:
    new_values: dict[str, int] = {}
    for field_name, label in visible_fields:
        raw = raw_values.get(field_name, "").strip()
        if not raw.isdigit() or int(raw) < 1:
            return ConfigWizardValueApplyResult(
                valid=False,
                error_message=f"{label} must be a positive integer.",
                focus_field=field_name,
            )
        new_values[field_name] = int(raw)
    candidate = deepcopy(values)
    for field_name, value in new_values.items():
        apply_port_field_value(candidate, field_name, value)
    validation = validate_managed_values(candidate)
    if not validation.valid:
        return ConfigWizardValueApplyResult(valid=False, error_message=validation.errors[0])
    for field_name, value in new_values.items():
        apply_port_field_value(values, field_name, value)
    return ConfigWizardValueApplyResult()


def apply_port_field_value(values: ManagedConfigValues, field_name: str, value: int) -> None:
    if field_name == "backend_port_base":
        values.port_defaults.backend_port_base = value
    elif field_name == "frontend_port_base":
        values.port_defaults.frontend_port_base = value
    elif field_name == "db_port_base":
        values.port_defaults.dependency_ports.setdefault("postgres", {})["primary"] = value
        values.port_defaults.dependency_ports.setdefault("supabase", {})["db"] = value
    elif field_name == "redis_port_base":
        values.port_defaults.dependency_ports.setdefault("redis", {})["primary"] = value
    elif field_name == "n8n_port_base":
        values.port_defaults.dependency_ports.setdefault("n8n", {})["primary"] = value
    elif field_name == "port_spacing":
        values.port_defaults.port_spacing = value
