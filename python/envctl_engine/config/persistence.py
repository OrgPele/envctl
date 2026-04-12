from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile

from envctl_engine.config import (
    CONFIG_MANAGED_BLOCK_END,
    CONFIG_MANAGED_BLOCK_START,
    LocalConfigState,
    PortDefaults,
    StartupProfile,
    _default_port_value,
    _parse_envctl_text,
    ensure_dependency_env_section,
)
from envctl_engine.config.git_global_ignore import (
    GlobalIgnoreStatus,
    _configured_global_excludes_path,
    ensure_envctl_global_ignores,
)
from envctl_engine.config.local_artifacts import envctl_local_artifact_patterns
from envctl_engine.config.profile_defaults import managed_dependency_default_enabled
from envctl_engine.requirements.core import dependency_definitions, managed_enable_keys
from envctl_engine.actions.actions_test import (
    canonicalize_frontend_test_path,
    suggest_action_test_command,
    suggest_backend_test_command,
    suggest_frontend_test_command,
    suggest_frontend_test_path,
)
from envctl_engine.runtime.command_resolution import suggest_service_directory, suggest_service_start_command
from envctl_engine.shared.parsing import parse_int


@dataclass(slots=True)
class ManagedConfigValues:
    default_mode: str
    main_profile: StartupProfile
    trees_profile: StartupProfile
    port_defaults: PortDefaults
    main_backend_expect_listener: bool = True
    trees_backend_expect_listener: bool = True
    backend_dir_name: str = "backend"
    frontend_dir_name: str = "frontend"
    backend_start_cmd: str = ""
    frontend_start_cmd: str = ""
    backend_test_cmd: str = ""
    frontend_test_cmd: str = ""
    action_test_cmd: str = ""
    frontend_test_path: str = ""


@dataclass(slots=True)
class ConfigSaveResult:
    path: Path
    ignore_updated: bool
    ignore_warning: str | None
    ignore_status: GlobalIgnoreStatus | None = None


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    errors: list[str]


_BOOLEAN_KEYS = {
    "MAIN_STARTUP_ENABLE",
    "MAIN_BACKEND_ENABLE",
    "MAIN_BACKEND_EXPECT_LISTENER",
    "MAIN_FRONTEND_ENABLE",
    "TREES_STARTUP_ENABLE",
    "TREES_BACKEND_ENABLE",
    "TREES_BACKEND_EXPECT_LISTENER",
    "TREES_FRONTEND_ENABLE",
    *managed_enable_keys(),
}


def managed_values_from_local_state(local_state: LocalConfigState) -> ManagedConfigValues:
    return managed_values_from_mapping(local_state.parsed_values, base_dir=local_state.base_dir)


def managed_values_from_mapping(values: dict[str, str], *, base_dir: Path | None = None) -> ManagedConfigValues:
    default_mode = str(values.get("ENVCTL_DEFAULT_MODE") or "main").strip().lower()
    if default_mode not in {"main", "trees"}:
        default_mode = "main"
    port_defaults = PortDefaults(
        backend_port_base=parse_int(values.get("BACKEND_PORT_BASE"), 8000),
        frontend_port_base=parse_int(values.get("FRONTEND_PORT_BASE"), 9000),
        dependency_ports={
            definition.id: {
                resource.name: parse_int(
                    values.get(resource.config_port_keys[0]), _default_port_value(resource.config_port_keys[0])
                )
                for resource in definition.resources
            }
            for definition in dependency_definitions()
        },
        port_spacing=max(parse_int(values.get("PORT_SPACING"), 20), 1),
    )
    main_profile = StartupProfile(
        startup_enable=_parse_bool_value(values.get("MAIN_STARTUP_ENABLE"), True),
        backend_enable=_parse_bool_value(values.get("MAIN_BACKEND_ENABLE"), True),
        frontend_enable=_parse_bool_value(values.get("MAIN_FRONTEND_ENABLE"), True),
        dependencies={
            definition.id: _resolve_dependency_enable(values, definition.id, mode="main")
            for definition in dependency_definitions()
        },
    )
    trees_profile = StartupProfile(
        startup_enable=_parse_bool_value(values.get("TREES_STARTUP_ENABLE"), True),
        backend_enable=_parse_bool_value(values.get("TREES_BACKEND_ENABLE"), True),
        frontend_enable=_parse_bool_value(values.get("TREES_FRONTEND_ENABLE"), True),
        dependencies={
            definition.id: _resolve_dependency_enable(values, definition.id, mode="trees")
            for definition in dependency_definitions()
        },
    )
    return ManagedConfigValues(
        default_mode=default_mode,
        main_backend_expect_listener=_parse_bool_value(values.get("MAIN_BACKEND_EXPECT_LISTENER"), True),
        trees_backend_expect_listener=_parse_bool_value(values.get("TREES_BACKEND_EXPECT_LISTENER"), True),
        backend_dir_name=_resolved_backend_dir_name(values=values, base_dir=base_dir),
        frontend_dir_name=_resolved_frontend_dir_name(values=values, base_dir=base_dir),
        backend_start_cmd=_resolved_backend_start_cmd(values=values, base_dir=base_dir),
        frontend_start_cmd=_resolved_frontend_start_cmd(values=values, base_dir=base_dir),
        backend_test_cmd=_resolved_backend_test_cmd(values=values, base_dir=base_dir),
        frontend_test_cmd=_resolved_frontend_test_cmd(values=values, base_dir=base_dir),
        action_test_cmd=_resolved_action_test_cmd(values=values, base_dir=base_dir),
        frontend_test_path=_resolved_frontend_test_path(values=values, base_dir=base_dir),
        main_profile=main_profile,
        trees_profile=trees_profile,
        port_defaults=port_defaults,
    )


