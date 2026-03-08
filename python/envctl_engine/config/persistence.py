from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile

from envctl_engine.config import (
    CONFIG_MANAGED_BLOCK_END,
    CONFIG_MANAGED_BLOCK_START,
    CONFIG_PRIMARY_FILENAME,
    MANAGED_CONFIG_KEYS,
    LocalConfigState,
    PortDefaults,
    StartupProfile,
    _parse_envctl_text,
)
from envctl_engine.requirements.core import dependency_definitions, managed_enable_keys
from envctl_engine.shared.parsing import parse_int


@dataclass(slots=True)
class ManagedConfigValues:
    default_mode: str
    main_profile: StartupProfile
    trees_profile: StartupProfile
    port_defaults: PortDefaults
    backend_dir_name: str = "backend"
    frontend_dir_name: str = "frontend"


@dataclass(slots=True)
class ConfigSaveResult:
    path: Path
    ignore_updated: bool
    ignore_warning: str | None


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    errors: list[str]


_BOOLEAN_KEYS = {
    "MAIN_BACKEND_ENABLE",
    "MAIN_FRONTEND_ENABLE",
    "TREES_BACKEND_ENABLE",
    "TREES_FRONTEND_ENABLE",
    *managed_enable_keys(),
}


def managed_values_from_local_state(local_state: LocalConfigState) -> ManagedConfigValues:
    return managed_values_from_mapping(local_state.parsed_values)


def managed_values_from_mapping(values: dict[str, str]) -> ManagedConfigValues:
    default_mode = str(values.get("ENVCTL_DEFAULT_MODE") or "main").strip().lower()
    if default_mode not in {"main", "trees"}:
        default_mode = "main"
    port_defaults = PortDefaults(
        backend_port_base=parse_int(values.get("BACKEND_PORT_BASE"), 8000),
        frontend_port_base=parse_int(values.get("FRONTEND_PORT_BASE"), 9000),
        dependency_ports={
            definition.id: {
                resource.name: parse_int(values.get(resource.config_port_keys[0]), _default_port_value(resource.config_port_keys[0]))
                for resource in definition.resources
            }
            for definition in dependency_definitions()
        },
        port_spacing=max(parse_int(values.get("PORT_SPACING"), 20), 1),
    )
    main_profile = StartupProfile(
        backend_enable=_parse_bool_value(values.get("MAIN_BACKEND_ENABLE"), True),
        frontend_enable=_parse_bool_value(values.get("MAIN_FRONTEND_ENABLE"), True),
        dependencies={
            definition.id: _resolve_dependency_enable(values, definition.id, mode="main")
            for definition in dependency_definitions()
        },
    )
    trees_profile = StartupProfile(
        backend_enable=_parse_bool_value(values.get("TREES_BACKEND_ENABLE"), True),
        frontend_enable=_parse_bool_value(values.get("TREES_FRONTEND_ENABLE"), True),
        dependencies={
            definition.id: _resolve_dependency_enable(values, definition.id, mode="trees")
            for definition in dependency_definitions()
        },
    )
    return ManagedConfigValues(
        default_mode=default_mode,
        backend_dir_name=str(values.get("BACKEND_DIR") or "backend").strip() or "backend",
        frontend_dir_name=str(values.get("FRONTEND_DIR") or "frontend").strip() or "frontend",
        main_profile=main_profile,
        trees_profile=trees_profile,
        port_defaults=port_defaults,
    )


def managed_values_to_mapping(values: ManagedConfigValues) -> dict[str, str]:
    rendered = {
        "ENVCTL_DEFAULT_MODE": values.default_mode,
        "BACKEND_DIR": values.backend_dir_name,
        "FRONTEND_DIR": values.frontend_dir_name,
        "BACKEND_PORT_BASE": str(values.port_defaults.backend_port_base),
        "FRONTEND_PORT_BASE": str(values.port_defaults.frontend_port_base),
        "PORT_SPACING": str(values.port_defaults.port_spacing),
        "MAIN_BACKEND_ENABLE": _bool_text(values.main_profile.backend_enable),
        "MAIN_FRONTEND_ENABLE": _bool_text(values.main_profile.frontend_enable),
        "TREES_BACKEND_ENABLE": _bool_text(values.trees_profile.backend_enable),
        "TREES_FRONTEND_ENABLE": _bool_text(values.trees_profile.frontend_enable),
    }
    for definition in dependency_definitions():
        for resource in definition.resources:
            rendered[resource.config_port_keys[0]] = str(values.port_defaults.dependency_port(definition.id, resource.name))
        rendered[definition.enable_keys_for_mode("main")[0]] = _bool_text(values.main_profile.dependency_enabled(definition.id))
        rendered[definition.enable_keys_for_mode("trees")[0]] = _bool_text(values.trees_profile.dependency_enabled(definition.id))
    return rendered


