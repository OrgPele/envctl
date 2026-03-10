from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from envctl_engine.config import LocalConfigState, discover_local_config_state
from envctl_engine.config.persistence import managed_values_from_local_state
from envctl_engine.ui.textual.screens.config_wizard import ConfigWizardResult, run_config_wizard_textual


@dataclass(slots=True)
class ConfigCommandResult:
    changed: bool
    message: str | None = None


def ensure_local_config(
    *,
    base_dir: Path,
    env: Mapping[str, str],
    emit: Callable[..., None] | None = None,
) -> ConfigCommandResult:
    local_state = discover_local_config_state(base_dir, env.get("ENVCTL_CONFIG_FILE"))
    if local_state.config_file_exists:
        return ConfigCommandResult(changed=False)
    _emit_local_config_event(emit, "config.bootstrap.required", local_state)
    _require_interactive_config_bootstrap(env)
    result = _run_wizard(local_state=local_state, emit=emit, default_wizard_type="simple")
    if result is None:
        _emit_local_config_event(emit, "config.bootstrap.cancelled", local_state)
        raise RuntimeError("Configuration wizard cancelled. envctl requires a local .envctl file to continue.")
    message = _save_message(result)
    _emit_local_config_event(emit, "config.bootstrap.saved", local_state, saved_path=str(result.save_result.path))
    return ConfigCommandResult(changed=True, message=message)


def edit_local_config(
    *,
    base_dir: Path,
    env: Mapping[str, str],
    emit: Callable[..., None] | None = None,
) -> ConfigCommandResult:
    local_state = discover_local_config_state(base_dir, env.get("ENVCTL_CONFIG_FILE"))
    _emit_local_config_event(emit, "config.command.open", local_state)
    _require_interactive_config_bootstrap(env)
    result = _run_wizard(local_state=local_state, emit=emit, default_wizard_type="advanced")
    if result is None:
        _emit_local_config_event(emit, "config.command.cancelled", local_state)
        return ConfigCommandResult(changed=False, message="Configuration edit cancelled.")
    _emit_local_config_event(emit, "config.command.saved", local_state, saved_path=str(result.save_result.path))
    return ConfigCommandResult(changed=True, message=_save_message(result))


def _run_wizard(
    *,
    local_state: LocalConfigState,
    emit: Callable[..., None] | None = None,
    default_wizard_type: str = "simple",
) -> ConfigWizardResult | None:
    initial_values = managed_values_from_local_state(local_state)
    result = run_config_wizard_textual(
        local_state=local_state,
        initial_values=initial_values,
        emit=emit,
        default_wizard_type=default_wizard_type,
    )
    if result is None:
        return None
    if not isinstance(result, ConfigWizardResult):
        return None
    return result


def _require_interactive_config_bootstrap(env: Mapping[str, str]) -> None:
    if not _has_tty(env):
        raise RuntimeError(
            "Missing repo-local .envctl and no interactive TTY is available. "
            "Run envctl from a terminal to create the config."
        )
    if not _textual_stack_available():
        raise RuntimeError(
            "Missing Textual/Rich dependencies required for initial configuration. "
            "Install with: python -m pip install -r python/requirements.txt"
        )


def _has_tty(env: Mapping[str, str]) -> bool:
    force_batch = str(env.get("ENVCTL_FORCE_BATCH", "")).strip().lower() in {"1", "true", "yes", "on"}
    if force_batch:
        return False
    try:
        import sys

        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except Exception:
        return False


def _textual_stack_available() -> bool:
    try:
        __import__("textual")
        __import__("rich")
    except Exception:
        return False
    return True


def _save_message(result: ConfigWizardResult) -> str:
    message = f"Saved startup config: {result.save_result.path}"
    if result.save_result.ignore_warning:
        return message + f" ({result.save_result.ignore_warning})"
    return message


def _emit_local_config_event(
    emit: Callable[..., None] | None,
    event: str,
    local_state: LocalConfigState,
    **payload: object,
) -> None:
    if not callable(emit):
        return
    emit(
        event,
        component="config_wizard_domain",
        config_source=local_state.config_source,
        config_path=str(local_state.config_file_path),
        legacy_source_path=str(local_state.legacy_source_path) if local_state.legacy_source_path is not None else None,
        **payload,
    )