def managed_values_to_mapping(values: ManagedConfigValues) -> dict[str, str]:
    rendered = {
        "ENVCTL_DEFAULT_MODE": values.default_mode,
        "BACKEND_DIR": values.backend_dir_name,
        "FRONTEND_DIR": values.frontend_dir_name,
        "ENVCTL_BACKEND_START_CMD": values.backend_start_cmd,
        "ENVCTL_FRONTEND_START_CMD": values.frontend_start_cmd,
        "ENVCTL_BACKEND_TEST_CMD": values.backend_test_cmd,
        "ENVCTL_FRONTEND_TEST_CMD": values.frontend_test_cmd,
        "ENVCTL_FRONTEND_TEST_PATH": values.frontend_test_path,
        "BACKEND_PORT_BASE": str(values.port_defaults.backend_port_base),
        "FRONTEND_PORT_BASE": str(values.port_defaults.frontend_port_base),
        "PORT_SPACING": str(values.port_defaults.port_spacing),
        "MAIN_STARTUP_ENABLE": _bool_text(values.main_profile.startup_enable),
        "MAIN_BACKEND_ENABLE": _bool_text(values.main_profile.backend_enable),
        "MAIN_BACKEND_EXPECT_LISTENER": _bool_text(values.main_backend_expect_listener),
        "MAIN_FRONTEND_ENABLE": _bool_text(values.main_profile.frontend_enable),
        "TREES_STARTUP_ENABLE": _bool_text(values.trees_profile.startup_enable),
        "TREES_BACKEND_ENABLE": _bool_text(values.trees_profile.backend_enable),
        "TREES_BACKEND_EXPECT_LISTENER": _bool_text(values.trees_backend_expect_listener),
        "TREES_FRONTEND_ENABLE": _bool_text(values.trees_profile.frontend_enable),
    }
    for definition in dependency_definitions():
        for resource in definition.resources:
            rendered[resource.config_port_keys[0]] = str(
                values.port_defaults.dependency_port(definition.id, resource.name)
            )
        rendered[definition.enable_keys_for_mode("main")[0]] = _bool_text(
            values.main_profile.dependency_enabled(definition.id)
        )
        rendered[definition.enable_keys_for_mode("trees")[0]] = _bool_text(
            values.trees_profile.dependency_enabled(definition.id)
        )
    return rendered


