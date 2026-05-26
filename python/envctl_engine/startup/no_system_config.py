from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

from envctl_engine.runtime.command_resolution import CommandResolutionError, resolve_service_start_command
from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.protocols import ProjectContextLike, StartupOrchestratorLike

_DEFAULT_APP_SERVICES = {"backend", "frontend"}


def no_local_app_system_configured(
    *,
    config: Any,
    env: Mapping[str, str],
    route: Route | None,
    mode: str,
    project_root: Path,
    selected_service_types: set[str],
    command_exists: Callable[[str], bool] | None,
) -> bool:
    if route is None or route.command != "plan" or route.flags.get("runtime_scope") != "entire-system":
        return False
    if not selected_service_types or not selected_service_types <= _DEFAULT_APP_SERVICES:
        return False
    if _has_explicit_local_system_signal(
        config,
        env=env,
        mode=mode,
        selected_service_types=selected_service_types,
    ):
        return False
    for service_name in selected_service_types:
        if _service_autodetects(
            config=config,
            env=env,
            service_name=service_name,
            project_root=project_root,
            command_exists=command_exists,
        ):
            return False
    return True


def no_local_app_system_message() -> str:
    return (
        "no local app system is configured for this repo/worktree; continuing with the implementation "
        "session only. --entire-system was honored, but there was nothing configured to start."
    )


def skip_no_local_app_system_services(
    orchestrator: StartupOrchestratorLike,
    context: ProjectContextLike,
    route: Route | None,
    mode: str,
    selected_service_types: set[str],
) -> bool:
    rt = orchestrator.runtime
    if not no_local_app_system_configured(
        config=rt.config,
        env=rt.env,
        route=route,
        mode=mode,
        project_root=context.root,
        selected_service_types=selected_service_types,
        command_exists=getattr(rt, "_command_exists", None),
    ):
        return False
    rt._emit(
        "service.attach.skipped",
        project=context.name,
        mode=mode,
        reason="no_system_configured",
        requested_scope=route.flags.get("runtime_scope") if route is not None else None,
        selected_service_types=sorted(selected_service_types),
    )
    record_warning = getattr(rt, "_record_project_startup_warning", None)
    if callable(record_warning):
        record_warning(context.name, no_local_app_system_message())
    return True


def _has_explicit_local_system_signal(
    config: Any,
    *,
    env: Mapping[str, str],
    mode: str,
    selected_service_types: set[str],
) -> bool:
    explicit_keys = {str(key).strip().upper() for key in getattr(config, "explicit_keys", ()) if str(key).strip()}
    explicit_keys.update(str(key).strip().upper() for key in env if str(key).strip())
    normalized_mode = str(mode).strip().lower() or "main"
    mode_prefix = normalized_mode.upper()

    if "ENVCTL_ADDITIONAL_SERVICES" in explicit_keys:
        return True
    if getattr(config, "additional_services", ()):
        return True

    for service_name in selected_service_types:
        service_prefix = service_name.upper()
        signal_keys = {
            f"ENVCTL_{service_prefix}_START_CMD",
            f"{service_prefix}_DIR",
            f"{mode_prefix}_STARTUP_ENABLE",
            f"{mode_prefix}_{service_prefix}_ENABLE",
        }
        if explicit_keys.intersection(signal_keys):
            return True
        if _service_dependency_env_section_present(config, mode=normalized_mode, service_name=service_name):
            return True
    return False


def _service_dependency_env_section_present(config: Any, *, mode: str, service_name: str) -> bool:
    service = service_name.strip().lower()
    normalized_mode = mode.strip().lower() or "main"
    if bool(getattr(config, f"{service}_dependency_env_section_present", False)):
        return True
    if bool(getattr(config, f"{normalized_mode}_{service}_dependency_env_section_present", False)):
        return True
    service_sections = getattr(config, "service_dependency_env_section_present", {}) or {}
    if bool(service_sections.get(service)):
        return True
    mode_service_sections = getattr(config, "mode_service_dependency_env_section_present", {}) or {}
    return bool(mode_service_sections.get((normalized_mode, service)))


def _service_autodetects(
    *,
    config: Any,
    env: Mapping[str, str],
    service_name: str,
    project_root: Path,
    command_exists: Callable[[str], bool] | None,
) -> bool:
    try:
        resolve_service_start_command(
            service_name=service_name,
            project_root=project_root,
            port=0,
            env=env,
            config_raw=getattr(config, "raw", {}),
            command_exists=command_exists,
        )
    except CommandResolutionError as exc:
        return exc.code != "missing_service_start_command"
    return True
