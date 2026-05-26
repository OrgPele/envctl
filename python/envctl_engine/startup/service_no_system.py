from __future__ import annotations

from envctl_engine.runtime.command_resolution import CommandResolutionError
from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.protocols import ProjectContextLike


DEFAULT_APP_SERVICE_TYPES = {"backend", "frontend"}
NO_LOCAL_APP_SYSTEM_MESSAGE = (
    "No local app system is configured for this repo/worktree; continuing with the implementation "
    "session only. --entire-system was honored, but there was nothing configured to start."
)


def should_skip_no_local_app_system(
    rt: object,
    *,
    context: ProjectContextLike,
    route: Route | None,
    mode: str,
    selected_service_types: set[str],
    backend_port: int,
    frontend_port: int,
) -> bool:
    if route is None or route.command != "plan" or route.flags.get("runtime_scope") != "entire-system":
        return False
    if not selected_service_types or not selected_service_types <= DEFAULT_APP_SERVICE_TYPES:
        return False
    config = getattr(rt, "config", None)
    if config is None:
        return False
    if _has_explicit_local_system_signal(config, mode=mode, selected_service_types=selected_service_types):
        return False
    return not _selected_defaults_have_autodetected_system(
        rt,
        context=context,
        selected_service_types=selected_service_types,
        backend_port=backend_port,
        frontend_port=frontend_port,
    )


def record_no_local_app_system_skip(
    rt: object,
    *,
    context: ProjectContextLike,
    mode: str,
    selected_service_types: set[str],
) -> None:
    record_warning = getattr(rt, "_record_project_startup_warning", None)
    if callable(record_warning):
        record_warning(context.name, NO_LOCAL_APP_SYSTEM_MESSAGE)
    rt._emit(  # type: ignore[attr-defined]
        "service.attach.skipped",
        project=context.name,
        mode=mode,
        reason="no_system_configured",
        requested_scope="entire-system",
        selected_service_types=sorted(selected_service_types),
    )


def _has_explicit_local_system_signal(
    config: object,
    *,
    mode: str,
    selected_service_types: set[str],
) -> bool:
    explicit_keys = {str(key).strip().upper() for key in getattr(config, "explicit_keys", ())}
    mode_key = mode.strip().upper()
    selected_default_services = selected_service_types.intersection(DEFAULT_APP_SERVICE_TYPES)
    for service_name in selected_default_services:
        service_key = service_name.upper()
        if {
            f"ENVCTL_{service_key}_START_CMD",
            f"{service_key}_DIR",
            f"{mode_key}_{service_key}_ENABLE",
            f"{mode_key}_{service_key}_EXPECT_LISTENER",
            f"{mode_key}_STARTUP_ENABLE",
        }.intersection(explicit_keys):
            return True

    if getattr(config, "additional_services", ()):
        return True

    mode_service_sections = getattr(config, "mode_service_dependency_env_section_present", None) or {}
    service_sections = getattr(config, "service_dependency_env_section_present", None) or {}
    for service_name in selected_default_services:
        if bool(service_sections.get(service_name)):
            return True
        if bool(mode_service_sections.get((mode, service_name))):
            return True
        attr_names = (
            f"{service_name}_dependency_env_section_present",
            f"{mode}_{service_name}_dependency_env_section_present",
        )
        if any(bool(getattr(config, attr_name, False)) for attr_name in attr_names):
            return True
    return False


def _selected_defaults_have_autodetected_system(
    rt: object,
    *,
    context: ProjectContextLike,
    selected_service_types: set[str],
    backend_port: int,
    frontend_port: int,
) -> bool:
    service_ports = {"backend": backend_port, "frontend": frontend_port}
    for service_name in sorted(selected_service_types.intersection(DEFAULT_APP_SERVICE_TYPES)):
        resolver = getattr(rt, "_service_command_source", None)
        if not callable(resolver):
            return True
        try:
            source = resolver(
                service_name=service_name,
                project_root=context.root,
                port=service_ports[service_name],
            )
        except CommandResolutionError as exc:
            if exc.code == "missing_service_start_command":
                continue
            return True
        except RuntimeError:
            return True
        if str(source or "").strip():
            return True
    return False
