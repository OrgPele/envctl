from __future__ import annotations

from pathlib import Path

from envctl_engine.runtime.command_resolution import CommandResolutionError
from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.protocols import ProjectContextLike


def _raw_config_value(config: object, key: str) -> str:
    raw = getattr(config, "raw", {})
    if isinstance(raw, dict):
        return str(raw.get(key, "") or "").strip()
    return ""


def _raw_setting_value(config: object, env: dict[str, str] | object, key: str) -> str:
    normalized = key.strip().upper()
    if isinstance(env, dict):
        for env_key, value in env.items():
            if str(env_key).strip().upper() == normalized:
                return str(value or "").strip()
    return _raw_config_value(config, key)


def _explicit_config_key(config: object, env: dict[str, str] | object, key: str) -> bool:
    normalized = key.strip().upper()
    explicit_keys = {str(item).strip().upper() for item in getattr(config, "explicit_keys", ())}
    if normalized in explicit_keys:
        return True
    if isinstance(env, dict) and normalized in {str(item).strip().upper() for item in env}:
        return True
    return False


def _explicit_dependency_env_section(config: object, *, mode: str, service_name: str) -> bool:
    normalized_mode = "main" if mode == "main" else "trees"
    service = service_name.strip().lower()
    return any(
        bool(getattr(config, attr, False))
        for attr in (
            "dependency_env_section_present",
            f"{service}_dependency_env_section_present",
            f"{normalized_mode}_{service}_dependency_env_section_present",
        )
    )


def _config_file_belongs_to_context(config: object, context: ProjectContextLike) -> bool:
    if not bool(getattr(config, "config_file_exists", False)):
        return True
    config_path = getattr(config, "config_file_path", None)
    if not config_path:
        return False
    try:
        Path(config_path).resolve().relative_to(context.root.resolve())
    except ValueError:
        return False
    return True


def _context_config_key(
    config: object,
    env: dict[str, str] | object,
    context: ProjectContextLike,
    key: str,
) -> bool:
    normalized = key.strip().upper()
    if isinstance(env, dict) and normalized in {str(item).strip().upper() for item in env}:
        return True
    if not _config_file_belongs_to_context(config, context):
        return False
    return _explicit_config_key(config, env, key)


def _has_explicit_local_system_signal(
    runtime: object,
    context: ProjectContextLike,
    *,
    mode: str,
    selected_service_types: set[str],
) -> bool:
    config = getattr(runtime, "config")
    env = getattr(runtime, "env", {})
    normalized_mode = "main" if mode == "main" else "trees"
    if _context_config_key(config, env, context, f"{normalized_mode.upper()}_STARTUP_ENABLE"):
        return True
    for service_name in selected_service_types:
        normalized = service_name.strip().lower()
        if normalized not in {"backend", "frontend"}:
            return True
        prefix = normalized.upper()
        command_key = f"ENVCTL_{prefix}_START_CMD"
        if _explicit_config_key(config, env, command_key) and _raw_setting_value(config, env, command_key):
            return True
        dir_key = f"{prefix}_DIR"
        if _context_config_key(config, env, context, dir_key) and _raw_setting_value(config, env, dir_key):
            return True
        if _context_config_key(config, env, context, f"{normalized_mode.upper()}_{prefix}_ENABLE"):
            return True
        if _config_file_belongs_to_context(config, context) and _explicit_dependency_env_section(
            config,
            mode=normalized_mode,
            service_name=normalized,
        ):
            return True
    return False


def selected_default_services_have_no_local_system(
    runtime: object,
    context: ProjectContextLike,
    *,
    mode: str,
    route: Route | None,
    selected_service_types: set[str],
    configured_additional_services: tuple[object, ...],
) -> bool:
    if route is None or route.command != "plan" or route.flags.get("runtime_scope") != "entire-system":
        return False
    if not selected_service_types or not selected_service_types <= {"backend", "frontend"}:
        return False
    if configured_additional_services:
        return False
    if _has_explicit_local_system_signal(
        runtime,
        context,
        mode=mode,
        selected_service_types=selected_service_types,
    ):
        return False
    resolver = getattr(runtime, "_service_command_source", None)
    if not callable(resolver):
        return False
    for service_name in selected_service_types:
        try:
            source = resolver(service_name=service_name, project_root=context.root, port=0)
        except CommandResolutionError as exc:
            if exc.code == "missing_service_start_command":
                continue
            return False
        except RuntimeError:
            return False
        if source:
            return False
    return True


def record_no_local_system_skip(
    runtime: object,
    context: ProjectContextLike,
    *,
    mode: str,
    route: Route | None,
    selected_service_types: set[str],
) -> None:
    requested_scope = str(route.flags.get("runtime_scope", "")) if route is not None else ""
    payload: dict[str, object] = {
        "project": context.name,
        "mode": mode,
        "reason": "no_system_configured",
        "selected_service_types": sorted(selected_service_types),
    }
    if requested_scope:
        payload["requested_scope"] = requested_scope
    runtime._emit("service.attach.skipped", **payload)  # type: ignore[attr-defined]
    record_warning = getattr(runtime, "_record_project_startup_warning", None)
    if callable(record_warning):
        record_warning(
            context.name,
            (
                f"No local app system is configured for {context.name}; continuing with the "
                "implementation session only. --entire-system was honored, but there was "
                "nothing configured to start."
            ),
        )


def skip_unconfigured_services(
    runtime: object,
    context: ProjectContextLike,
    mode: str,
    route: Route | None,
    selected_service_types: set[str],
    configured_additional_services: tuple[object, ...],
) -> bool:
    if not selected_service_types:
        runtime._emit(  # type: ignore[attr-defined]
            "service.attach.skipped",
            project=context.name,
            mode=mode,
            reason="all_services_disabled",
        )
        return True
    if not selected_default_services_have_no_local_system(
        runtime,
        context,
        mode=mode,
        route=route,
        selected_service_types=selected_service_types,
        configured_additional_services=configured_additional_services,
    ):
        return False
    record_no_local_system_skip(
        runtime,
        context,
        mode=mode,
        route=route,
        selected_service_types=selected_service_types,
    )
    return True
