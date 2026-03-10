from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile

from envctl_engine.config import (
    CONFIG_MANAGED_BLOCK_END,
    CONFIG_MANAGED_BLOCK_START,
    CONFIG_PRIMARY_FILENAME,
    LocalConfigState,
    PortDefaults,
    StartupProfile,
    _default_port_value,
    _parse_envctl_text,
    ensure_dependency_env_section,
)
from envctl_engine.config.profile_defaults import managed_dependency_default_enabled
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
    "MAIN_STARTUP_ENABLE",
    "MAIN_BACKEND_ENABLE",
    "MAIN_FRONTEND_ENABLE",
    "TREES_STARTUP_ENABLE",
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
        "MAIN_STARTUP_ENABLE": _bool_text(values.main_profile.startup_enable),
        "MAIN_BACKEND_ENABLE": _bool_text(values.main_profile.backend_enable),
        "MAIN_FRONTEND_ENABLE": _bool_text(values.main_profile.frontend_enable),
        "TREES_STARTUP_ENABLE": _bool_text(values.trees_profile.startup_enable),
        "TREES_BACKEND_ENABLE": _bool_text(values.trees_profile.backend_enable),
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
                "frontend": values.main_profile.frontend_enable,
                "dependencies": {
                    definition.id: values.main_profile.dependency_enabled(definition.id)
                    for definition in dependency_definitions()
                },
            },
            "trees": {
                "startup_enabled": values.trees_profile.startup_enable,
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
            if profile.get("startup_enabled") is not None:
                mapping[f"{mode.upper()}_STARTUP_ENABLE"] = _bool_text(bool(profile["startup_enabled"]))
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
    sections.append(directory_keys)

    port_keys: list[str] = []
    if _component_enabled_any(values, "backend") and rendered["BACKEND_PORT_BASE"] != defaults["BACKEND_PORT_BASE"]:
        append_once(port_keys, "BACKEND_PORT_BASE")
    if _component_enabled_any(values, "frontend") and rendered["FRONTEND_PORT_BASE"] != defaults["FRONTEND_PORT_BASE"]:
        append_once(port_keys, "FRONTEND_PORT_BASE")
    for definition in dependency_definitions():
        if not _dependency_enabled_any(values, definition.id):
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


def _dependency_enabled_any(values: ManagedConfigValues, dependency_id: str) -> bool:
    return bool(
        values.main_profile.dependency_enabled(dependency_id) or values.trees_profile.dependency_enabled(dependency_id)
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
    merged = ensure_dependency_env_section(merged)
    _atomic_write(local_state.config_file_path, merged)
    ignore_updated, ignore_warning = ensure_local_config_ignored(local_state.base_dir)
    return ConfigSaveResult(
        path=local_state.config_file_path,
        ignore_updated=ignore_updated,
        ignore_warning=ignore_warning,
    )


def ensure_local_config_ignored(base_dir: Path) -> tuple[bool, str | None]:
    warnings: list[str] = []
    gitignore_updated = False
    exclude_updated = False
    try:
        gitignore_updated = _ensure_ignore_patterns(
            Path(base_dir) / ".gitignore",
            (CONFIG_PRIMARY_FILENAME, "trees/"),
        )
    except OSError as exc:
        warnings.append(f"Could not update .gitignore: {exc}")

    exclude_path = Path(base_dir) / ".git" / "info" / "exclude"
    try:
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        exclude_updated = _ensure_ignore_patterns(exclude_path, (CONFIG_PRIMARY_FILENAME,))
    except OSError as exc:
        warnings.append(f"Could not update .git/info/exclude: {exc}")
    warning_text = "; ".join(warnings) if warnings else None
    return gitignore_updated or exclude_updated, warning_text


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