def managed_values_to_payload(values: ManagedConfigValues) -> dict[str, object]:
    return {
        "default_mode": values.default_mode,
        "directories": {
            "backend": values.backend_dir_name,
            "frontend": values.frontend_dir_name,
            "backend_entrypoint": values.backend_start_cmd,
            "frontend_entrypoint": values.frontend_start_cmd,
            "backend_test_command": values.backend_test_cmd,
            "frontend_test_command": values.frontend_test_cmd,
            "test_command": values.action_test_cmd,
            "frontend_test_path": values.frontend_test_path,
        },
        "ports": {
            "backend": values.port_defaults.backend_port_base,
            "frontend": values.port_defaults.frontend_port_base,
            "spacing": values.port_defaults.port_spacing,
            "dependencies": {
                definition.id: {
                    resource.name: values.port_defaults.dependency_port(definition.id, resource.name)
                    for resource in definition.resources
                }
                for definition in dependency_definitions()
            },
        },
        "profiles": {
            "main": {
                "startup_enabled": values.main_profile.startup_enable,
                "backend": values.main_profile.backend_enable,
                "backend_expect_listener": values.main_backend_expect_listener,
                "frontend": values.main_profile.frontend_enable,
                "dependencies": {
                    definition.id: values.main_profile.dependency_enabled(definition.id)
                    for definition in dependency_definitions()
                },
            },
            "trees": {
                "startup_enabled": values.trees_profile.startup_enable,
                "backend": values.trees_profile.backend_enable,
                "backend_expect_listener": values.trees_backend_expect_listener,
                "frontend": values.trees_profile.frontend_enable,
                "dependencies": {
                    definition.id: values.trees_profile.dependency_enabled(definition.id)
                    for definition in dependency_definitions()
                },
            },
        },
        "managed_keys": managed_values_to_mapping(values),
    }


def managed_values_from_payload(
    payload: dict[str, object],
    *,
    base_values: ManagedConfigValues | None = None,
) -> ManagedConfigValues:
    mapping = managed_values_to_mapping(base_values or managed_values_from_mapping({}))
    if all(isinstance(key, str) for key in payload):
        if any(str(key).isupper() or str(key).startswith("MAIN_") or str(key).startswith("TREES_") for key in payload):
            for key, value in payload.items():
                mapping[str(key)] = str(value)
            return managed_values_from_mapping(mapping)

    default_mode = payload.get("default_mode")
    if default_mode is not None:
        mapping["ENVCTL_DEFAULT_MODE"] = str(default_mode)

    directories = payload.get("directories")
    if isinstance(directories, dict):
        if directories.get("backend") is not None:
            mapping["BACKEND_DIR"] = str(directories["backend"])
        if directories.get("frontend") is not None:
            mapping["FRONTEND_DIR"] = str(directories["frontend"])
        if directories.get("entrypoint") is not None:
            mapping["ENVCTL_BACKEND_START_CMD"] = str(directories["entrypoint"])
        if directories.get("backend_entrypoint") is not None:
            mapping["ENVCTL_BACKEND_START_CMD"] = str(directories["backend_entrypoint"])
        if directories.get("frontend_entrypoint") is not None:
            mapping["ENVCTL_FRONTEND_START_CMD"] = str(directories["frontend_entrypoint"])
        if directories.get("backend_test_command") is not None:
            mapping["ENVCTL_BACKEND_TEST_CMD"] = str(directories["backend_test_command"])
        if directories.get("frontend_test_command") is not None:
            mapping["ENVCTL_FRONTEND_TEST_CMD"] = str(directories["frontend_test_command"])
        if directories.get("test_command") is not None:
            value = str(directories["test_command"])
            mapping["ENVCTL_BACKEND_TEST_CMD"] = value
            mapping["ENVCTL_FRONTEND_TEST_CMD"] = value
            mapping["ENVCTL_ACTION_TEST_CMD"] = value
        if directories.get("frontend_test_path") is not None:
            mapping["ENVCTL_FRONTEND_TEST_PATH"] = str(directories["frontend_test_path"])

    ports = payload.get("ports")
    if isinstance(ports, dict):
        if ports.get("backend") is not None:
            mapping["BACKEND_PORT_BASE"] = str(ports["backend"])
        if ports.get("frontend") is not None:
            mapping["FRONTEND_PORT_BASE"] = str(ports["frontend"])
        if ports.get("spacing") is not None:
            mapping["PORT_SPACING"] = str(ports["spacing"])
        dependencies = ports.get("dependencies")
        if isinstance(dependencies, dict):
            by_id = {definition.id: definition for definition in dependency_definitions()}
            for dependency_id, resource_values in dependencies.items():
                definition = by_id.get(str(dependency_id).strip().lower())
                if definition is None or not isinstance(resource_values, dict):
                    continue
                for resource in definition.resources:
                    if resource.name in resource_values:
                        mapping[resource.config_port_keys[0]] = str(resource_values[resource.name])

    profiles = payload.get("profiles")
    if isinstance(profiles, dict):
        for mode in ("main", "trees"):
            profile = profiles.get(mode)
            if not isinstance(profile, dict):
                continue
            if profile.get("startup_enabled") is not None:
                mapping[f"{mode.upper()}_STARTUP_ENABLE"] = _bool_text(bool(profile["startup_enabled"]))
            if profile.get("backend") is not None:
                mapping[f"{mode.upper()}_BACKEND_ENABLE"] = _bool_text(bool(profile["backend"]))
            if profile.get("backend_expect_listener") is not None:
                mapping[f"{mode.upper()}_BACKEND_EXPECT_LISTENER"] = _bool_text(
                    bool(profile["backend_expect_listener"])
                )
            if profile.get("frontend") is not None:
                mapping[f"{mode.upper()}_FRONTEND_ENABLE"] = _bool_text(bool(profile["frontend"]))
            dependencies = profile.get("dependencies")
            if isinstance(dependencies, dict):
                by_id = {definition.id: definition for definition in dependency_definitions()}
                for dependency_id, enabled in dependencies.items():
                    definition = by_id.get(str(dependency_id).strip().lower())
                    if definition is None:
                        continue
                    mapping[definition.enable_keys_for_mode(mode)[0]] = _bool_text(bool(enabled))

    return managed_values_from_mapping(mapping)


