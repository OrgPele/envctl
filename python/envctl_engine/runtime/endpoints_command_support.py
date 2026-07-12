from __future__ import annotations

import json
from typing import Any, Mapping

from envctl_engine.requirements.component_ports import component_resource_ports, dependency_display_port, positive_int
from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.public_urls import resolve_public_host
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.state.project_runtime import (
    active_project_names,
    dependency_mode_summary,
    project_resolution_event_payload,
    project_root_for_state,
    resolve_requested_project_state,
)
from envctl_engine.shared.services import service_project_name


def run_endpoints_command(runtime: Any, route: Route) -> int:
    state = _load_state(runtime, route)
    json_output = bool(getattr(route, "flags", {}).get("json"))
    if state is None:
        payload = {"ok": False, "error": "state_not_found", "mode": getattr(route, "mode", None)}
        return _emit_payload(payload, json_output=json_output, ok=False)
    active = active_project_names(state, runtime=runtime)
    requested = list(getattr(route, "projects", []) or [])
    if not requested and len(active) != 1:
        payload = {"ok": False, "error": "project_required", "active_projects": active}
        return _emit_payload(payload, json_output=json_output, ok=False)
    resolution = resolve_requested_project_state(
        state,
        requested,
        command="endpoints",
        runtime=runtime,
        allow_multi=False,
    )
    if not resolution.ok:
        _emit_resolution(runtime, "state.project_resolution.failed", resolution, state)
        return _emit_payload(resolution.payload(), json_output=json_output, ok=False)
    _emit_resolution(runtime, "state.project_resolution.ok", resolution, state)
    project = resolution.selected_projects[0]
    payload = build_endpoints_payload(
        resolution.state or state,
        project=project,
        env=getattr(runtime, "env", {}),
        config=getattr(runtime, "config", None),
        runtime=runtime,
    )
    return _emit_payload(payload, json_output=json_output, ok=bool(payload.get("ok")))


def build_endpoints_payload(
    state: RunState,
    *,
    project: str,
    env: Mapping[str, str] | None,
    config: Any | None,
    runtime: Any | None = None,
) -> dict[str, object]:
    public_host = resolve_public_host(env=env, config=config)
    backend = _service_endpoint(
        state,
        project=project,
        service_type="backend",
        public_host=public_host,
        runtime=runtime,
    )
    frontend = _service_endpoint(
        state,
        project=project,
        service_type="frontend",
        public_host=public_host,
        runtime=runtime,
    )
    additional_services = {
        str(service.name): _service_endpoint(
            state,
            project=project,
            service_type=str(service.name),
            public_host=public_host,
            runtime=runtime,
        )
        for service in getattr(config, "additional_services", ()) or ()
    }
    requirements = _requirements_for_project(state, project)
    dependency_summary = dependency_mode_summary(state)
    return {
        "ok": True,
        "run_id": state.run_id,
        "mode": state.mode,
        "project": project,
        "project_root": project_root_for_state(state, project, runtime=runtime),
        "dependency_mode": dependency_summary["dependency_mode"],
        "shared_dependencies": dependency_summary["shared_dependencies"],
        "frontend": frontend,
        "backend": backend,
        "additional_services": additional_services,
        "dependencies": _dependency_endpoints(requirements),
    }


def _service_endpoint(
    state: RunState,
    *,
    project: str,
    service_type: str,
    public_host: str,
    runtime: Any | None = None,
) -> dict[str, object]:
    service = _service_for_project_type(state, project=project, service_type=service_type, runtime=runtime)
    if service is None:
        stopped = _stopped_service_endpoint(state, project=project, service_type=service_type)
        if stopped is not None:
            return stopped
        return {"status": "missing", "port": None, "local_url": None, "public_url": None}
    port = service.actual_port if service.actual_port is not None else service.requested_port
    status = str(service.status or "unknown").strip().lower() or "unknown"
    ready = status in {"running", "healthy", "starting"} and port is not None
    local_url = f"http://localhost:{port}" if ready else None
    explicit_public = str(getattr(service, "public_url", "") or "").strip() or None
    public_url = explicit_public or (f"http://{public_host}:{port}" if ready else None)
    return {
        "name": service.name,
        "status": status,
        "port": port,
        "local_url": local_url,
        "public_url": public_url,
        "health_url": getattr(service, "health_url", None),
    }


def _stopped_service_endpoint(state: RunState, *, project: str, service_type: str) -> dict[str, object] | None:
    raw = state.metadata.get("dashboard_stopped_services")
    if not isinstance(raw, list):
        return None
    for item in raw:
        if not isinstance(item, dict):
            continue
        if str(item.get("project") or "").strip() != project:
            continue
        if str(item.get("type") or "").strip().lower() != service_type:
            continue
        return {
            "name": str(item.get("name") or "") or None,
            "status": "stopped",
            "port": None,
            "local_url": None,
            "public_url": None,
            "health_url": None,
            "reason": item.get("reason"),
            "stopped_at": item.get("stopped_at"),
        }
    return None


