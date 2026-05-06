from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import cast

from envctl_engine.state.models import RunState


def build_runtime_map(state: RunState, *, host: str = "localhost") -> dict[str, object]:
    projects: dict[str, dict[str, object]] = {}
    port_to_service: dict[int, str] = {}
    service_to_actual_port: dict[str, int] = {}
    service_to_url: dict[str, str] = {}
    service_to_health_url: dict[str, str] = {}
    for service in state.services.values():
        project = _project_name_for_service(service)
        project_entry = projects.setdefault(project, {"backend_port": None, "frontend_port": None, "services": {}})
        port = service.actual_port if service.actual_port is not None else service.requested_port
        service_entry = _service_map_entry(service, port=port, host=host)
        services = project_entry.setdefault("services", {})
        if isinstance(services, dict):
            services[str(service.type)] = service_entry
        if service.type == "backend":
            project_entry["backend_port"] = port
        elif service.type == "frontend":
            project_entry["frontend_port"] = port
        if port is not None:
            port_to_service[port] = service.name
            service_to_actual_port[service.name] = port
        public_url = _service_public_url(service, port=port, host=host)
        if public_url:
            service_to_url[service.name] = public_url
        health_url = str(getattr(service, "health_url", "") or "").strip()
        if health_url:
            service_to_health_url[service.name] = health_url
    projection = build_runtime_projection(state, host=host)
    return {
        "schema_version": "1.0",
        "backend_mode": "python",
        "run_id": state.run_id,
        "mode": state.mode,
        "projects": projects,
        "port_to_service": port_to_service,
        "service_to_actual_port": service_to_actual_port,
        "service_to_url": service_to_url,
        "service_to_health_url": service_to_health_url,
        "projection": projection,
    }


def write_runtime_map(path: str, state: RunState) -> None:
    Path(path).write_text(json.dumps(build_runtime_map(state), indent=2, sort_keys=True), encoding="utf-8")


def build_runtime_projection(state: RunState, *, host: str = "localhost") -> dict[str, dict[str, object]]:
    runtime_map = build_runtime_map_without_projection(state)
    projection: dict[str, dict[str, object]] = {}
    projects = cast(Mapping[str, Mapping[str, object]], runtime_map["projects"])
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
    service_to_health_url: dict[str, str] = {}
    for service in state.services.values():
        project = _project_name_for_service(service)
        project_entry = projects.setdefault(project, {"backend_port": None, "frontend_port": None, "services": {}})
        port = service.actual_port if service.actual_port is not None else service.requested_port
        services = project_entry.setdefault("services", {})
        if isinstance(services, dict):
            services[str(service.type)] = _service_map_entry(service, port=port, host=host)
        if service.type == "backend":
            project_entry["backend_port"] = port
        elif service.type == "frontend":
            project_entry["frontend_port"] = port
        if port is not None:
            port_to_service[port] = service.name
            service_to_actual_port[service.name] = port
        public_url = _service_public_url(service, port=port, host=host)
        if public_url:
            service_to_url[service.name] = public_url
        health_url = str(getattr(service, "health_url", "") or "").strip()
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
        "service_to_health_url": service_to_health_url,
    }


def _service_map_entry(service: object, *, port: int | None, host: str) -> dict[str, object]:
    url = f"http://{host}:{port}" if port is not None and _service_projection_ready(service) else None
    public_url = str(getattr(service, "public_url", "") or "").strip() or None
    health_url = str(getattr(service, "health_url", "") or "").strip() or None
    return {
        "name": getattr(service, "name", ""),
        "type": getattr(service, "type", ""),
        "port": port,
        "url": url,
        "public_url": public_url,
        "health_url": health_url,
        "status": getattr(service, "status", "unknown"),
        "cwd": getattr(service, "cwd", ""),
        "log_path": getattr(service, "log_path", None),
        "listener_expected": bool(getattr(service, "listener_expected", True)),
    }


def _service_public_url(service: object, *, port: int | None, host: str) -> str | None:
    configured = str(getattr(service, "public_url", "") or "").strip()
    if configured:
        return configured
    if port is not None and _service_projection_ready(service):
        return f"http://{host}:{port}"
    return None


def _project_name_for_service(service: object) -> str:
    name = str(getattr(service, "name", "") or "").strip()
    service_type = str(getattr(service, "type", "") or "").strip()
    if service_type:
        display = " ".join(part.capitalize() for part in service_type.split("-") if part)
        suffix = f" {display}"
        if name.endswith(suffix):
            return name[: -len(suffix)].strip()
    for suffix in (" Backend", " Frontend"):
        if name.endswith(suffix):
            return name[: -len(suffix)].strip()
    return name


def _service_projection_ready(service: object | None) -> bool:
    if service is None:
        return False
    status = str(getattr(service, "status", "unknown")).strip().lower()
    return status in {"running", "healthy", "starting"}