def managed_values_to_payload(values: ManagedConfigValues) -> dict[str, object]:
    return {
        "default_mode": values.default_mode,
        "directories": {
            "backend": values.backend_dir_name,
            "frontend": values.frontend_dir_name,
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
                "backend": values.main_profile.backend_enable,
                "frontend": values.main_profile.frontend_enable,
                "dependencies": {
                    definition.id: values.main_profile.dependency_enabled(definition.id)
                    for definition in dependency_definitions()
                },
            },
            "trees": {
                "backend": values.trees_profile.backend_enable,
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
            if profile.get("backend") is not None:
                mapping[f"{mode.upper()}_BACKEND_ENABLE"] = _bool_text(bool(profile["backend"]))
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


def validate_managed_values(values: ManagedConfigValues) -> ValidationResult:
    errors: list[str] = []
    if values.default_mode not in {"main", "trees"}:
        errors.append("Default mode must be main or trees.")
    if not str(values.backend_dir_name).strip():
        errors.append("Backend directory must not be empty.")
    if not str(values.frontend_dir_name).strip():
        errors.append("Frontend directory must not be empty.")
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
    lines = [CONFIG_MANAGED_BLOCK_START]
    ordered_keys = ["ENVCTL_DEFAULT_MODE", "BACKEND_DIR", "FRONTEND_DIR", "BACKEND_PORT_BASE", "FRONTEND_PORT_BASE"]
    ordered_keys.extend(key for key in MANAGED_CONFIG_KEYS if key in {"DB_PORT", "REDIS_PORT", "N8N_PORT_BASE"})
    ordered_keys.append("PORT_SPACING")
    ordered_keys.extend(["MAIN_BACKEND_ENABLE", "MAIN_FRONTEND_ENABLE"])
    ordered_keys.extend(definition.enable_keys_for_mode("main")[0] for definition in dependency_definitions())
    ordered_keys.extend(["TREES_BACKEND_ENABLE", "TREES_FRONTEND_ENABLE"])
    ordered_keys.extend(definition.enable_keys_for_mode("trees")[0] for definition in dependency_definitions())
    for index, key in enumerate(ordered_keys):
        if index in {1, 7, 13}:
            lines.append("")
        lines.append(f"{key}={rendered[key]}")
    lines.append(CONFIG_MANAGED_BLOCK_END)
    return "\n".join(lines) + "\n"


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
    validation = validate_managed_values(values)
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
    merged = merge_managed_block(existing_text, render_managed_block(values))
    _atomic_write(local_state.config_file_path, merged)
    ignore_updated, ignore_warning = ensure_local_config_ignored(local_state.base_dir)
    return ConfigSaveResult(
        path=local_state.config_file_path,
        ignore_updated=ignore_updated,
        ignore_warning=ignore_warning,
    )


def ensure_local_config_ignored(base_dir: Path) -> tuple[bool, str | None]:
    exclude_path = Path(base_dir) / ".git" / "info" / "exclude"
    try:
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
        lines = [line.strip() for line in existing.splitlines()]
        if CONFIG_PRIMARY_FILENAME in lines:
            return False, None
        updated = existing.rstrip("\n")
        if updated:
            updated += "\n"
        updated += CONFIG_PRIMARY_FILENAME + "\n"
        _atomic_write(exclude_path, updated)
        return True, None
    except OSError as exc:
        return False, f"Could not update .git/info/exclude: {exc}"


def config_review_text(*, path: Path, values: ManagedConfigValues, source_label: str, ignore_warning: str | None = None) -> str:
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
    default = definition.enabled_by_default(mode)
    for key in definition.enable_keys_for_mode(mode):
        if key in values:
            return _parse_bool_value(values.get(key), default)
    return default


def _default_port_value(key: str) -> int:
    defaults = {
        "DB_PORT": 5432,
        "REDIS_PORT": 6379,
        "N8N_PORT_BASE": 5678,
    }
    return defaults.get(key, 0)


def _validate_profile(profile: StartupProfile, *, mode: str, errors: list[str]) -> None:
    enabled = [
        profile.backend_enable,
        profile.frontend_enable,
        profile.postgres_enable,
        profile.redis_enable,
        profile.supabase_enable,
        profile.n8n_enable,
    ]
    if not any(enabled):
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
