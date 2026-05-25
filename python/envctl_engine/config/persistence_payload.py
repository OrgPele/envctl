from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from envctl_engine.config.persistence_values import (
    ManagedConfigValues,
    _bool_text,
    managed_values_from_mapping,
    managed_values_to_mapping,
)
from envctl_engine.requirements.core import dependency_definitions


@dataclass(frozen=True, slots=True)
class ConfigPayloadHydrator:
    base_values: ManagedConfigValues | None = None

    def hydrate(self, payload: dict[str, object]) -> ManagedConfigValues:
        mapping = managed_values_to_mapping(self.base_values or managed_values_from_mapping({}))
        if self._apply_flat_payload(payload, mapping):
            return managed_values_from_mapping(mapping)

        self._apply_default_mode(payload, mapping)
        self._apply_directories(payload, mapping)
        self._apply_ports(payload, mapping)
        self._apply_network(payload, mapping)
        self._apply_additional_services(payload, mapping)
        self._apply_profiles(payload, mapping)
        return managed_values_from_mapping(mapping)

    @staticmethod
    def _apply_flat_payload(payload: dict[str, object], mapping: dict[str, str]) -> bool:
        if not all(isinstance(key, str) for key in payload):
            return False
        if not any(str(key).isupper() or str(key).startswith(("MAIN_", "TREES_")) for key in payload):
            return False
        for key, value in payload.items():
            mapping[str(key)] = str(value)
        return True

    @staticmethod
    def _apply_default_mode(payload: dict[str, object], mapping: dict[str, str]) -> None:
        default_mode = payload.get("default_mode")
        if default_mode is not None:
            mapping["ENVCTL_DEFAULT_MODE"] = str(default_mode)

    @staticmethod
    def _apply_directories(payload: dict[str, object], mapping: dict[str, str]) -> None:
        directories = payload.get("directories")
        if not isinstance(directories, dict):
            return
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

    @staticmethod
    def _apply_ports(payload: dict[str, object], mapping: dict[str, str]) -> None:
        ports = payload.get("ports")
        if not isinstance(ports, dict):
            return
        if ports.get("backend") is not None:
            mapping["BACKEND_PORT_BASE"] = str(ports["backend"])
        if ports.get("frontend") is not None:
            mapping["FRONTEND_PORT_BASE"] = str(ports["frontend"])
        if ports.get("spacing") is not None:
            mapping["PORT_SPACING"] = str(ports["spacing"])
        dependencies = ports.get("dependencies")
        if not isinstance(dependencies, dict):
            return
        by_id = {definition.id: definition for definition in dependency_definitions()}
        for dependency_id, resource_values in dependencies.items():
            definition = by_id.get(str(dependency_id).strip().lower())
            if definition is None or not isinstance(resource_values, dict):
                continue
            for resource in definition.resources:
                if resource.name in resource_values:
                    mapping[resource.config_port_keys[0]] = str(resource_values[resource.name])

    @staticmethod
    def _apply_network(payload: dict[str, object], mapping: dict[str, str]) -> None:
        ui = payload.get("ui")
        if isinstance(ui, dict) and ui.get("visual_host") is not None:
            mapping["ENVCTL_UI_VISUAL_HOST"] = str(ui["visual_host"])

        network = payload.get("network")
        if isinstance(network, dict) and network.get("public_host") is not None:
            mapping["ENVCTL_PUBLIC_HOST"] = str(network["public_host"])

    @staticmethod
    def _apply_additional_services(payload: dict[str, object], mapping: dict[str, str]) -> None:
        additional_services = payload.get("additional_services")
        if not isinstance(additional_services, list):
            return
        names: list[str] = []
        for item in additional_services:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip().lower()
            if not name:
                continue
            suffix = str(item.get("env_suffix") or name.upper().replace("-", "_")).strip().upper()
            names.append(name)
            ConfigPayloadHydrator._apply_additional_service(item, mapping, suffix=suffix)
        if names:
            mapping["ENVCTL_ADDITIONAL_SERVICES"] = ",".join(names)

    @staticmethod
    def _apply_additional_service(item: dict[Any, Any], mapping: dict[str, str], *, suffix: str) -> None:
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
            mapping[f"{prefix}DEPENDS_ON"] = ",".join(str(value).strip() for value in depends_on if str(value).strip())
        elif depends_on is not None:
            mapping[f"{prefix}DEPENDS_ON"] = str(depends_on)
        if item.get("start_order") is not None:
            mapping[f"{prefix}START_ORDER"] = str(item["start_order"])
        if item.get("enable_if_path") is not None:
            mapping[f"{prefix}ENABLE_IF_PATH"] = str(item.get("enable_if_path") or "")
        if item.get("critical") is not None:
            mapping[f"{prefix}CRITICAL"] = _bool_text(bool(item["critical"]))

    @staticmethod
    def _apply_profiles(payload: dict[str, object], mapping: dict[str, str]) -> None:
        profiles = payload.get("profiles")
        if not isinstance(profiles, dict):
            return
        for mode in ("main", "trees"):
            profile = profiles.get(mode)
            if isinstance(profile, dict):
                ConfigPayloadHydrator._apply_profile(mode=mode, profile=profile, mapping=mapping)

    @staticmethod
    def _apply_profile(*, mode: str, profile: dict[Any, Any], mapping: dict[str, str]) -> None:
        if profile.get("startup_enabled") is not None:
            mapping[f"{mode.upper()}_STARTUP_ENABLE"] = _bool_text(bool(profile["startup_enabled"]))
        if profile.get("backend") is not None:
            mapping[f"{mode.upper()}_BACKEND_ENABLE"] = _bool_text(bool(profile["backend"]))
        if profile.get("backend_expect_listener") is not None:
            mapping[f"{mode.upper()}_BACKEND_EXPECT_LISTENER"] = _bool_text(bool(profile["backend_expect_listener"]))
        if profile.get("frontend") is not None:
            mapping[f"{mode.upper()}_FRONTEND_ENABLE"] = _bool_text(bool(profile["frontend"]))
        dependencies = profile.get("dependencies")
        if not isinstance(dependencies, dict):
            return
        by_id = {definition.id: definition for definition in dependency_definitions()}
        for dependency_id, enabled in dependencies.items():
            definition = by_id.get(str(dependency_id).strip().lower())
            if definition is not None:
                mapping[definition.enable_keys_for_mode(mode)[0]] = _bool_text(bool(enabled))
