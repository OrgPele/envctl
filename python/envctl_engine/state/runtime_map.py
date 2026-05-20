from __future__ import annotations

import json
from pathlib import Path

from envctl_engine.shared.services import project_name_from_service_name
from envctl_engine.state.models import RunState


def build_runtime_map(state: RunState, *, host: str = "localhost") -> dict[str, object]:
    runtime_map = build_runtime_map_without_projection(state, host=host)
    projection = build_runtime_projection(state, host=host)
    return {
        **runtime_map,
        "projection": projection,
    }


def write_runtime_map(path: str, state: RunState) -> None:
    Path(path).write_text(json.dumps(build_runtime_map(state), indent=2, sort_keys=True), encoding="utf-8")


def build_runtime_projection(state: RunState, *, host: str = "localhost") -> dict[str, dict[str, object]]:
    runtime_map = build_runtime_map_without_projection(state, host=host)
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
            "backend_url": (f"http://{host}:{backend_port}" if backend_port is not None and backend_ready else None),
            "frontend_url": (
                f"http://{host}:{frontend_port}" if frontend_port is not None and frontend_ready else None
            ),
            "backend_status": getattr(backend_service, "status", "unknown")
            if backend_service is not None
            else "unknown",
            "frontend_status": getattr(frontend_service, "status", "unknown")
            if frontend_service is not None
            else "unknown",
            "services": ports.get("services", {}),
        }
    return projection


def build_runtime_map_without_projection(state: RunState, *, host: str = "localhost") -> dict[str, object]:
    projects: dict[str, dict[str, object]] = {}
    port_to_service: dict[int, str] = {}
    service_to_actual_port: dict[str, int] = {}
    service_to_url: dict[str, str] = {}
    service_to_public_url: dict[str, str] = {}
    service_to_health_url: dict[str, str] = {}
    for service in state.services.values():
        project = str(getattr(service, "project", "") or "").strip() or _project_name_from_service_record(service)
        project_entry = projects.setdefault(project, {"backend_port": None, "frontend_port": None, "services": {}})
        port = service.actual_port if service.actual_port is not None else service.requested_port
        service_ready = _service_projection_ready(service)
        url = f"http://{host}:{port}" if port is not None and service_ready else None
        public_url = str(getattr(service, "public_url", "") or "").strip() or url
        health_url = str(getattr(service, "health_url", "") or "").strip() or None
        service_slug = str(getattr(service, "service_slug", "") or "").strip() or service.type
        services_entry = project_entry.setdefault("services", {})
        if isinstance(services_entry, dict):
            services_entry[service_slug] = {
                "name": service.name,
                "type": service.type,
                "service_slug": service_slug,
                "port": port,
                "url": url,
                "public_url": public_url,
                "health_url": health_url,
                "status": service.status,
                "cwd": service.cwd,
                "listener_expected": service.listener_expected,
                "requested_port": service.requested_port,
                "actual_port": service.actual_port,
                "log_path": service.log_path,
                "failure_detail": getattr(service, "failure_detail", None),
                "critical": getattr(service, "critical", True),
                "degraded": getattr(service, "degraded", False),
            }
        if service.type == "backend":
            project_entry["backend_port"] = port
        elif service.type == "frontend":
            project_entry["frontend_port"] = port
        if port is not None:
            port_to_service[port] = service.name
            service_to_actual_port[service.name] = port
            if url is not None:
                service_to_url[service.name] = url
            if public_url:
                service_to_public_url[service.name] = public_url
            if health_url:
                service_to_health_url[service.name] = health_url
    return {
        "schema_version": "1.0",
        "backend_mode": "python",
        "run_id": state.run_id,
        "mode": state.mode,
        "projects": projects,
        "port_to_service": port_to_service,
        "service_to_actual_port": service_to_actual_port,
        "service_to_url": service_to_url,
        "service_to_public_url": service_to_public_url,
        "service_to_health_url": service_to_health_url,
    }


def _service_projection_ready(service: object | None) -> bool:
    if service is None:
        return False
    status = str(getattr(service, "status", "unknown")).strip().lower()
    return status in {"running", "healthy", "starting"}


def _project_name_from_service_record(service: object) -> str:
    name = str(getattr(service, "name", "") or "").strip()
    service_type = str(getattr(service, "type", "") or "").strip().lower()
    display_suffix = " ".join(part.capitalize() for part in service_type.replace("_", "-").split("-") if part)
    if display_suffix and name.endswith(f" {display_suffix}"):
        return name[: -(len(display_suffix) + 1)]
    return project_name_from_service_name(name)
