from __future__ import annotations

from typing import Any

from envctl_engine.requirements.external_env import ExternalDependencyEnvResolver
from envctl_engine.requirements.external_env import normalize_dependency_id
from envctl_engine.requirements.external_env import parse_dependency_list
from envctl_engine.shared.parsing import parse_bool


MODE_EXTERNAL_VALUES = {"external", "externally-managed", "remote", "native-external"}


class ExternalDependencyModePolicy:
    """Decides whether a dependency should be treated as externally managed."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self._env = ExternalDependencyEnvResolver(runtime)

    def external_mode(self, dependency_id: str, *, mode: str | None = None, route: Any = None) -> bool:
        dependency = normalize_dependency_id(dependency_id)
        if not dependency:
            return False
        if self._route_forces_managed_dependencies(route):
            return False
        global_mode = self._env.raw("ENVCTL_EXTERNAL_DEPENDENCIES_MODE") or self._env.raw("ENVCTL_DEPENDENCIES_MODE")
        if global_mode is not None and str(global_mode).strip().lower() == "managed":
            return False
        explicit_mode = self._env.raw(f"ENVCTL_DEPENDENCY_{dependency.upper()}_MODE")
        if explicit_mode is None:
            explicit_mode = self._env.raw(f"ENVCTL_{dependency.upper()}_MODE")
        if explicit_mode is not None:
            return str(explicit_mode).strip().lower() in MODE_EXTERNAL_VALUES
        explicit_bool = self._env.raw(f"ENVCTL_{dependency.upper()}_EXTERNAL")
        if explicit_bool is not None:
            return parse_bool(explicit_bool, False)
        external_list = self._env.raw("ENVCTL_EXTERNAL_DEPENDENCIES")
        if dependency in parse_dependency_list(external_list):
            return True
        if self._dependency_configured_for_managed_mode(dependency, mode=mode):
            return False
        return self._dependency_auto_external_mode(dependency, mode=mode)

    def _dependency_auto_external_mode(self, dependency_id: str, *, mode: str | None) -> bool:
        if str(mode or "").strip().lower() != "main":
            return False
        return self._env.validation_error(dependency_id) is None

    def _dependency_configured_for_managed_mode(self, dependency_id: str, *, mode: str | None) -> bool:
        if str(mode or "").strip().lower() != "main":
            return False
        if parse_bool(self._env.raw_without_app_env("SKIP_LOCAL_DB_ENV"), False):
            return False
        config = getattr(self.runtime, "config", None)
        enabled_for_mode = getattr(config, "requirement_enabled_for_mode", None)
        if callable(enabled_for_mode):
            try:
                return bool(enabled_for_mode("main", dependency_id))
            except Exception:  # noqa: BLE001
                return False
        attr_name = {
            "postgres": "postgres_main_enable",
            "redis": "redis_main_enable",
            "supabase": "supabase_main_enable",
            "n8n": "n8n_main_enable",
        }.get(dependency_id)
        if not attr_name:
            return False
        raw = getattr(config, attr_name, None)
        return bool(raw)

    @staticmethod
    def _route_forces_managed_dependencies(route: Any) -> bool:
        flags = getattr(route, "flags", None)
        if not isinstance(flags, dict):
            return False
        return str(flags.get("external_dependencies_mode") or "").strip().lower() == "managed"


def dependency_external_mode(runtime: Any, dependency_id: str, *, mode: str | None = None, route: Any = None) -> bool:
    return ExternalDependencyModePolicy(runtime).external_mode(dependency_id, mode=mode, route=route)


__all__ = [
    "MODE_EXTERNAL_VALUES",
    "ExternalDependencyModePolicy",
    "dependency_external_mode",
]
