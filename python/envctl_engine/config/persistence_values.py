from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from envctl_engine.actions.actions_test import (
    canonicalize_frontend_test_path,
    suggest_action_test_command,
    suggest_backend_test_command,
    suggest_frontend_test_command,
    suggest_frontend_test_path,
)
from envctl_engine.config import (
    AppServiceConfig,
    LocalConfigState,
    PortDefaults,
    StartupProfile,
    _default_port_value,
    _parse_additional_services,
)
from envctl_engine.config.profile_defaults import managed_dependency_default_enabled
from envctl_engine.requirements.core import dependency_definitions, managed_enable_keys
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
    public_host: str = "localhost"
    ui_visual_host: str = "localhost"
    additional_services: tuple[AppServiceConfig, ...] = ()


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
    additional_services, _additional_service_errors = _parse_additional_services(values)
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
        public_host=_resolved_public_host(values),
        ui_visual_host=_resolved_ui_visual_host(values),
        main_profile=main_profile,
        trees_profile=trees_profile,
        port_defaults=port_defaults,
        additional_services=additional_services,
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
        "ENVCTL_PUBLIC_HOST": values.public_host,
        "ENVCTL_UI_VISUAL_HOST": values.ui_visual_host,
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
    if values.additional_services:
        rendered["ENVCTL_ADDITIONAL_SERVICES"] = ",".join(service.name for service in values.additional_services)
    for service in values.additional_services:
        prefix = f"ENVCTL_SERVICE_{service.env_suffix}_"
        rendered[f"{prefix}DIR"] = service.dir_name
        rendered[f"{prefix}START_CMD"] = service.start_cmd
        rendered[f"{prefix}MAIN_ENABLE"] = _bool_text(service.enabled_main)
        rendered[f"{prefix}TREES_ENABLE"] = _bool_text(service.enabled_trees)
        rendered[f"{prefix}EXPECT_LISTENER"] = _bool_text(service.expect_listener)
        if service.test_cmd:
            rendered[f"{prefix}TEST_CMD"] = service.test_cmd
        if service.port_base is not None:
            rendered[f"{prefix}PORT_BASE"] = str(service.port_base)
        if service.health_url_template:
            rendered[f"{prefix}HEALTH_URL"] = service.health_url_template
        if service.public_url_template:
            rendered[f"{prefix}PUBLIC_URL"] = service.public_url_template
        if service.depends_on:
            rendered[f"{prefix}DEPENDS_ON"] = ",".join(service.depends_on)
        if service.start_order != 100:
            rendered[f"{prefix}START_ORDER"] = str(service.start_order)
        if not service.critical:
            rendered[f"{prefix}CRITICAL"] = "false"
        if service.enable_if_path:
            rendered[f"{prefix}ENABLE_IF_PATH"] = service.enable_if_path
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
        "ui": {
            "visual_host": values.ui_visual_host,
        },
        "network": {
            "public_host": values.public_host,
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
        "additional_services": [
            {
                "name": service.name,
                "env_suffix": service.env_suffix,
                "enabled_main": service.enabled_main,
                "enabled_trees": service.enabled_trees,
                "dir": service.dir_name,
                "start_cmd": service.start_cmd,
                "test_cmd": service.test_cmd,
                "port_base": service.port_base,
                "expect_listener": service.expect_listener,
                "health_url": service.health_url_template,
                "public_url": service.public_url_template,
                "depends_on": list(service.depends_on),
                "start_order": service.start_order,
                "critical": service.critical,
                "enable_if_path": service.enable_if_path,
            }
            for service in values.additional_services
        ],
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

    ui = payload.get("ui")
    if isinstance(ui, dict) and ui.get("visual_host") is not None:
        mapping["ENVCTL_UI_VISUAL_HOST"] = str(ui["visual_host"])

    network = payload.get("network")
    if isinstance(network, dict) and network.get("public_host") is not None:
        mapping["ENVCTL_PUBLIC_HOST"] = str(network["public_host"])

    additional_services = payload.get("additional_services")
    if isinstance(additional_services, list):
        names: list[str] = []
        for item in additional_services:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip().lower()
            if not name:
                continue
            suffix = str(item.get("env_suffix") or name.upper().replace("-", "_")).strip().upper()
            names.append(name)
            prefix = f"ENVCTL_SERVICE_{suffix}_"
            mapping[f"{prefix}DIR"] = str(item.get("dir") or ".")
            mapping[f"{prefix}START_CMD"] = str(item.get("start_cmd") or "")
            mapping[f"{prefix}MAIN_ENABLE"] = _bool_text(bool(item.get("enabled_main", True)))
            mapping[f"{prefix}TREES_ENABLE"] = _bool_text(bool(item.get("enabled_trees", True)))
            mapping[f"{prefix}EXPECT_LISTENER"] = _bool_text(bool(item.get("expect_listener", True)))
            if item.get("test_cmd") is not None:
                mapping[f"{prefix}TEST_CMD"] = str(item.get("test_cmd") or "")
            if item.get("port_base") is not None:
                mapping[f"{prefix}PORT_BASE"] = str(item["port_base"])
            if item.get("health_url") is not None:
                mapping[f"{prefix}HEALTH_URL"] = str(item.get("health_url") or "")
            if item.get("public_url") is not None:
                mapping[f"{prefix}PUBLIC_URL"] = str(item.get("public_url") or "")
            depends_on = item.get("depends_on")
            if isinstance(depends_on, list):
                mapping[f"{prefix}DEPENDS_ON"] = ",".join(
                    str(value).strip() for value in depends_on if str(value).strip()
                )
            elif depends_on is not None:
                mapping[f"{prefix}DEPENDS_ON"] = str(depends_on)
            if item.get("start_order") is not None:
                mapping[f"{prefix}START_ORDER"] = str(item["start_order"])
            if item.get("enable_if_path") is not None:
                mapping[f"{prefix}ENABLE_IF_PATH"] = str(item.get("enable_if_path") or "")
            if item.get("critical") is not None:
                mapping[f"{prefix}CRITICAL"] = _bool_text(bool(item["critical"]))
        if names:
            mapping["ENVCTL_ADDITIONAL_SERVICES"] = ",".join(names)

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
    _services_from_rendered, additional_service_errors = _parse_additional_services(managed_values_to_mapping(values))
    errors.extend(additional_service_errors)
    for service in values.additional_services:
        if (service.enabled_main or service.enabled_trees) and not str(service.start_cmd).strip():
            errors.append(f"Additional service {service.name} entrypoint must not be empty.")
        if service.expect_listener and service.port_base is None:
            errors.append(f"Additional service {service.name} port base must not be empty when listener expected.")
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


def _resolved_ui_visual_host(values: dict[str, str]) -> str:
    host = str(values.get("ENVCTL_UI_VISUAL_HOST") or "").strip()
    if host:
        return host
    return _resolved_public_host(values)


def _resolved_public_host(values: dict[str, str]) -> str:
    host = str(values.get("ENVCTL_PUBLIC_HOST") or "").strip()
    return host or "localhost"


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