def validate_managed_values(
    values: ManagedConfigValues,
    *,
    require_directories: bool = True,
    require_entrypoints: bool = True,
) -> ValidationResult:
    errors: list[str] = []
    if values.default_mode not in {"main", "trees"}:
        errors.append("Default mode must be main or trees.")
    if require_directories and _component_enabled_any(values, "backend") and not str(values.backend_dir_name).strip():
        errors.append("Backend directory must not be empty.")
    if require_directories and _component_enabled_any(values, "frontend") and not str(values.frontend_dir_name).strip():
        errors.append("Frontend directory must not be empty.")
    if require_entrypoints and _component_runs_any(values, "backend") and not str(values.backend_start_cmd).strip():
        errors.append("Backend entrypoint must not be empty.")
    if require_entrypoints and _component_runs_any(values, "frontend") and not str(values.frontend_start_cmd).strip():
        errors.append("Frontend entrypoint must not be empty.")
    _validate_profile(values.main_profile, mode="main", errors=errors)
    _validate_profile(values.trees_profile, mode="trees", errors=errors)
    ports = values.port_defaults
    for label, raw in (
        ("Backend port base", ports.backend_port_base),
        ("Frontend port base", ports.frontend_port_base),
        ("DB port base", ports.db_port_base),
        ("Redis port base", ports.redis_port_base),
        ("n8n port base", ports.n8n_port_base),
        ("Port spacing", ports.port_spacing),
    ):
        if int(raw) < 1:
            errors.append(f"{label} must be a positive integer.")
    return ValidationResult(valid=not errors, errors=errors)


def render_managed_block(values: ManagedConfigValues) -> str:
    rendered = managed_values_to_mapping(values)
    defaults = managed_values_to_mapping(managed_values_from_mapping({}))
    lines = [CONFIG_MANAGED_BLOCK_START]
    section_groups = _managed_block_sections(values=values, rendered=rendered, defaults=defaults)
    wrote_any = False
    for section in section_groups:
        if not section:
            continue
        if wrote_any:
            lines.append("")
        for key in section:
            lines.append(f"{key}={rendered[key]}")
        wrote_any = True
    lines.append(CONFIG_MANAGED_BLOCK_END)
    return "\n".join(lines) + "\n"


