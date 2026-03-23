from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Callable, Mapping

from envctl_engine.config import LocalConfigState, discover_local_config_state
from envctl_engine.config.persistence import ignore_status_summary, managed_values_from_local_state
from envctl_engine.runtime.runtime_dependency_contract import (
    missing_runtime_dependency_modules,
    runtime_dependency_failure_message,
)
from envctl_engine.ui.path_links import local_paths_in_text, render_path_for_terminal, render_paths_in_terminal_text
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
    result = _run_wizard(local_state=local_state, emit=emit)
    if result is None:
        _emit_local_config_event(emit, "config.bootstrap.cancelled", local_state)
        raise RuntimeError("Configuration wizard cancelled. envctl requires a local .envctl file to continue.")
    message = _save_message(result, env=env)
    _emit_ignore_status_event(emit, local_state=local_state, result=result)
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
    result = _run_wizard(local_state=local_state, emit=emit)
    if result is None:
        _emit_local_config_event(emit, "config.command.cancelled", local_state)
        return ConfigCommandResult(changed=False, message="Configuration edit cancelled.")
    _emit_ignore_status_event(emit, local_state=local_state, result=result)
    _emit_local_config_event(emit, "config.command.saved", local_state, saved_path=str(result.save_result.path))
    return ConfigCommandResult(changed=True, message=_save_message(result, env=env))


def _run_wizard(
    *,
    local_state: LocalConfigState,
    emit: Callable[..., None] | None = None,
) -> ConfigWizardResult | None:
    initial_values = managed_values_from_local_state(local_state)
    result = run_config_wizard_textual(
        local_state=local_state,
        initial_values=initial_values,
        emit=emit,
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
        missing_modules = _missing_interactive_runtime_modules()
        raise RuntimeError(runtime_dependency_failure_message(missing_modules, env=env))


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
    return not _missing_interactive_runtime_modules()


def _missing_interactive_runtime_modules() -> list[str]:
    return missing_runtime_dependency_modules()


def _save_message(result: ConfigWizardResult, *, env: Mapping[str, str] | None = None) -> str:
    message = f"Saved startup config: {render_path_for_terminal(result.save_result.path, env=env, stream=sys.stdout)}"
    status = result.save_result.ignore_status
    status_message = ignore_status_summary(status)
    if status_message:
        rendered_status = render_paths_in_terminal_text(
            status_message,
            paths=local_paths_in_text(status_message),
            env=env,
            stream=sys.stdout,
        )
        message += f" ({rendered_status})"
    if result.save_result.ignore_warning:
        warning = render_paths_in_terminal_text(
            result.save_result.ignore_warning,
            paths=local_paths_in_text(result.save_result.ignore_warning),
            env=env,
            stream=sys.stdout,
        )
        return message + f" ({warning})"
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


def _emit_ignore_status_event(
    emit: Callable[..., None] | None,
    *,
    local_state: LocalConfigState,
    result: ConfigWizardResult,
) -> None:
    status = result.save_result.ignore_status
    if not callable(emit) or status is None:
        return
    if status.code in {"updated_existing_global_excludes", "configured_global_excludes", "already_present"}:
        event = "config.ignore.global.updated"
    elif status.code == "missing_global_excludes_configuration":
        event = "config.ignore.global.skipped"
    else:
        event = "config.ignore.global.warning"
    _emit_local_config_event(
        emit,
        event,
        local_state,
        ignore_status=status.code,
        ignore_scope=status.scope,
        ignore_target_path=str(status.target_path) if status.target_path is not None else None,
        ignore_warning=status.warning,
    )
