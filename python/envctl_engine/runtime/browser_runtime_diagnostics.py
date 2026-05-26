from __future__ import annotations

from typing import Any, Mapping

from envctl_engine.requirements.component_ports import component_resource_ports, dependency_display_port, positive_int
from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.runtime.browser_cors_diagnostics import cors_payload, frontend_env_mismatch_warnings
from envctl_engine.runtime.browser_env_preview import safe_env_preview
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord


def launch_diagnostics_payload(
    *,
    project: str,
    service_name: str,
    env: Mapping[str, object],
    command_source: str | None,
    argv: list[str] | tuple[str, ...] | None,
    cors: Mapping[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "project": project,
        "service": service_name,
        "env": safe_env_preview(env, service_name=service_name),
        "command_source": command_source,
        "argv": [str(part) for part in (argv or [])],
    }
    if cors is not None:
        payload["cors"] = dict(cors)
    return payload


def build_runtime_diagnostics(
    state: RunState,
    *,
    env: Mapping[str, str] | None,
    config: Any | None,
    runtime: Any | None = None,
) -> dict[str, object]:
    projects = project_names(state, runtime=runtime)
    diagnostics: dict[str, object] = {}
    warnings: list[dict[str, object]] = []
    launch_by_project = launch_metadata(state)
    for project in projects:
        project_launch = launch_by_project.get(project, {})
        backend_service = service_for_project_type(state, project=project, service_type="backend", runtime=runtime)
        frontend_service = service_for_project_type(state, project=project, service_type="frontend", runtime=runtime)
        requirements = requirements_for_project(state, project)
        dependency_payload = dependency_payload_for_requirements(requirements, project_launch=project_launch)
        backend = service_payload(backend_service)
        frontend = service_payload(frontend_service)
        frontend_launch = project_launch.get("frontend") if isinstance(project_launch, dict) else None
        backend_launch = project_launch.get("backend") if isinstance(project_launch, dict) else None
        frontend_env = safe_launch_env(frontend_launch, service_name="frontend")
        backend_env = safe_launch_env(backend_launch, service_name="backend")
        backend["env"] = backend_env
        backend["cors"] = cors_payload(
            backend_launch=backend_launch,
            backend_env=backend_env,
            frontend_url=frontend.get("url"),
            config=config,
            env=env,
        )
        frontend["env"] = frontend_env
        diagnostics[project] = {
            "backend": backend,
            "frontend": frontend,
            "dependencies": dependency_payload,
        }
        warnings.extend(
            frontend_env_mismatch_warnings(
                project=project,
                frontend_env=frontend_env,
                backend_service=backend_service,
                supabase=dependency_payload.get("supabase") if isinstance(dependency_payload, dict) else None,
            )
        )
    return {"projects": diagnostics, "warnings": warnings}


def project_names(state: RunState, *, runtime: Any | None) -> list[str]:
    names: set[str] = set(state.requirements)
    roots = state.metadata.get("project_roots")
    if isinstance(roots, dict):
        names.update(str(name) for name in roots)
    for service_name, service in state.services.items():
        names.add(service_project_name(service_name, service, runtime=runtime))
    launch = launch_metadata(state)
    names.update(launch)
    return sorted(name for name in names if name)


def service_payload(service: ServiceRecord | None) -> dict[str, object]:
    if service is None:
        return {"status": "missing", "port": None, "url": None}
    port = service.actual_port if service.actual_port is not None else service.requested_port
    status = str(service.status or "unknown").strip().lower() or "unknown"
    return {
        "name": service.name,
        "status": status,
        "port": port,
        "url": f"http://localhost:{port}" if port else None,
        "public_url": service.public_url,
        "health_url": service.health_url,
    }


def dependency_payload_for_requirements(
    requirements: RequirementsResult | None,
    *,
    project_launch: Mapping[str, object] | None,
) -> dict[str, dict[str, object]]:
    payload: dict[str, dict[str, object]] = {}
    for definition in dependency_definitions():
        component = requirements.component(definition.id) if requirements is not None else {}
        enabled = bool(component.get("enabled", False))
        resources = component_resource_ports(component)
        entry: dict[str, object] = {
            "enabled": enabled,
            "status": str(component.get("runtime_status") or ("healthy" if component.get("success") else "unknown")),
            "port": dependency_display_port(definition.id, component),
            "resources": resources,
        }
        if definition.id == "supabase":
            api_port = positive_int(resources.get("api")) or dependency_display_port("supabase", component)
            external_url = str(component.get("external_url") or "").strip()
            entry["api_url"] = external_url or (f"http://localhost:{api_port}" if api_port else None)
            entry["anon_key_present"] = anon_key_present(project_launch)
        payload[definition.id] = entry
    return payload


def anon_key_present(project_launch: Mapping[str, object] | None) -> bool:
    if not isinstance(project_launch, Mapping):
        return False
    for service in ("frontend", "backend"):
        raw_service = project_launch.get(service)
        if not isinstance(raw_service, Mapping):
            continue
        raw_env = raw_service.get("env")
        if not isinstance(raw_env, Mapping):
            continue
        for key, value in raw_env.items():
            normalized = str(key).upper()
            if normalized.endswith("SUPABASE_ANON_KEY") and str(value):
                return True
    return False


def safe_launch_env(raw_launch: object, *, service_name: str) -> dict[str, str]:
    if not isinstance(raw_launch, Mapping):
        return {}
    raw_env = raw_launch.get("env")
    if not isinstance(raw_env, Mapping):
        return {}
    return safe_env_preview(raw_env, service_name=service_name)


def requirements_for_project(state: RunState, project: str) -> RequirementsResult | None:
    if project in state.requirements:
        return state.requirements[project]
    if len(state.requirements) == 1:
        return next(iter(state.requirements.values()))
    return None


def service_for_project_type(
    state: RunState,
    *,
    project: str,
    service_type: str,
    runtime: Any | None,
) -> ServiceRecord | None:
    for service_name, service in state.services.items():
        if service_project_name(service_name, service, runtime=runtime) != project:
            continue
        if str(service.type).strip().lower() == service_type:
            return service
    return None


def service_project_name(service_name: str, service: ServiceRecord, *, runtime: Any | None) -> str:
    explicit = str(getattr(service, "project", "") or "").strip()
    if explicit:
        return explicit
    if runtime is not None:
        resolver = getattr(runtime, "_project_name_from_service", None)
        if callable(resolver):
            try:
                resolved = str(resolver(service_name) or "").strip()
            except Exception:
                resolved = ""
            if resolved:
                return resolved
    prefix = service_name.rsplit(" ", 1)[0].strip()
    return prefix or "Main"


def launch_metadata(state: RunState) -> dict[str, dict[str, object]]:
    raw = state.metadata.get("runtime_launch_diagnostics")
    if not isinstance(raw, dict):
        return {}
    return {
        str(project): dict(payload)
        for project, payload in raw.items()
        if isinstance(payload, dict) and str(project).strip()
    }


_project_names = project_names
_service_payload = service_payload
_dependency_payload = dependency_payload_for_requirements
_anon_key_present = anon_key_present
_safe_launch_env = safe_launch_env
_requirements_for_project = requirements_for_project
_service_for_project_type = service_for_project_type
_service_project_name = service_project_name
_launch_metadata = launch_metadata