def _managed_block_sections(
    *,
    values: ManagedConfigValues,
    rendered: dict[str, str],
    defaults: dict[str, str],
) -> list[list[str]]:
    def append_once(keys: list[str], key: str) -> None:
        if key not in keys:
            keys.append(key)

    sections: list[list[str]] = []
    sections.append(["ENVCTL_DEFAULT_MODE"])

    directory_keys: list[str] = []
    if _component_enabled_any(values, "backend") and rendered["BACKEND_DIR"] != defaults["BACKEND_DIR"]:
        append_once(directory_keys, "BACKEND_DIR")
    if _component_enabled_any(values, "frontend") and rendered["FRONTEND_DIR"] != defaults["FRONTEND_DIR"]:
        append_once(directory_keys, "FRONTEND_DIR")
    if (
        _component_runs_any(values, "backend")
        and rendered["ENVCTL_BACKEND_START_CMD"] != defaults["ENVCTL_BACKEND_START_CMD"]
    ):
        append_once(directory_keys, "ENVCTL_BACKEND_START_CMD")
    if (
        _component_runs_any(values, "frontend")
        and rendered["ENVCTL_FRONTEND_START_CMD"] != defaults["ENVCTL_FRONTEND_START_CMD"]
    ):
        append_once(directory_keys, "ENVCTL_FRONTEND_START_CMD")
    if (
        _component_enabled_any(values, "backend")
        and rendered["ENVCTL_BACKEND_TEST_CMD"] != defaults["ENVCTL_BACKEND_TEST_CMD"]
    ):
        append_once(directory_keys, "ENVCTL_BACKEND_TEST_CMD")
    if (
        _component_enabled_any(values, "frontend")
        and rendered["ENVCTL_FRONTEND_TEST_CMD"] != defaults["ENVCTL_FRONTEND_TEST_CMD"]
    ):
        append_once(directory_keys, "ENVCTL_FRONTEND_TEST_CMD")
    if (
        _component_enabled_any(values, "frontend")
        and rendered["ENVCTL_FRONTEND_TEST_PATH"] != defaults["ENVCTL_FRONTEND_TEST_PATH"]
    ):
        append_once(directory_keys, "ENVCTL_FRONTEND_TEST_PATH")
    sections.append(directory_keys)

    port_keys: list[str] = []
    if _backend_uses_port_any(values) and rendered["BACKEND_PORT_BASE"] != defaults["BACKEND_PORT_BASE"]:
        append_once(port_keys, "BACKEND_PORT_BASE")
    if _frontend_uses_port_any(values) and rendered["FRONTEND_PORT_BASE"] != defaults["FRONTEND_PORT_BASE"]:
        append_once(port_keys, "FRONTEND_PORT_BASE")
    for definition in dependency_definitions():
        if not _dependency_runs_any(values, definition.id):
            continue
        for resource in definition.resources:
            key = resource.config_port_keys[0]
            if rendered[key] != defaults[key]:
                append_once(port_keys, key)
    if port_keys and rendered["PORT_SPACING"] != defaults["PORT_SPACING"]:
        append_once(port_keys, "PORT_SPACING")
    sections.append(port_keys)

    main_keys = _profile_keys_for_mode(mode="main", values=values, rendered=rendered, defaults=defaults)
    trees_keys = _profile_keys_for_mode(mode="trees", values=values, rendered=rendered, defaults=defaults)
    sections.append(main_keys)
    sections.append(trees_keys)
    return sections


def _profile_keys_for_mode(
    *,
    mode: str,
    values: ManagedConfigValues,
    rendered: dict[str, str],
    defaults: dict[str, str],
) -> list[str]:
    prefix = mode.upper()
    keys: list[str] = []
    for key in (
        f"{prefix}_STARTUP_ENABLE",
        f"{prefix}_BACKEND_ENABLE",
        f"{prefix}_BACKEND_EXPECT_LISTENER",
        f"{prefix}_FRONTEND_ENABLE",
    ):
        if rendered[key] != defaults[key]:
            keys.append(key)
    for definition in dependency_definitions():
        key = definition.enable_keys_for_mode(mode)[0]
        if rendered[key] != defaults[key]:
            keys.append(key)
    return keys


def _component_enabled_any(values: ManagedConfigValues, component: str) -> bool:
    if component == "backend":
        return bool(values.main_profile.backend_enable or values.trees_profile.backend_enable)
    if component == "frontend":
        return bool(values.main_profile.frontend_enable or values.trees_profile.frontend_enable)
    return False


def _component_runs_any(values: ManagedConfigValues, component: str) -> bool:
    if component == "backend":
        return bool(
            (values.main_profile.startup_enable and values.main_profile.backend_enable)
            or (values.trees_profile.startup_enable and values.trees_profile.backend_enable)
        )
    if component == "frontend":
        return bool(
            (values.main_profile.startup_enable and values.main_profile.frontend_enable)
            or (values.trees_profile.startup_enable and values.trees_profile.frontend_enable)
        )
    return False


