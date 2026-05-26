from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from envctl_engine.dashboard_metadata import (
    DASHBOARD_CONFIGURED_SERVICE_TYPES_KEY,
    DASHBOARD_STOPPED_SERVICES_KEY,
)
from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.services import service_project_name, service_slug_from_record
from envctl_engine.state.models import RunState


def should_preserve_stopped_dashboard_state(route: Route) -> bool:
    if bool(route.flags.get("interactive_command")):
        return True
    if bool(route.flags.get("stop_preserve_requirements")):
        return True
    services = route.flags.get("services")
    return isinstance(services, list) and any(str(item).strip() for item in services)


def remember_dashboard_stopped_services(
    state: RunState,
    selected_services: set[str],
    *,
    project_name_from_service_fn: Callable[[str], str],
) -> None:
    if not selected_services:
        return

    by_name = _existing_stopped_services_by_name(state)
    project_roots = _existing_project_roots(state)
    configured_types = _existing_configured_service_types(state)

    for service_name in sorted(selected_services):
        service = state.services.get(service_name)
        if service is None:
            continue

        project = _stopped_service_project(
            service_name,
            service,
            project_name_from_service_fn=project_name_from_service_fn,
        )
        service_type = service_type_from_stopped_service(service_name, service)
        if not project or not service_type:
            continue

        by_name[service_name] = {"name": service_name, "project": project, "type": service_type}
        configured_types.add(service_type)
        if project not in project_roots:
            root = project_root_from_stopped_service(service, service_type=service_type)
            if root:
                project_roots[project] = root

    if by_name:
        state.metadata[DASHBOARD_STOPPED_SERVICES_KEY] = [by_name[name] for name in sorted(by_name)]
    if project_roots:
        state.metadata["project_roots"] = {str(key): str(value) for key, value in project_roots.items()}
    if configured_types:
        state.metadata[DASHBOARD_CONFIGURED_SERVICE_TYPES_KEY] = sorted(configured_types)


def has_dashboard_stopped_services(state: RunState) -> bool:
    raw = state.metadata.get(DASHBOARD_STOPPED_SERVICES_KEY)
    return isinstance(raw, list) and bool(raw)


def project_name_from_stopped_service(service_name: str) -> str:
    trimmed = str(service_name).strip()
    for suffix in (" Backend", " Frontend"):
        if trimmed.endswith(suffix):
            return trimmed[: -len(suffix)].strip()
    return ""


def service_type_from_stopped_service(service_name: str, service: object) -> str:
    service_type = service_slug_from_record(service)
    if service_type:
        return service_type
    lowered = str(service_name).strip().lower()
    if lowered.endswith(" backend"):
        return "backend"
    if lowered.endswith(" frontend"):
        return "frontend"
    return ""


def project_root_from_stopped_service(service: object, *, service_type: str) -> str:
    cwd_raw = str(getattr(service, "cwd", "") or "").strip()
    if not cwd_raw:
        return ""
    cwd = Path(cwd_raw).expanduser()
    if cwd.name.lower() == service_type:
        return str(cwd.parent)
    return str(cwd)


def _existing_stopped_services_by_name(state: RunState) -> dict[str, dict[str, str]]:
    raw_existing = state.metadata.get(DASHBOARD_STOPPED_SERVICES_KEY)
    existing_items = raw_existing if isinstance(raw_existing, list) else []
    by_name: dict[str, dict[str, str]] = {}
    for item in existing_items:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name", "") or "").strip()
        project = str(item.get("project", "") or "").strip()
        service_type = str(item.get("type", "") or "").strip().lower()
        if name and project and service_type:
            by_name[name] = {"name": name, "project": project, "type": service_type}
    return by_name


def _existing_project_roots(state: RunState) -> dict[str, object]:
    raw_roots = state.metadata.get("project_roots")
    return dict(raw_roots) if isinstance(raw_roots, Mapping) else {}


def _existing_configured_service_types(state: RunState) -> set[str]:
    raw_configured_types = state.metadata.get(DASHBOARD_CONFIGURED_SERVICE_TYPES_KEY)
    return {
        str(item).strip().lower()
        for item in (raw_configured_types if isinstance(raw_configured_types, list) else [])
        if str(item).strip()
    }


def _stopped_service_project(
    service_name: str,
    service: object,
    *,
    project_name_from_service_fn: Callable[[str], str],
) -> str:
    project = service_project_name(service)
    if project:
        return project
    project = str(project_name_from_service_fn(service_name) or "").strip()
    if project:
        return project
    return project_name_from_stopped_service(service_name)
