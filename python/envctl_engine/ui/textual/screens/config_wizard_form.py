from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from ....config.persistence import ManagedConfigValues, validate_managed_values
from . import config_wizard_values as value_policy
from .config_wizard_fields import (
    _ADDITIONAL_SERVICE_FIELDS,
    _COMMAND_FIELDS,
    _DIRECTORY_FIELDS,
    _PORT_FIELDS,
    _additional_service_field_value,
    _additional_service_input_id,
    build_additional_service_from_input_values,
    _directory_error_id,
    _directory_hint_id,
    _directory_input_id,
    _field_label_id,
    _port_input_id,
)
from .config_wizard_hints import ConfigWizardHintResolver


class _QueryApp(Protocol):
    def query_one(self, selector: str, widget_type: object = ...) -> Any: ...


class ConfigWizardFormController:
    def __init__(
        self,
        *,
        app: _QueryApp,
        values: ManagedConfigValues,
        base_dir: Path,
        hints: ConfigWizardHintResolver,
        input_cls: object,
        label_cls: object,
        static_cls: object,
        refresh_status: Callable[[str | None], None],
        current_step: Callable[[], str],
    ) -> None:
        self.app = app
        self.values = values
        self.base_dir = base_dir
        self.hints = hints
        self.input_cls = input_cls
        self.label_cls = label_cls
        self.static_cls = static_cls
        self.refresh_status = refresh_status
        self.current_step = current_step

    def sync_directory_inputs(self, visible_fields: tuple[tuple[str, str], ...]) -> None:
        visible_names = {field_name for field_name, _label in visible_fields}
        for field_name, _label in (*_DIRECTORY_FIELDS, *_COMMAND_FIELDS):
            label = self.app.query_one(f"#{_field_label_id('directory', field_name)}", self.label_cls)
            directory_input = self.app.query_one(f"#{_directory_input_id(field_name)}", self.input_cls)
            hint = self.app.query_one(f"#{_directory_hint_id(field_name)}", self.static_cls)
            error = self.app.query_one(f"#{_directory_error_id(field_name)}", self.static_cls)
            label.display = field_name in visible_names
            directory_input.display = field_name in visible_names
            hint.display = field_name in visible_names
            error.display = field_name in visible_names
            if field_name in visible_names:
                directory_input.value = str(self.field_value(field_name))
                self.refresh_directory_validation(field_name)
                self.refresh_field_hint(field_name, raw=directory_input.value)
            else:
                directory_input.remove_class("directory-invalid")
                hint.update("")
                error.update("")
                error.remove_class("directory-error-visible")

    def sync_port_inputs(self, visible_fields: tuple[tuple[str, str], ...]) -> None:
        visible_names = {field_name for field_name, _label in visible_fields}
        for field_name, _label in _PORT_FIELDS:
            label = self.app.query_one(f"#{_field_label_id('port', field_name)}", self.label_cls)
            port_input = self.app.query_one(f"#{_port_input_id(field_name)}", self.input_cls)
            label.display = field_name in visible_names
            port_input.display = field_name in visible_names
            if field_name in visible_names:
                port_input.value = str(self.field_value(field_name))

    def sync_additional_service_inputs(self) -> None:
        service = self.values.additional_services[0] if self.values.additional_services else None
        for field_name, _label in _ADDITIONAL_SERVICE_FIELDS:
            service_input = self.app.query_one(f"#{_additional_service_input_id(field_name)}", self.input_cls)
            service_input.value = _additional_service_field_value(service, field_name)

    def additional_service_input_value(self, field_name: str) -> str:
        service_input = self.app.query_one(f"#{_additional_service_input_id(field_name)}", self.input_cls)
        return str(service_input.value or "").strip()

    def apply_additional_service_inputs(self) -> bool:
        existing_service = self.values.additional_services[0] if self.values.additional_services else None
        result = build_additional_service_from_input_values(
            self.additional_service_input_value,
            existing_service=existing_service,
        )
        if result.remove_current:
            self.values.additional_services = self.values.additional_services[1:]
            return True
        if result.error_message is not None:
            self.refresh_status(result.error_message)
            if result.focus_field is not None:
                self.app.query_one(f"#{_additional_service_input_id(result.focus_field)}", self.input_cls).focus()
            return False
        if result.service is not None:
            self.values.additional_services = (result.service, *self.values.additional_services[1:])
        validation = validate_managed_values(self.values, require_directories=False, require_entrypoints=False)
        if not validation.valid:
            self.refresh_status(validation.errors[0])
            return False
        return True

    def field_value(self, field_name: str) -> int | str:
        return value_policy.wizard_field_value(self.values, field_name)

    def directory_label(self, field_name: str) -> str:
        return self.hints.directory_label(field_name)

    def refresh_field_hint(self, field_name: str, *, raw: str | None = None) -> None:
        hint = self.app.query_one(f"#{_directory_hint_id(field_name)}", self.static_cls)
        hint.update(self.field_hint_text(field_name, raw=raw))

    def field_hint_text(self, field_name: str, *, raw: str | None = None) -> str:
        return self.hints.field_hint_text(field_name, raw=raw)

    def directory_validation_error(self, field_name: str, *, raw: str | None = None) -> str | None:
        return self.hints.directory_validation_error(field_name, raw=raw)

    def refresh_directory_validation(self, field_name: str, *, raw: str | None = None) -> None:
        directory_input = self.app.query_one(f"#{_directory_input_id(field_name)}", self.input_cls)
        error = self.app.query_one(f"#{_directory_error_id(field_name)}", self.static_cls)
        message = self.directory_validation_error(field_name, raw=raw if raw is not None else directory_input.value)
        if message is None:
            directory_input.remove_class("directory-invalid")
            error.update("")
            error.remove_class("directory-error-visible")
            return
        directory_input.add_class("directory-invalid")
        error.update(message)
        error.add_class("directory-error-visible")

    def first_directory_error(self, *, visible_fields: tuple[tuple[str, str], ...] | None = None) -> str | None:
        fields = visible_fields if visible_fields is not None else self._default_visible_text_fields()
        for field_name, _label in fields:
            message = self.directory_validation_error(field_name)
            if message is not None:
                return message
        return None

    def apply_directory_inputs(self, visible_fields: tuple[tuple[str, str], ...] | None = None) -> bool:
        fields = visible_fields if visible_fields is not None else self._default_visible_text_fields()
        raw_values: dict[str, str] = {}
        for field_name, _label in fields:
            directory_input = self.app.query_one(f"#{_directory_input_id(field_name)}", self.input_cls)
            raw = directory_input.value.strip()
            raw_values[field_name] = raw
            self.refresh_directory_validation(field_name, raw=raw)
            self.refresh_field_hint(field_name, raw=raw)
        result = value_policy.apply_text_field_values(
            self.values,
            base_dir=self.base_dir,
            visible_fields=fields,
            raw_values=raw_values,
        )
        if not result.valid:
            self.refresh_status(result.error_message or "Invalid configuration value.")
            if result.focus_field is not None:
                self.app.query_one(f"#{_directory_input_id(result.focus_field)}", self.input_cls).focus()
            return False
        return True

    def apply_port_inputs(self, visible_fields: tuple[tuple[str, str], ...] | None = None) -> bool:
        fields = visible_fields if visible_fields is not None else _PORT_FIELDS
        raw_values: dict[str, str] = {}
        for field_name, _label in fields:
            port_input = self.app.query_one(f"#{_port_input_id(field_name)}", self.input_cls)
            raw_values[field_name] = port_input.value.strip()
        result = value_policy.apply_port_field_values(
            self.values,
            visible_fields=fields,
            raw_values=raw_values,
        )
        if not result.valid:
            self.refresh_status(result.error_message or "Invalid port configuration.")
            if result.focus_field is not None:
                self.app.query_one(f"#{_port_input_id(result.focus_field)}", self.input_cls).focus()
            return False
        return True

    def _default_visible_text_fields(self) -> tuple[tuple[str, str], ...]:
        from .config_wizard_fields import _visible_command_fields, _visible_directory_fields

        if self.current_step() == "directories":
            return _visible_directory_fields(self.values)
        return _visible_command_fields(self.values)
