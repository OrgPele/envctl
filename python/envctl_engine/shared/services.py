from __future__ import annotations

from envctl_engine.state.models import RunState


def frontend_env_for_project(state: RunState, project: str, *, host: str = "localhost") -> dict[str, str]:
    backend_port = None
    for service in state.services.values():
        if project_name_from_service_name(service.name) != project:
            continue
        if service.type != "backend":
            continue
        backend_port = service.actual_port if service.actual_port is not None else service.requested_port
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
    return project_name_from_service_name(str(getattr(service, "name", "") or ""))


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
