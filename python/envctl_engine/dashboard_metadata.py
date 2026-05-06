from __future__ import annotations

from collections.abc import Mapping

from envctl_engine.shared.services import service_display_name

APP_SERVICE_TYPES = ("backend", "frontend")
APP_SERVICE_TYPE_SET = frozenset(APP_SERVICE_TYPES)
_SERVICE_SLUG_RE = __import__("re").compile(r"^[a-z][a-z0-9-]*$")
DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY = "dashboard_project_configured_services"
DASHBOARD_CONFIGURED_SERVICE_TYPES_KEY = "dashboard_configured_service_types"
DASHBOARD_STOPPED_SERVICES_KEY = "dashboard_stopped_services"


def normalize_dashboard_service_types(raw: object) -> list[str]:
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return []
    normalized = {
        value
        for service_type in raw
        for value in [str(service_type).strip().lower()]
        if _SERVICE_SLUG_RE.fullmatch(value)
    }
    return sorted(normalized)


def dashboard_project_configured_services_from_metadata(metadata: Mapping[str, object]) -> dict[str, set[str]]:
    raw = metadata.get(DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY)
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


def serialize_dashboard_project_configured_services(
    configured: Mapping[str, object],
) -> dict[str, list[str]]:
    serialized: dict[str, list[str]] = {}
    for project_raw, service_types_raw in configured.items():
        project = str(project_raw).strip()
        if not project:
            continue
        service_types = normalize_dashboard_service_types(service_types_raw)
        if service_types:
            serialized[project] = service_types
    return dict(sorted(serialized.items(), key=lambda item: item[0].casefold()))


def dashboard_configured_missing_services_by_project(
    *,
    configured_services: Mapping[str, set[str]],
    stopped_services: Mapping[str, Mapping[str, str]],
    active_service_names: set[str],
) -> dict[str, set[str]]:
    missing: dict[str, set[str]] = {}
    for project, service_types in configured_services.items():
        stopped_for_project = stopped_services.get(project, {})
        for service_type in service_types:
            service_name = f"{project} {service_display_name(service_type)}"
            if service_name in active_service_names or service_type in stopped_for_project:
                continue
            missing.setdefault(project, set()).add(service_type)
    return missing


def _service_display_name(service_type: str) -> str:
    return " ".join(part.capitalize() for part in str(service_type).replace("_", "-").split("-") if part)
