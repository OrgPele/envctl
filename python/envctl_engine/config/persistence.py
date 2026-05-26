from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import tempfile

from envctl_engine.actions.actions_test import canonicalize_frontend_test_path
from envctl_engine.config import (
    AppServiceConfig,
    LocalConfigState,
    PortDefaults,
    StartupProfile,
    _parse_envctl_text,
    ensure_dependency_env_section,
)
from envctl_engine.config.agent_instructions import AgentInstructionsStatus, ensure_repo_agent_instructions
from envctl_engine.config.git_global_ignore import (
    GlobalIgnoreStatus,
    _configured_global_excludes_path,
    configure_envctl_global_ignores,
    ensure_envctl_global_ignores,
)
from envctl_engine.config.local_artifacts import envctl_local_artifact_patterns
from envctl_engine.config.persistence_rendering import config_review_text, merge_managed_block, render_managed_block
from envctl_engine.config.persistence_values import (
    ManagedConfigValues,
    ValidationResult,
    _BOOLEAN_KEYS,
    _backend_uses_port_any,
    _bool_text,
    _component_enabled_any,
    _component_runs_any,
    _dependency_enabled_any,
    _dependency_runs_any,
    _parse_bool_value,
    _resolve_dependency_enable,
    _resolved_action_test_cmd,
    _resolved_backend_dir_name,
    _resolved_backend_start_cmd,
    _resolved_backend_test_cmd,
    _resolved_frontend_dir_name,
    _resolved_frontend_start_cmd,
    _resolved_frontend_test_cmd,
    _resolved_frontend_test_path,
    _resolved_public_host,
    _resolved_ui_visual_host,
    _validate_profile,
    managed_values_from_local_state,
    managed_values_from_mapping,
    managed_values_from_payload,
    managed_values_to_mapping,
    managed_values_to_payload,
    validate_managed_values,
)

__all__ = [
    "ConfigSaveResult",
    "AppServiceConfig",
    "LocalConfigState",
    "ManagedConfigValues",
    "PortDefaults",
    "StartupProfile",
    "ValidationResult",
    "_BOOLEAN_KEYS",
    "_backend_uses_port_any",
    "_bool_text",
    "_component_enabled_any",
    "_component_runs_any",
    "_dependency_enabled_any",
    "_dependency_runs_any",
    "_parse_bool_value",
    "_resolve_dependency_enable",
    "_resolved_action_test_cmd",
    "_resolved_backend_dir_name",
    "_resolved_backend_start_cmd",
    "_resolved_backend_test_cmd",
    "_resolved_frontend_dir_name",
    "_resolved_frontend_start_cmd",
    "_resolved_frontend_test_cmd",
    "_resolved_frontend_test_path",
    "_resolved_public_host",
    "_resolved_ui_visual_host",
    "_validate_profile",
    "config_review_text",
    "ensure_global_ignore_status",
    "ensure_local_config_ignored",
    "ignore_status_summary",
    "managed_values_from_local_state",
    "managed_values_from_mapping",
    "managed_values_from_payload",
    "managed_values_to_mapping",
    "managed_values_to_payload",
    "merge_managed_block",
    "parse_env_file_text",
    "render_managed_block",
    "save_local_config",
    "save_local_config_with_ignore_policy",
    "validate_managed_values",
]


@dataclass(slots=True)
class ConfigSaveResult:
    path: Path
    ignore_updated: bool
    ignore_warning: str | None
    ignore_status: GlobalIgnoreStatus | None = None
    agent_instructions_status: AgentInstructionsStatus | None = None


def save_local_config(*, local_state: LocalConfigState, values: ManagedConfigValues) -> ConfigSaveResult:
    return save_local_config_with_ignore_policy(local_state=local_state, values=values, update_global_ignores=True)


def save_local_config_with_ignore_policy(
    *,
    local_state: LocalConfigState,
    values: ManagedConfigValues,
    update_global_ignores: bool,
) -> ConfigSaveResult:
    canonical_values = replace(
        values,
        frontend_test_path=(
            canonicalize_frontend_test_path(
                values.frontend_test_path,
                project_root=local_state.base_dir,
                frontend_dir_name=values.frontend_dir_name,
            )
            or ""
        ),
    )
    validation = validate_managed_values(canonical_values, require_directories=False, require_entrypoints=False)
    if not validation.valid:
        raise ValueError("Invalid config values: " + "; ".join(validation.errors))
    existing_text = _existing_config_text(local_state)
    merged = merge_managed_block(existing_text, render_managed_block(canonical_values))
    merged = ensure_dependency_env_section(merged)
    _atomic_write(local_state.config_file_path, merged)
    ignore_status = ensure_global_ignore_status(local_state.base_dir, update_config=update_global_ignores)
    agent_instructions_status = ensure_repo_agent_instructions(local_state.base_dir)
    return ConfigSaveResult(
        path=local_state.config_file_path,
        ignore_updated=ignore_status.updated,
        ignore_warning=ignore_status.warning,
        ignore_status=ignore_status,
        agent_instructions_status=agent_instructions_status,
    )


def _existing_config_text(local_state: LocalConfigState) -> str:
    if local_state.config_file_path.is_file():
        try:
            return local_state.config_file_path.read_text(encoding="utf-8")
        except OSError:
            return ""
    if local_state.file_text and local_state.config_source == "envctl":
        return local_state.file_text
    return ""


def ensure_global_ignore_status(base_dir: Path, *, update_config: bool = False) -> GlobalIgnoreStatus:
    if update_config:
        current_path, lookup_warning = _configured_global_excludes_path(base_dir)
        if lookup_warning is not None:
            return GlobalIgnoreStatus(
                code="global_excludes_lookup_failed",
                updated=False,
                scope="git_global_excludes",
                target_path=None,
                managed_patterns=envctl_local_artifact_patterns(),
                warning=lookup_warning,
            )
        if current_path is None:
            return configure_envctl_global_ignores(base_dir)
    return ensure_envctl_global_ignores(base_dir)


def ensure_local_config_ignored(base_dir: Path) -> tuple[bool, str | None]:
    status = ensure_global_ignore_status(base_dir)
    return status.updated, status.warning


def ignore_status_summary(status: GlobalIgnoreStatus | None) -> str | None:
    if status is None:
        return None
    target = f" at {status.target_path}" if status.target_path is not None else ""
    if status.code == "updated_existing_global_excludes":
        return f"Updated Git global excludes{target}."
    if status.code == "already_present":
        return f"Git global excludes already include envctl local artifacts{target}."
    if status.code == "configured_global_excludes":
        return f"Configured Git global excludes{target}."
    return None


def _ensure_ignore_patterns(path: Path, patterns: tuple[str, ...]) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = [line.strip() for line in existing.splitlines()]
    missing = [pattern for pattern in patterns if pattern not in lines]
    if not missing:
        return False
    updated = existing.rstrip("\n")
    if updated:
        updated += "\n"
    updated += "\n".join(missing) + "\n"
    _atomic_write(path, updated)
    return True


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        Path(temp_name).replace(path)
    finally:
        try:
            if Path(temp_name).exists():
                Path(temp_name).unlink()
        except OSError:
            pass


def parse_env_file_text(text: str) -> dict[str, str]:
    return _parse_envctl_text(text)
