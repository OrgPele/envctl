from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from envctl_engine.shared.services import (
    project_name_from_service_name,
    service_display_name,
    service_project_name,
    service_slug_from_record,
)
from envctl_engine.state.models import RunState, ServiceRecord


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
    projects_raw = runtime_map["projects"]
    projects = projects_raw if isinstance(projects_raw, Mapping) else {}
    for project, ports_raw in projects.items():
        ports = ports_raw if isinstance(ports_raw, Mapping) else {}
        services_raw = ports.get("services")
        services = services_raw if isinstance(services_raw, Mapping) else {}
        backend_port, backend_url, backend_status = _projected_service_fields(services.get("backend"))
        frontend_port, frontend_url, frontend_status = _projected_service_fields(services.get("frontend"))
        projection[project] = {
            "backend_port": backend_port,
            "frontend_port": frontend_port,
            "backend_url": backend_url,
            "frontend_url": frontend_url,
            "backend_status": backend_status,
            "frontend_status": frontend_status,
            "services": services,
        }
    return projection


def build_runtime_map_without_projection(state: RunState, *, host: str = "localhost") -> dict[str, object]:
    projects: dict[str, dict[str, object]] = {}
    port_to_service: dict[int, str] = {}
    service_to_actual_port: dict[str, int] = {}
    service_to_url: dict[str, str] = {}
    service_to_public_url: dict[str, str] = {}
    service_to_health_url: dict[str, str] = {}

    grouped = _services_by_project_and_slug(state)
    reserved_service_keys_by_project: dict[str, set[str]] = {}
    for project, service_slug in grouped:
        reserved_service_keys_by_project.setdefault(project, set()).add(service_slug)

    for (project, service_slug), instances in sorted(
        grouped.items(),
        key=lambda item: (item[0][0].casefold(), item[0][1].casefold()),
    ):
        project_entry = projects.setdefault(project, {"backend_port": None, "frontend_port": None, "services": {}})
        services_entry = project_entry.setdefault("services", {})
        if not isinstance(services_entry, dict):
            continue

        ordered_instances = sorted(
            instances,
            key=lambda item: _service_authority_sort_key(project=project, service_slug=service_slug, item=item),
        )
        used_service_keys = set(services_entry)
        reserved_service_keys = reserved_service_keys_by_project.get(project, set())
        for index, (state_name, service) in enumerate(ordered_instances):
            projection_key = (
                service_slug
                if index == 0
                else _duplicate_service_projection_key(
                    service_slug=service_slug,
                    state_name=state_name,
                    used_keys=used_service_keys,
                    reserved_keys=reserved_service_keys,
                )
            )
            used_service_keys.add(projection_key)
            payload = _runtime_service_payload(
                service=service,
                service_slug=service_slug,
                host=host,
            )
            services_entry[projection_key] = payload
            if index == 0 and service_slug in {"backend", "frontend"}:
                project_entry[f"{service_slug}_port"] = payload["port"]

            port = payload["port"]
            url = payload["url"]
            public_url = payload["public_url"]
            health_url = payload["health_url"]
            if not isinstance(port, int):
                continue
            service_name = str(payload["name"] or "").strip() or state_name
            port_to_service.setdefault(port, service_name)
            service_to_actual_port[service_name] = port
            if url is not None:
                service_to_url[service_name] = str(url)
            if public_url:
                service_to_public_url[service_name] = str(public_url)
            if health_url:
                service_to_health_url[service_name] = str(health_url)
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


def _services_by_project_and_slug(
    state: RunState,
) -> dict[tuple[str, str], list[tuple[str, ServiceRecord]]]:
    grouped: dict[tuple[str, str], list[tuple[str, ServiceRecord]]] = {}
    for state_name, service in state.services.items():
        project = str(getattr(service, "project", "") or "").strip() or _project_name_from_service_record(service)
        service_slug = service_slug_from_record(service) or "service"
        grouped.setdefault((project, service_slug), []).append((state_name, service))
    return grouped


def _service_authority_sort_key(
    *,
    project: str,
    service_slug: str,
    item: tuple[str, ServiceRecord],
) -> tuple[object, ...]:
    state_name, service = item
    status = str(getattr(service, "status", "unknown") or "unknown").strip().lower()
    status_priority = {
        "healthy": 0,
        "running": 1,
        "starting": 2,
        "unknown": 3,
        "stale": 4,
        "degraded": 5,
        "stopped": 6,
        "termination_failed": 7,
    }.get(status, 3)
    explicit_metadata_count = sum(
        bool(str(value or "").strip())
        for value in (getattr(service, "project", ""), getattr(service, "service_slug", ""))
    )
    canonical_name = f"{project} {service_display_name(service_slug)}".casefold()
    service_name = str(getattr(service, "name", "") or "").strip()
    actual_port = getattr(service, "actual_port", None)
    return (
        status == "termination_failed",
        not _service_projection_ready(service),
        status_priority,
        -explicit_metadata_count,
        bool(getattr(service, "degraded", False)),
        service_name.casefold() != canonical_name,
        not isinstance(actual_port, int) or actual_port <= 0,
        service_name.casefold(),
        service_name,
        state_name.casefold(),
        state_name,
        int(getattr(service, "pid", 0) or 0),
    )


def _duplicate_service_projection_key(
    *,
    service_slug: str,
    state_name: str,
    used_keys: set[str],
    reserved_keys: set[str],
) -> str:
    base = f"{service_slug}@{state_name}"
    candidate = base
    index = 2
    while candidate in used_keys or candidate in reserved_keys:
        candidate = f"{base}#{index}"
        index += 1
    return candidate


def _runtime_service_payload(
    *,
    service: ServiceRecord,
    service_slug: str,
    host: str,
) -> dict[str, object]:
    port = service.actual_port if service.actual_port is not None else service.requested_port
    url = f"http://{host}:{port}" if port is not None and _service_projection_ready(service) else None
    public_url = str(getattr(service, "public_url", "") or "").strip() or url
    health_url = str(getattr(service, "health_url", "") or "").strip() or None
    return {
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
        "runtime_kind": getattr(service, "runtime_kind", "process"),
        "container_id": getattr(service, "container_id", None),
        "container_name": getattr(service, "container_name", None),
        "container_image": getattr(service, "container_image", None),
        "container_launch_token": getattr(service, "container_launch_token", None),
        "container_cleanup_pending_since": getattr(
            service,
            "container_cleanup_pending_since",
            None,
        ),
    }


def _projected_service_fields(raw: object) -> tuple[int | None, str | None, str]:
    if not isinstance(raw, Mapping):
        return None, None, "unknown"
    port_raw = raw.get("port")
    port = port_raw if isinstance(port_raw, int) else None
    url_raw = raw.get("url")
    url = str(url_raw) if isinstance(url_raw, str) and url_raw else None
    status = str(raw.get("status", "unknown") or "unknown")
    return port, url, status


def _service_projection_ready(service: object | None) -> bool:
    if service is None:
        return False
    status = str(getattr(service, "status", "unknown")).strip().lower()
    return status in {"running", "healthy", "starting"}


def _project_name_from_service_record(service: object) -> str:
    resolved_project = service_project_name(service)
    if resolved_project:
        return resolved_project
    name = str(getattr(service, "name", "") or "").strip()
    service_type = str(getattr(service, "type", "") or "").strip().lower()
    display_suffix = service_display_name(service_type)
    if display_suffix and name.endswith(f" {display_suffix}"):
        return name[: -(len(display_suffix) + 1)]
    return project_name_from_service_name(name)
