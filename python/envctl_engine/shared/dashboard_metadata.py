from __future__ import annotations

from collections.abc import Mapping

from envctl_engine.state.models import RunState

DASHBOARD_CONFIGURED_SERVICE_TYPES_KEY = "dashboard_configured_service_types"
DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY = "dashboard_project_configured_services"
DASHBOARD_STOPPED_SERVICES_KEY = "dashboard_stopped_services"
DASHBOARD_APP_SERVICE_TYPES = frozenset({"backend", "frontend"})


def normalize_dashboard_service_types(raw_types: object) -> list[str]:
    if not isinstance(raw_types, (list, tuple, set, frozenset)):
        return []
    normalized = {
        str(service_type).strip().lower()
        for service_type in raw_types
        if str(service_type).strip().lower() in DASHBOARD_APP_SERVICE_TYPES
    }
    return sorted(normalized)


def serialize_dashboard_project_configured_services(
    configured_by_project: Mapping[str, object],
) -> dict[str, list[str]]:
    serialized: dict[str, list[str]] = {}
    for project_raw, service_types_raw in configured_by_project.items():
        project = str(project_raw).strip()
        if not project:
            continue
        service_types = normalize_dashboard_service_types(service_types_raw)
        if service_types:
            serialized[project] = service_types
    return serialized


def dashboard_project_configured_services(state: RunState) -> dict[str, set[str]]:
    raw = state.metadata.get(DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY)
    if not isinstance(raw, Mapping):
        return {}
    configured: dict[str, set[str]] = {}
    for project_raw, service_types_raw in raw.items():
        project = str(project_raw).strip()
        if not project:
            continue
        service_types = set(normalize_dashboard_service_types(service_types_raw))
        if service_types:
            configured[project] = service_types
    return configured


def dashboard_global_configured_service_types(state: RunState) -> set[str]:
    return set(normalize_dashboard_service_types(state.metadata.get(DASHBOARD_CONFIGURED_SERVICE_TYPES_KEY)))


def dashboard_stopped_services_by_project(state: RunState) -> dict[str, dict[str, str]]:
    raw = state.metadata.get(DASHBOARD_STOPPED_SERVICES_KEY)
    if not isinstance(raw, list):
        return {}
    stopped: dict[str, dict[str, str]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        project = str(item.get("project", "") or "").strip()
        service_type = str(item.get("type", "") or "").strip().lower()
        name = str(item.get("name", "") or "").strip()
        if not project or service_type not in DASHBOARD_APP_SERVICE_TYPES:
            continue
        stopped.setdefault(project, {})[service_type] = name or canonical_dashboard_service_name(project, service_type)
    return stopped


def canonical_dashboard_service_name(project: str, service_type: str) -> str:
    return f"{str(project).strip()} {str(service_type).strip().title()}"


def dashboard_configured_missing_services_by_project(state: RunState) -> dict[str, dict[str, str]]:
    configured = dashboard_project_configured_services(state)
    if not configured:
        return {}
    stopped = dashboard_stopped_services_by_project(state)
    active_names = set(state.services)
    missing: dict[str, dict[str, str]] = {}
    for project, service_types in configured.items():
        stopped_for_project = stopped.get(project, {})
        for service_type in sorted(service_types):
            service_name = canonical_dashboard_service_name(project, service_type)
            if service_name in active_names or service_type in stopped_for_project:
                continue
            missing.setdefault(project, {})[service_type] = service_name
    return missing
