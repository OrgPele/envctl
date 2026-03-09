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
    return {
        "VITE_BACKEND_URL": f"http://{host}:{backend_port}",
    }


def project_name_from_service_name(service_name: str) -> str:
    for suffix in (" Backend", " Frontend"):
        if service_name.endswith(suffix):
            return service_name[: -len(suffix)]
    return service_name
