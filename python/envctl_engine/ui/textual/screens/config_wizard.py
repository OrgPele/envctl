from __future__ import annotations

from typing import Callable

from ....config import LocalConfigState
from ....config.persistence import ManagedConfigValues
from envctl_engine.ui.capabilities import textual_importable as _textual_importable
from .config_wizard_app import ConfigWizardResult, _emit, build_config_wizard_app
from .config_wizard_fields import (
    CONFIG_ROW_STYLES_CSS,
    _PORT_FIELDS as _PORT_FIELDS,
    _additional_service_input_id,
    _clone_values,
    _directory_validation_message,
    _hydrate_wizard_values,
    _port_input_id as _port_input_id,
    _should_hydrate_directory_value,
    _visible_command_fields,
    _visible_directory_fields,
    _visible_port_fields,
)


__all__ = [
    "CONFIG_ROW_STYLES_CSS",
    "ConfigWizardResult",
    "_PORT_FIELDS",
    "_additional_service_input_id",
    "_clone_values",
    "_directory_validation_message",
    "_hydrate_wizard_values",
    "_should_hydrate_directory_value",
    "_visible_command_fields",
    "_visible_directory_fields",
    "_visible_port_fields",
    "run_config_wizard_textual",
]


def run_config_wizard_textual(
    *,
    local_state: LocalConfigState,
    initial_values: ManagedConfigValues | None = None,
    emit: Callable[..., None] | None = None,
    build_only: bool = False,
    default_wizard_type: str = "simple",
) -> ConfigWizardResult | None | object:
    if not _textual_importable():
        _emit(emit, "ui.fallback.non_interactive", reason="textual_missing", command="config_wizard")
        return None

    app, run_policy = build_config_wizard_app(
        local_state=local_state,
        initial_values=initial_values,
        emit=emit,
        default_wizard_type=default_wizard_type,
    )
    if build_only:
        return app
    _emit(
        emit,
        "ui.textual.run_policy",
        screen="config_wizard",
        mouse_enabled=run_policy.mouse,
        reason=run_policy.reason,
        term_program=run_policy.term_program,
    )
    return app.run(mouse=run_policy.mouse)