def _dependency_enabled_any(values: ManagedConfigValues, dependency_id: str) -> bool:
    return bool(
        values.main_profile.dependency_enabled(dependency_id) or values.trees_profile.dependency_enabled(dependency_id)
    )


def _backend_uses_port_any(values: ManagedConfigValues) -> bool:
    return bool(
        (
            values.main_profile.startup_enable
            and values.main_profile.backend_enable
            and values.main_backend_expect_listener
        )
        or (
            values.trees_profile.startup_enable
            and values.trees_profile.backend_enable
            and values.trees_backend_expect_listener
        )
    )


def _frontend_uses_port_any(values: ManagedConfigValues) -> bool:
    return _component_runs_any(values, "frontend")


def _dependency_runs_any(values: ManagedConfigValues, dependency_id: str) -> bool:
    return bool(
        (values.main_profile.startup_enable and values.main_profile.dependency_enabled(dependency_id))
        or (values.trees_profile.startup_enable and values.trees_profile.dependency_enabled(dependency_id))
    )


def merge_managed_block(existing_text: str, block_text: str) -> str:
    text = existing_text or ""
    start = text.find(CONFIG_MANAGED_BLOCK_START)
    end = text.find(CONFIG_MANAGED_BLOCK_END)
    if start != -1 and end != -1 and end >= start:
        end += len(CONFIG_MANAGED_BLOCK_END)
        suffix = text[end:]
        if suffix.startswith("\n"):
            suffix = suffix[1:]
        prefix = text[:start].rstrip("\n")
        parts = [part for part in (prefix, block_text.rstrip("\n"), suffix.rstrip("\n")) if part]
        return "\n\n".join(parts) + "\n"
    stripped = text.rstrip("\n")
    if not stripped:
        return block_text
    return stripped + "\n\n" + block_text


def save_local_config(*, local_state: LocalConfigState, values: ManagedConfigValues) -> ConfigSaveResult:
    return save_local_config_with_ignore_policy(local_state=local_state, values=values, update_global_ignores=False)


