from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, cast

from envctl_engine.runtime.command_resolution import suggest_service_start_command
from envctl_engine.shared.node_tooling import CommandExists


DEFAULT_APP_SERVICE_TYPES = frozenset({"backend", "frontend"})


@dataclass(frozen=True, slots=True)
class NoSystemConfiguredSkip:
    project: str
    mode: str
    requested_scope: str
    selected_services: tuple[str, ...]


def classify_no_local_app_system(
    *,
    runtime: Any,
    project_name: str,
    project_root: Path,
    mode: str,
    selected_service_types: set[str],
    configured_additional_services: tuple[object, ...],
    route: Any | None,
) -> NoSystemConfiguredSkip | None:
    requested_scope = _requested_scope(route)
    if str(getattr(route, "command", "")).strip().lower() != "plan":
        return None
    if requested_scope != "entire-system":
        return None
    selected_defaults = tuple(
        sorted(service for service in selected_service_types if service in DEFAULT_APP_SERVICE_TYPES)
    )
    if not selected_defaults or set(selected_defaults) != set(selected_service_types):
        return None
    if configured_additional_services:
        return None
    if _has_explicit_local_system_signal(runtime=runtime, mode=mode, selected_services=selected_defaults):
        return None
    if _has_autodetectable_default_service(
        runtime=runtime,
        project_root=project_root,
        selected_services=selected_defaults,
    ):
        return None
    return NoSystemConfiguredSkip(
        project=project_name,
        mode=mode,
        requested_scope=requested_scope,
        selected_services=selected_defaults,
    )


def record_no_local_app_system_skip(route: Any | None, skip: NoSystemConfiguredSkip) -> None:
    if route is None:
        return
    flags = getattr(route, "flags", None)
    if not isinstance(flags, dict):
        return
    skips = flags.setdefault("_no_system_configured_projects", [])
    if isinstance(skips, list):
        skips.append(
            {
                "project": skip.project,
                "mode": skip.mode,
                "requested_scope": skip.requested_scope,
                "selected_services": list(skip.selected_services),
            }
        )


def no_local_app_system_skip_messages(route: Any | None) -> list[str]:
    flags = getattr(route, "flags", None)
    if not isinstance(flags, dict):
        return []
    skips = flags.get("_no_system_configured_projects")
    if not isinstance(skips, list) or not skips:
        return []
    projects = sorted(
        {
            str(skip.get("project", "")).strip()
            for skip in skips
            if isinstance(skip, dict) and str(skip.get("project", "")).strip()
        }
    )
    if not projects:
        project_text = "this repo/worktree"
    elif len(projects) == 1:
        project_text = projects[0]
    else:
        project_text = ", ".join(projects)
    return [
        f"No local app system is configured for {project_text}.",
        "envctl is continuing with the implementation session only.",
        "`--entire-system` was honored, but there was nothing configured to start.",
    ]


def copy_no_local_app_system_skips(*, source_route: Any | None, target_route: Any | None) -> None:
    source_flags = getattr(source_route, "flags", None)
    target_flags = getattr(target_route, "flags", None)
    if not isinstance(source_flags, dict) or not isinstance(target_flags, dict):
        return
    skips = source_flags.get("_no_system_configured_projects")
    if isinstance(skips, list) and skips:
        target_flags["_no_system_configured_projects"] = list(skips)


def _requested_scope(route: Any | None) -> str:
    flags = getattr(route, "flags", None)
    if not isinstance(flags, Mapping):
        return ""
    return str(flags.get("runtime_scope", "")).strip().lower()


def _has_explicit_local_system_signal(*, runtime: Any, mode: str, selected_services: tuple[str, ...]) -> bool:
    config = getattr(runtime, "config", None)
    env = getattr(runtime, "env", {}) or {}
    explicit_keys = {str(key).strip().upper() for key in getattr(config, "explicit_keys", set()) or set()}
    env_keys = {str(key).strip().upper() for key in env}
    explicit_or_env_keys = explicit_keys | env_keys
    mode_prefix = str(mode).strip().upper() or "MAIN"

    signal_keys: set[str] = {f"{mode_prefix}_STARTUP_ENABLE"}
    for service in selected_services:
        upper_service = service.upper()
        signal_keys.update(
            {
                f"ENVCTL_{upper_service}_START_CMD",
                f"{upper_service}_DIR",
                f"{mode_prefix}_{upper_service}_ENABLE",
            }
        )
    if explicit_or_env_keys & signal_keys:
        return True

    section_flags = []
    if "backend" in selected_services:
        section_flags.extend(
            [
                getattr(config, "backend_dependency_env_section_present", False),
                getattr(config, f"{mode}_backend_dependency_env_section_present", False),
            ]
        )
    if "frontend" in selected_services:
        section_flags.extend(
            [
                getattr(config, "frontend_dependency_env_section_present", False),
                getattr(config, f"{mode}_frontend_dependency_env_section_present", False),
            ]
        )
    if any(bool(flag) for flag in section_flags):
        return True

    service_sections = getattr(config, "service_dependency_env_section_present", {}) or {}
    mode_service_sections = getattr(config, "mode_service_dependency_env_section_present", {}) or {}
    return any(bool(service_sections.get(service)) for service in selected_services) or any(
        bool(mode_service_sections.get((mode, service))) for service in selected_services
    )


def _has_autodetectable_default_service(
    *,
    runtime: Any,
    project_root: Path,
    selected_services: tuple[str, ...],
) -> bool:
    raw_command_exists = getattr(runtime, "_command_exists", None)
    command_exists = cast(CommandExists | None, raw_command_exists) if callable(raw_command_exists) else None
    return any(
        suggest_service_start_command(
            service_name=service,
            project_root=project_root,
            command_exists=command_exists,
        )
        is not None
        for service in selected_services
    )
