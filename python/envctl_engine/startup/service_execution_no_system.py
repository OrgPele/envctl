from __future__ import annotations

from pathlib import Path
from typing import Any

from envctl_engine.runtime.command_resolution import CommandResolutionError
from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.protocols import ProjectContextLike


def route_requested_entire_system(route: Route | None) -> bool:
    if route is None:
        return False
    if route.command != "plan":
        return False
    return str(route.flags.get("runtime_scope", "")).strip().lower() == "entire-system"


def has_explicit_app_service_signal(rt: Any, *, mode: str, service_name: str) -> bool:
    normalized = str(service_name).strip().lower()
    upper = normalized.upper()
    mode_upper = str(mode).strip().upper()
    explicit_keys = {str(key).strip().upper() for key in getattr(rt.config, "explicit_keys", ())}
    env = getattr(rt, "env", {})

    def explicit_or_env(key: str) -> bool:
        return key in explicit_keys or str(env.get(key, "")).strip() != ""

    explicit_signal_keys = {
        f"ENVCTL_{upper}_START_CMD",
        f"{upper}_DIR",
        f"{mode_upper}_{upper}_ENABLE",
        f"{mode_upper}_STARTUP_ENABLE",
    }
    if any(explicit_or_env(key) for key in explicit_signal_keys):
        return True

    section_attrs = (
        f"{normalized}_dependency_env_section_present",
        f"{mode}_{normalized}_dependency_env_section_present",
    )
    if any(bool(getattr(rt.config, attr, False)) for attr in section_attrs):
        return True

    service_sections = getattr(rt.config, "service_dependency_env_section_present", None) or {}
    if bool(service_sections.get(normalized)):
        return True
    mode_service_sections = getattr(rt.config, "mode_service_dependency_env_section_present", None) or {}
    return bool(mode_service_sections.get((mode, normalized)))


def service_has_resolvable_command(rt: Any, *, service_name: str, project_root: Path, port: int) -> bool:
    try:
        rt._service_command_source(service_name=service_name, project_root=project_root, port=port)
    except CommandResolutionError as exc:
        if exc.code == "missing_service_start_command":
            return False
        return True
    return True


def selected_services_are_default_no_system(
    rt: Any,
    *,
    context: ProjectContextLike,
    mode: str,
    route: Route | None,
    selected_service_types: set[str],
    backend_port: int,
    frontend_port: int,
) -> bool:
    if not route_requested_entire_system(route):
        return False
    if not selected_service_types:
        return False
    if not selected_service_types.issubset({"backend", "frontend"}):
        return False
    if any(
        has_explicit_app_service_signal(rt, mode=mode, service_name=service_name)
        for service_name in selected_service_types
    ):
        return False

    ports = {"backend": backend_port, "frontend": frontend_port}
    return not any(
        service_has_resolvable_command(
            rt,
            service_name=service_name,
            project_root=context.root,
            port=ports[service_name],
        )
        for service_name in selected_service_types
    )


def skip_default_no_system_services(
    rt: Any,
    context: ProjectContextLike,
    mode: str,
    route: Route | None,
    selected_service_types: set[str],
    ports: tuple[int, int],
) -> bool:
    backend_port, frontend_port = ports
    if not selected_services_are_default_no_system(
        rt,
        context=context,
        mode=mode,
        route=route,
        selected_service_types=selected_service_types,
        backend_port=backend_port,
        frontend_port=frontend_port,
    ):
        return False
    selected_defaults = sorted(selected_service_types)
    rt._emit(
        "service.attach.skipped",
        project=context.name,
        mode=mode,
        reason="no_system_configured",
        requested_scope="entire-system",
        selected_services=selected_defaults,
    )
    warning = (
        "No local app system is configured for this repo/worktree; envctl is continuing with the "
        "implementation session only. --entire-system was honored, but there was nothing configured to start."
    )
    rt._record_project_startup_warning(context.name, warning)
    return True