def save_local_config_with_ignore_policy(
    *,
    local_state: LocalConfigState,
    values: ManagedConfigValues,
    update_global_ignores: bool,
) -> ConfigSaveResult:
    canonical_values = ManagedConfigValues(
        default_mode=values.default_mode,
        main_profile=values.main_profile,
        trees_profile=values.trees_profile,
        main_backend_expect_listener=values.main_backend_expect_listener,
        trees_backend_expect_listener=values.trees_backend_expect_listener,
        port_defaults=values.port_defaults,
        backend_dir_name=values.backend_dir_name,
        frontend_dir_name=values.frontend_dir_name,
        backend_start_cmd=values.backend_start_cmd,
        frontend_start_cmd=values.frontend_start_cmd,
        backend_test_cmd=values.backend_test_cmd,
        frontend_test_cmd=values.frontend_test_cmd,
        action_test_cmd=values.action_test_cmd,
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
    existing_text = ""
    if local_state.config_file_path.is_file():
        try:
            existing_text = local_state.config_file_path.read_text(encoding="utf-8")
        except OSError:
            existing_text = ""
    elif local_state.file_text and local_state.config_source == "envctl":
        existing_text = local_state.file_text
    merged = merge_managed_block(existing_text, render_managed_block(canonical_values))
    merged = ensure_dependency_env_section(merged)
    _atomic_write(local_state.config_file_path, merged)
    ignore_status = ensure_global_ignore_status(local_state.base_dir, update_config=update_global_ignores)
    return ConfigSaveResult(
        path=local_state.config_file_path,
        ignore_updated=ignore_status.updated,
        ignore_warning=ignore_status.warning,
        ignore_status=ignore_status,
    )


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
            return ensure_envctl_global_ignores(base_dir)
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


def config_review_text(
    *, path: Path, values: ManagedConfigValues, source_label: str, ignore_warning: str | None = None
) -> str:
    summary = [
        f"Path: {path}",
        f"Source: {source_label}",
        "CLI/env overrides still apply above this file.",
        "",
        render_managed_block(values).rstrip("\n"),
    ]
    if ignore_warning:
        summary.extend(["", f"Ignore warning: {ignore_warning}"])
    return "\n".join(summary)


def _resolve_dependency_enable(values: dict[str, str], dependency_id: str, *, mode: str) -> bool:
    definition = next(defn for defn in dependency_definitions() if defn.id == dependency_id)
    default = managed_dependency_default_enabled(dependency_id, mode)
    for key in definition.enable_keys_for_mode(mode):
        if key in values:
            return _parse_bool_value(values.get(key), default)
    return default


def _validate_profile(profile: StartupProfile, *, mode: str, errors: list[str]) -> None:
    enabled = [
        profile.backend_enable,
        profile.frontend_enable,
        profile.postgres_enable,
        profile.redis_enable,
        profile.supabase_enable,
        profile.n8n_enable,
    ]
    if profile.startup_enable and not any(enabled):
        errors.append(f"{mode} must enable at least one component.")
    if profile.postgres_enable and profile.supabase_enable:
        errors.append(f"{mode} cannot enable both postgres and supabase.")


def _parse_bool_value(raw: str | None, default: bool) -> bool:
    if raw is None:
        return default
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _resolved_backend_start_cmd(*, values: dict[str, str], base_dir: Path | None) -> str:
    raw = str(values.get("ENVCTL_BACKEND_START_CMD") or "").strip()
    if raw:
        return raw
    if base_dir is None:
        return ""
    suggested = suggest_service_start_command(service_name="backend", project_root=base_dir)
    return str(suggested or "").strip()


def _resolved_backend_dir_name(*, values: dict[str, str], base_dir: Path | None) -> str:
    if "BACKEND_DIR" in values:
        return str(values.get("BACKEND_DIR") or "").strip()
    if base_dir is None:
        return "backend"
    suggested = suggest_service_directory(service_name="backend", project_root=base_dir)
    return str(suggested or "").strip()


def _resolved_frontend_start_cmd(*, values: dict[str, str], base_dir: Path | None) -> str:
    raw = str(values.get("ENVCTL_FRONTEND_START_CMD") or "").strip()
    if raw:
        return raw
    if base_dir is None:
        return ""
    suggested = suggest_service_start_command(service_name="frontend", project_root=base_dir)
    return str(suggested or "").strip()


def _resolved_action_test_cmd(*, values: dict[str, str], base_dir: Path | None) -> str:
    raw = str(values.get("ENVCTL_ACTION_TEST_CMD") or "").strip()
    if raw:
        return raw
    if base_dir is None:
        return ""
    suggested = suggest_action_test_command(base_dir)
    return str(suggested or "").strip()


def _resolved_backend_test_cmd(*, values: dict[str, str], base_dir: Path | None) -> str:
    raw = str(values.get("ENVCTL_BACKEND_TEST_CMD") or "").strip()
    if raw:
        return raw
    shared = str(values.get("ENVCTL_ACTION_TEST_CMD") or "").strip()
    if shared:
        return shared
    if base_dir is None:
        return ""
    suggested = suggest_backend_test_command(base_dir)
    return str(suggested or "").strip()


def _resolved_frontend_test_cmd(*, values: dict[str, str], base_dir: Path | None) -> str:
    raw = str(values.get("ENVCTL_FRONTEND_TEST_CMD") or "").strip()
    if raw:
        return raw
    shared = str(values.get("ENVCTL_ACTION_TEST_CMD") or "").strip()
    if shared:
        return shared
    if base_dir is None:
        return ""
    suggested = suggest_frontend_test_command(base_dir)
    return str(suggested or "").strip()


def _resolved_frontend_test_path(*, values: dict[str, str], base_dir: Path | None) -> str:
    raw = str(values.get("ENVCTL_FRONTEND_TEST_PATH") or "").strip()
    if raw:
        if base_dir is None:
            return raw
        return str(
            canonicalize_frontend_test_path(
                raw,
                project_root=base_dir,
                frontend_dir_name=str(values.get("FRONTEND_DIR") or "").strip(),
            )
            or raw
        ).strip()
    if base_dir is None:
        return ""
    suggested = suggest_frontend_test_path(base_dir)
    return str(suggested or "").strip()


def _resolved_frontend_dir_name(*, values: dict[str, str], base_dir: Path | None) -> str:
    if "FRONTEND_DIR" in values:
        return str(values.get("FRONTEND_DIR") or "").strip()
    if base_dir is None:
        return "frontend"
    suggested = suggest_service_directory(service_name="frontend", project_root=base_dir)
    return str(suggested or "").strip()


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
