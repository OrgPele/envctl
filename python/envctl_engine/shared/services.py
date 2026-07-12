from __future__ import annotations

from collections.abc import Callable

from envctl_engine.state.models import RunState, ServiceRecord


def frontend_env_for_project(state: RunState, project: str, *, host: str = "localhost") -> dict[str, str]:
    backend = service_for_project_type(state, project=project, service_type="backend")
    backend_port = None
    if backend is not None:
        backend_port = backend.actual_port if backend.actual_port is not None else backend.requested_port
    if backend_port is None:
        return {}
    backend_url = f"http://{host}:{backend_port}"
    return {
        "VITE_BACKEND_URL": backend_url,
        "VITE_API_URL": f"{backend_url}/api/v1",
    }


def project_name_from_service_name(service_name: str) -> str:
    for suffix in (" Backend", " Frontend"):
        if service_name.endswith(suffix):
            return service_name[: -len(suffix)]
    parts = str(service_name).rsplit(" ", 1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return parts[0]
    return service_name


def service_display_name(service_type: str) -> str:
    return " ".join(
        part.capitalize() for part in str(service_type).replace("_", "-").split("-") if part
    )


def service_slug_from_record(service: object) -> str:
    explicit = str(getattr(service, "service_slug", "") or "").strip().lower()
    if explicit:
        return explicit
    return str(getattr(service, "type", "") or "").strip().lower()


def service_project_name(service: object) -> str:
    explicit = str(getattr(service, "project", "") or "").strip()
    if explicit:
        return explicit
    typed_project = _typed_service_project_name(service)
    if typed_project:
        return typed_project
    return project_name_from_service_name(str(getattr(service, "name", "") or ""))


def _typed_service_project_name(service: object) -> str:
    name = str(getattr(service, "name", "") or "").strip()
    display = service_display_name(service_slug_from_record(service))
    suffix = f" {display}" if display else ""
    if suffix and name.casefold().endswith(suffix.casefold()):
        return name[: -len(suffix)].strip()
    collision_marker = f" {display} " if display else ""
    if collision_marker:
        marker_index = name.casefold().rfind(collision_marker.casefold())
        if marker_index > 0:
            collision_suffix = name[marker_index + len(collision_marker) :].strip().casefold()
            if collision_suffix.startswith(("restart collision", "resume collision", "state collision")):
                return name[:marker_index].strip()
    return ""


def service_for_project_type(state: RunState, *, project: str, service_type: str) -> ServiceRecord | None:
    project_key = str(project).strip().casefold()
    type_key = str(service_type).strip().lower()
    for service in state.services.values():
        if service_project_name(service).casefold() != project_key:
            continue
        if service_slug_from_record(service) == type_key:
            return service
    return None


def resolve_service_project_name(
    service_name: str,
    service: object | None,
    *,
    project_name_from_service: Callable[[str], object] | None = None,
) -> str:
    """Resolve project ownership without discarding authoritative record metadata."""
    explicit = str(getattr(service, "project", "") or "").strip()
    if explicit:
        return explicit
    typed_project = _typed_service_project_name(service) if service is not None else ""
    if typed_project:
        return typed_project
    if project_name_from_service is not None:
        legacy = str(project_name_from_service(service_name) or "").strip()
        if legacy:
            return legacy
    if service is not None:
        record_project = service_project_name(service)
        if record_project:
            return record_project
    return project_name_from_service_name(str(service_name))


def service_matches_selector(service: object, selector: str) -> bool:
    target = str(selector or "").strip().lower()
    if not target:
        return False
    if target.startswith("service:"):
        target = target.removeprefix("service:").strip()
    name = str(getattr(service, "name", "") or "").strip()
    slug = service_slug_from_record(service)
    display = service_display_name(slug)
    project = service_project_name(service)
    candidates = {
        name.lower(),
        slug,
        display.lower(),
        f"service:{slug}",
    }
    if project and display:
        candidates.add(f"{project} {display}".lower())
    return target in candidates
