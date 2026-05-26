from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Mapping

from envctl_engine.requirements.component_ports import component_resource_ports, dependency_display_port, positive_int
from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.runtime.browser_cors_diagnostics import cors_env_key, cors_projection_preview
from envctl_engine.runtime.browser_env_preview import redacted_env_value, safe_env_preview, source_alias_env
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.engine_runtime_env import service_env_overlays
from envctl_engine.startup.public_urls import browser_backend_url, resolve_public_host
from envctl_engine.state.models import PortPlan, RequirementsResult


def build_startup_env_projection(
    runtime: Any,
    route: Route,
    *,
    mode: str,
    contexts: list[object],
) -> dict[str, object]:
    projects: dict[str, object] = {}
    for context in contexts:
        requirements = requirements_preview(runtime, context=context, mode=mode, route=route)
        project = str(getattr(context, "name", "") or "")
        dependency_ports = dependency_ports_payload(requirements)
        services: dict[str, dict[str, object]] = {}
        for service_name in ("backend", "frontend"):
            if not bool(runtime.config.service_enabled_for_mode(mode, service_name)):
                continue
            base_env = runtime._project_service_env(
                context,
                requirements=requirements,
                route=route,
                service_name=service_name,
            )
            if service_name == "frontend":
                backend_port = context_port(context, "backend")
                if backend_port:
                    backend_url = browser_backend_url(
                        host=resolve_public_host(
                            env=getattr(runtime, "env", None),
                            config=getattr(runtime, "config", None),
                        ),
                        port=backend_port,
                    )
                    base_env["VITE_BACKEND_URL"] = backend_url
                    base_env["VITE_API_URL"] = f"{backend_url}/api/v1"
            if service_name == "backend":
                frontend_port = context_port(context, "frontend")
                cors = cors_projection_preview(runtime, frontend_port=frontend_port, backend_env=base_env)
                base_env.update(cors["env"])
            else:
                cors = None
            overlay_source = {
                **runtime._project_service_env_internal(context, requirements=requirements, route=route),
                **base_env,
            }
            overlays = service_env_overlays(runtime, service_name=service_name, base_env=overlay_source)
            final_env = {**base_env, **source_alias_env(overlay_source), **overlays}
            port = context_port(context, service_name) or 0
            services[service_name] = {
                "env": safe_env_preview(final_env, service_name=service_name),
                "env_overlays": {
                    key: redacted_env_value(key, value)
                    for key, value in sorted(overlays.items(), key=lambda item: item[0])
                },
                "command_source": command_source(runtime, service_name=service_name, context=context, port=port),
                "argv": command_argv(runtime, service_name=service_name, context=context, port=port),
            }
            if cors is not None:
                services[service_name]["cors"] = cors["diagnostics"]
        projects[project] = {
            "dependency_ports": dependency_ports,
            "services": services,
        }
    return {
        "contract_version": "envctl.env_projection.v1",
        "projects": projects,
    }


def dependency_ports_payload(requirements: RequirementsResult) -> dict[str, dict[str, int | None]]:
    payload: dict[str, dict[str, int | None]] = {}
    for definition in dependency_definitions():
        component = requirements.component(definition.id)
        resources = component_resource_ports(component)
        payload[definition.id] = {
            resource.name: positive_int(resources.get(resource.name))
            for resource in definition.resources
        }
        payload[definition.id]["primary"] = dependency_display_port(definition.id, component)
    return payload


def requirements_preview(runtime: Any, *, context: object, mode: str, route: Route) -> RequirementsResult:
    components: dict[str, dict[str, object]] = {}
    for definition in dependency_definitions():
        enabled = bool(runtime._requirement_enabled_for_mode(mode, definition.id, route=route))
        resources: dict[str, int] = {}
        for resource in definition.resources:
            plan = getattr(context, "ports", {}).get(resource.legacy_port_key)
            value = int(getattr(plan, "final", 0) or 0)
            if value <= 0:
                value = default_dependency_port(runtime, definition.id, resource.legacy_port_key)
            if value > 0:
                resources[resource.name] = value
        if resources:
            resources.setdefault("primary", next(iter(resources.values())))
        components[definition.id] = {
            "enabled": enabled,
            "success": enabled,
            "runtime_status": "healthy" if enabled else "disabled",
            "resources": resources,
            "final": resources.get("primary", 0),
        }
    return RequirementsResult(project=str(getattr(context, "name", "Main")), components=components, health="healthy")


def default_dependency_port(runtime: Any, dependency_id: str, legacy_port_key: str) -> int:
    config = getattr(runtime, "config", None)
    raw = getattr(config, "raw", {}) if config is not None else {}
    candidates: tuple[str, ...]
    if legacy_port_key == "supabase_api":
        candidates = ("SUPABASE_PUBLIC_PORT", "SUPABASE_API_PORT")
    elif legacy_port_key == "db":
        candidates = ("DB_PORT",)
    elif legacy_port_key == "redis":
        candidates = ("REDIS_PORT",)
    elif legacy_port_key == "n8n":
        candidates = ("N8N_PORT_BASE",)
    else:
        candidates = ()
    for key in candidates:
        if isinstance(raw, Mapping):
            value = positive_int(raw.get(key))
            if value:
                return value
    defaults = {
        "postgres": 5432,
        "redis": 6379,
        "supabase_api": 54321,
        "supabase": 5432,
        "n8n": 5678,
    }
    if legacy_port_key in defaults:
        return defaults[legacy_port_key]
    return defaults.get(dependency_id, 0)


def context_port(context: object, name: str) -> int | None:
    plan = getattr(context, "ports", {}).get(name)
    value = getattr(plan, "final", None)
    return int(value) if isinstance(value, int) and value > 0 else None


def command_source(runtime: Any, *, service_name: str, context: object, port: int) -> str | None:
    resolver = getattr(runtime, "_service_command_source", None)
    if not callable(resolver):
        return None
    try:
        result = resolver(service_name=service_name, project_root=getattr(context, "root"), port=port)
    except Exception:
        return None
    return result if isinstance(result, str) else None


def command_argv(runtime: Any, *, service_name: str, context: object, port: int) -> list[str]:
    resolver = getattr(runtime, "_service_start_command_resolved", None)
    if not callable(resolver):
        return []
    try:
        result = resolver(service_name=service_name, project_root=getattr(context, "root"), port=port)
    except Exception:
        return []
    if not isinstance(result, tuple) or len(result) < 1:
        return []
    argv = result[0]
    if not isinstance(argv, Sequence) or isinstance(argv, (str, bytes)):
        return []
    return [str(part) for part in argv]


def port_plan(project: str, port: int) -> PortPlan:
    return PortPlan(project=project, requested=port, assigned=port, final=port, source="explain")


_dependency_ports_payload = dependency_ports_payload
_requirements_preview = requirements_preview
_default_dependency_port = default_dependency_port
_context_port = context_port
_cors_projection_preview = cors_projection_preview
_cors_env_key = cors_env_key
_command_source = command_source
_command_argv = command_argv
