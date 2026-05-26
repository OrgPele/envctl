from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from ....config.persistence import ManagedConfigValues
from .config_wizard_fields import (
    CONFIG_ROW_STYLES_CSS,
    _ADDITIONAL_SERVICE_FIELDS,
    _COMMAND_FIELDS,
    _DIRECTORY_FIELDS,
    _PORT_FIELDS,
    _additional_service_field_value,
    _additional_service_input_id,
    _directory_error_id,
    _directory_hint_id,
    _directory_input_id,
    _field_label_id,
    _field_placeholder,
    _port_input_id,
)

CONFIG_WIZARD_APP_CSS = (
    """
Screen {
    align: center middle;
}
#config-shell {
    width: 94%;
    max-width: 140;
    height: 94%;
    border: round $accent;
    padding: 1 2;
}
#config-title {
    text-style: bold;
    margin-bottom: 1;
}
#config-source {
    color: $text-muted;
    margin-bottom: 1;
}
#config-step-title {
    text-style: bold;
}
#config-step-help {
    color: $text-muted;
    margin-bottom: 1;
}
#config-body {
    height: 1fr;
    border: round $surface;
    padding: 0 1;
}
#config-list {
    height: 1fr;
    border: tall $surface;
}
.config-section-header {
    margin-top: 1;
    padding: 0 1;
    background: transparent;
    border-left: none;
}
.config-section-header Label {
    color: $accent;
    text-style: bold;
}
.config-section-header.-highlight {
    background: transparent;
    border-left: none;
}
#config-ports {
    height: 1fr;
    overflow: auto;
}
#config-additional-services {
    height: 1fr;
    overflow: auto;
}
#config-directories {
    height: 1fr;
    overflow: auto;
}
#config-empty {
    color: $text-muted;
}
.directory-field {
    margin-bottom: 1;
}
.directory-field.directory-invalid {
    background: $error 10%;
    border: tall $error;
}
.directory-error {
    color: $text-muted;
    margin-top: -1;
    margin-bottom: 1;
}
.directory-hint {
    color: $text-muted;
    margin-top: -1;
    margin-bottom: 1;
}
.directory-error-visible {
    color: $error;
}
.port-field {
    margin-bottom: 1;
}
.additional-service-field {
    margin-bottom: 1;
}
#config-review-scroll {
    height: 1fr;
    overflow: auto;
}
#config-review {
    height: auto;
}
#config-status {
    margin-top: 1;
    color: $text-muted;
}
#config-actions {
    margin-top: 1;
    align-horizontal: right;
    height: auto;
}
"""
    + CONFIG_ROW_STYLES_CSS
)


def compose_config_wizard_layout(
    *,
    values: ManagedConfigValues,
    field_value: Callable[[str], int | str],
    horizontal_cls: type[Any],
    vertical_cls: type[Any],
    vertical_scroll_cls: type[Any],
    button_cls: type[Any],
    footer_cls: type[Any],
    input_cls: type[Any],
    label_cls: type[Any],
    list_view_cls: type[Any],
    static_cls: type[Any],
) -> Iterator[Any]:
    with vertical_cls(id="config-shell"):
        yield static_cls("envctl Run Configuration", id="config-title")
        yield static_cls("", id="config-source")
        yield static_cls("", id="config-step-title")
        yield static_cls("", id="config-step-help")
        with vertical_cls(id="config-body"):
            yield static_cls("", id="config-welcome")
            yield list_view_cls(id="config-list")
            yield static_cls("", id="config-empty")
            with vertical_scroll_cls(id="config-directories"):
                for field_name, label in (*_DIRECTORY_FIELDS, *_COMMAND_FIELDS):
                    yield label_cls(label, id=_field_label_id("directory", field_name))
                    yield input_cls(
                        value=str(field_value(field_name)),
                        id=_directory_input_id(field_name),
                        placeholder=_field_placeholder(field_name),
                        classes="directory-field",
                    )
                    yield static_cls("", id=_directory_hint_id(field_name), classes="directory-hint")
                    yield static_cls("", id=_directory_error_id(field_name), classes="directory-error")
            with vertical_scroll_cls(id="config-ports"):
                for field_name, label in _PORT_FIELDS:
                    yield label_cls(label, id=_field_label_id("port", field_name))
                    yield input_cls(
                        value=str(field_value(field_name)),
                        id=_port_input_id(field_name),
                        classes="port-field",
                    )
            with vertical_scroll_cls(id="config-additional-services"):
                service = values.additional_services[0] if values.additional_services else None
                for field_name, label in _ADDITIONAL_SERVICE_FIELDS:
                    yield label_cls(label, id=_field_label_id("additional-service", field_name))
                    yield input_cls(
                        value=_additional_service_field_value(service, field_name),
                        id=_additional_service_input_id(field_name),
                        placeholder=_field_placeholder(f"additional_service_{field_name}"),
                        classes="additional-service-field",
                    )
            with vertical_scroll_cls(id="config-review-scroll"):
                yield static_cls("", id="config-review")
        yield static_cls("", id="config-status")
        with horizontal_cls(id="config-actions"):
            yield button_cls("Cancel", id="btn-cancel")
            yield button_cls("Back", id="btn-back")
            yield button_cls("Next", variant="success", id="btn-next")
        yield footer_cls()
