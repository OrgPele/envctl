from __future__ import annotations

import json
from pathlib import Path

from envctl_engine.shared.services import project_name_from_service_name
from envctl_engine.state.models import RunState


def build_runtime_map(state: RunState, *, host: str = "localhost") -> dict[str, object]:
    projects: dict[str, dict[str, object]] = {}
    port_to_service: dict[int, str] = {}
    service_to_actual_port: dict[str, int] = {}
    for service in state.services.values():
        project = project_name_from_service_name(service.name)
        project_entry = projects.setdefault(project, {"backend_port": None, "frontend_port": None})
        port = service.actual_port if service.actual_port is not None else service.requested_port
        if service.type == "backend":
            project_entry["backend_port"] = port
        elif service.type == "frontend":
            project_entry["frontend_port"] = port
        if port is not None:
            port_to_service[port] = service.name
            service_to_actual_port[service.name] = port
    projection = build_runtime_projection(state, host=host)
    return {
        "schema_version": "1.0",
        "backend_mode": "python",
        "run_id": state.run_id,
        "mode": state.mode,
        "projects": projects,
        "port_to_service": port_to_service,
        "service_to_actual_port": service_to_actual_port,
        "projection": projection,
    }


def write_runtime_map(path: str, state: RunState) -> None:
    Path(path).write_text(json.dumps(build_runtime_map(state), indent=2, sort_keys=True), encoding="utf-8")


def build_runtime_projection(state: RunState, *, host: str = "localhost") -> dict[str, dict[str, object]]:
    runtime_map = build_runtime_map_without_projection(state)
    projection: dict[str, dict[str, object]] = {}
    projects = runtime_map["projects"]
    service_records = state.services
    for project, ports in projects.items():
        backend_port = ports.get("backend_port")
        frontend_port = ports.get("frontend_port")
        backend_service = service_records.get(f"{project} Backend")
        frontend_service = service_records.get(f"{project} Frontend")
        backend_ready = _service_projection_ready(backend_service)
        frontend_ready = _service_projection_ready(frontend_service)
        projection[project] = {
            "backend_port": backend_port,
            "frontend_port": frontend_port,
            "backend_url": (
                f"http://{host}:{backend_port}" if backend_port is not None and backend_ready else None
            ),
            "frontend_url": (
                f"http://{host}:{frontend_port}" if frontend_port is not None and frontend_ready else None
            ),
            "backend_status": getattr(backend_service, "status", "unknown") if backend_service is not None else "unknown",
            "frontend_status": getattr(frontend_service, "status", "unknown") if frontend_service is not None else "unknown",
        }
    return projection

def build_runtime_map_without_projection(state: RunState) -> dict[str, object]:
    projects: dict[str, dict[str, object]] = {}
    port_to_service: dict[int, str] = {}
    service_to_actual_port: dict[str, int] = {}
    for service in state.services.values():
        project = project_name_from_service_name(service.name)
        project_entry = projects.setdefault(project, {"backend_port": None, "frontend_port": None})
        port = service.actual_port if service.actual_port is not None else service.requested_port
        if service.type == "backend":
            project_entry["backend_port"] = port
        elif service.type == "frontend":
            project_entry["frontend_port"] = port
        if port is not None:
            port_to_service[port] = service.name
            service_to_actual_port[service.name] = port
    return {
        "schema_version": "1.0",
        "backend_mode": "python",
        "run_id": state.run_id,
        "mode": state.mode,
        "projects": projects,
        "port_to_service": port_to_service,
        "service_to_actual_port": service_to_actual_port,
    }


def _service_projection_ready(service: object | None) -> bool:
    if service is None:
        return False
    status = str(getattr(service, "status", "unknown")).strip().lower()
    return status in {"running", "healthy", "starting"}