def _service_for_project_type(
    state: RunState,
    *,
    project: str,
    service_type: str,
    runtime: Any | None = None,
) -> ServiceRecord | None:
    for service_name, service in state.services.items():
        if _service_project_name(service_name, service, runtime=runtime) != project:
            continue
        if str(getattr(service, "type", "") or "").strip().lower() == service_type:
            return service
    return None


def _service_project_name(service_name: str, service: ServiceRecord, *, runtime: Any | None = None) -> str:
    explicit = str(getattr(service, "project", "") or "").strip()
    if explicit:
        return explicit
    if runtime is not None:
        resolver = getattr(runtime, "_project_name_from_service", None)
        if callable(resolver):
            try:
                resolved = str(resolver(str(service_name)) or "").strip()
            except Exception:
                resolved = ""
            if resolved:
                return resolved
    return service_project_name(service)


def _requirements_for_project(state: RunState, project: str) -> RequirementsResult | None:
    if project in state.requirements:
        return state.requirements[project]
    target = str(project).strip().casefold()
    for storage_key, requirements in state.requirements.items():
        if str(requirements.project or storage_key).strip().casefold() == target:
            return requirements
    if len(state.requirements) == 1:
        return next(iter(state.requirements.values()))
    return None


def _dependency_endpoints(requirements: RequirementsResult | None) -> dict[str, dict[str, object]]:
    endpoints: dict[str, dict[str, object]] = {}
    if requirements is None:
        for definition in dependency_definitions():
            endpoints[definition.id] = {"enabled": False, "status": "missing", "port": None}
        return endpoints
    for definition in dependency_definitions():
        component = requirements.component(definition.id)
        enabled = bool(component.get("enabled", False))
        status = str(component.get("runtime_status") or ("healthy" if component.get("success") else "unknown"))
        endpoints[definition.id] = {
            "enabled": enabled,
            "status": status,
            "port": dependency_display_port(definition.id, component),
            "resources": component_resource_ports(component),
        }
        external_url = str(component.get("external_url") or "").strip()
        if external_url:
            endpoints[definition.id]["url"] = external_url
    supabase = requirements.component("supabase")
    resources = component_resource_ports(supabase)
    if resources:
        endpoints["supabase_db"] = {
            "enabled": bool(supabase.get("enabled")),
            "status": str(supabase.get("runtime_status") or ("healthy" if supabase.get("success") else "unknown")),
            "port": positive_int(resources.get("db")) or positive_int(resources.get("primary")),
        }
        endpoints["supabase_api"] = {
            "enabled": bool(supabase.get("enabled")),
            "status": str(supabase.get("runtime_status") or ("healthy" if supabase.get("success") else "unknown")),
            "port": positive_int(resources.get("api")),
        }
    return endpoints


def _load_state(runtime: Any, route: Route) -> RunState | None:
    loader = getattr(runtime, "_try_load_existing_state", None)
    if not callable(loader):
        return None
    strict = False
    strict_resolver = getattr(runtime, "_state_lookup_strict_mode_match", None)
    if callable(strict_resolver):
        strict = bool(strict_resolver(route))
    state = loader(mode=getattr(route, "mode", None), strict_mode_match=strict)
    return state if isinstance(state, RunState) else None


def _emit_payload(payload: Mapping[str, object], *, json_output: bool, ok: bool) -> int:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif ok:
        print(_human_endpoints(payload))
    else:
        print(str(payload.get("error", "endpoints failed")))
    return 0 if ok else 1


def _human_endpoints(payload: Mapping[str, object]) -> str:
    lines = [f"project: {payload.get('project')}", f"run_id: {payload.get('run_id')}"]
    for label in ("frontend", "backend"):
        endpoint = payload.get(label)
        if isinstance(endpoint, dict):
            lines.append(f"{label}: {endpoint.get('public_url') or endpoint.get('local_url') or 'n/a'}")
    additional_services = payload.get("additional_services")
    if isinstance(additional_services, dict):
        for name, endpoint in sorted(additional_services.items()):
            if isinstance(endpoint, dict):
                lines.append(f"{name}: {endpoint.get('public_url') or endpoint.get('local_url') or 'n/a'}")
    return "\n".join(lines)


def _emit_resolution(runtime: Any, event: str, resolution: Any, state: RunState) -> None:
    emitter = getattr(runtime, "_emit", None)
    if not callable(emitter):
        return
    emitter(event, **project_resolution_event_payload(resolution, state, runtime=runtime))
