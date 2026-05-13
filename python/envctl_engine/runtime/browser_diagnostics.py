from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlparse

from envctl_engine.requirements.component_ports import component_resource_ports, dependency_display_port, positive_int
from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.engine_runtime_env import service_env_overlays
from envctl_engine.startup.public_urls import browser_backend_url, resolve_public_host
from envctl_engine.state.models import PortPlan, RequirementsResult, RunState, ServiceRecord


_SAFE_BACKEND_ENV_KEYS = {
    "FRONTEND_BASE_URL",
    "ENVCTL_SOURCE_FRONTEND_URL",
    "CORS_ORIGINS_RAW",
}


def safe_env_preview(env: Mapping[str, object], *, service_name: str) -> dict[str, str]:
    preview: dict[str, str] = {}
    normalized_service = str(service_name).strip().lower()
    for key, value in sorted(env.items(), key=lambda item: str(item[0])):
        name = str(key).strip()
        if not name:
            continue
        if normalized_service == "frontend":
            allowed = name.startswith("VITE_") or name.startswith("ENVCTL_SOURCE_")
        else:
            allowed = name in _SAFE_BACKEND_ENV_KEYS or name.startswith("ENVCTL_SOURCE_")
        if not allowed:
            continue
        if _is_secret_key(name) and not name.startswith("VITE_"):
            continue
        preview[name] = _redacted_env_value(name, value)
    return preview


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
    projects = _project_names(state, runtime=runtime)
    diagnostics: dict[str, object] = {}
    warnings: list[dict[str, object]] = []
    launch_metadata = _launch_metadata(state)
    for project in projects:
        project_launch = launch_metadata.get(project, {})
        backend_service = _service_for_project_type(state, project=project, service_type="backend", runtime=runtime)
        frontend_service = _service_for_project_type(state, project=project, service_type="frontend", runtime=runtime)
        requirements = _requirements_for_project(state, project)
        dependency_payload = _dependency_payload(requirements, project_launch=project_launch)
        backend = _service_payload(backend_service)
        frontend = _service_payload(frontend_service)
        frontend_launch = project_launch.get("frontend") if isinstance(project_launch, dict) else None
        backend_launch = project_launch.get("backend") if isinstance(project_launch, dict) else None
        frontend_env = _safe_launch_env(frontend_launch, service_name="frontend")
        backend_env = _safe_launch_env(backend_launch, service_name="backend")
        backend["env"] = backend_env
        backend["cors"] = _cors_payload(
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
            _frontend_env_mismatch_warnings(
                project=project,
                frontend_env=frontend_env,
                backend_service=backend_service,
                supabase=dependency_payload.get("supabase") if isinstance(dependency_payload, dict) else None,
            )
        )
    return {"projects": diagnostics, "warnings": warnings}


def build_startup_env_projection(
    runtime: Any,
    route: Route,
    *,
    mode: str,
    contexts: list[object],
) -> dict[str, object]:
    projects: dict[str, object] = {}
    for context in contexts:
        requirements = _requirements_preview(runtime, context=context, mode=mode, route=route)
        project = str(getattr(context, "name", "") or "")
        dependency_ports = _dependency_ports_payload(requirements)
        services: dict[str, object] = {}
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
                backend_port = _context_port(context, "backend")
                if backend_port:
                    backend_url = browser_backend_url(
                        host=resolve_public_host(env=getattr(runtime, "env", None), config=getattr(runtime, "config", None)),
                        port=backend_port,
                    )
                    base_env["VITE_BACKEND_URL"] = backend_url
                    base_env["VITE_API_URL"] = f"{backend_url}/api/v1"
            if service_name == "backend":
                frontend_port = _context_port(context, "frontend")
                cors = _cors_projection_preview(runtime, frontend_port=frontend_port, backend_env=base_env)
                base_env.update(cors["env"])
            else:
                cors = None
            overlay_source = {
                **runtime._project_service_env_internal(context, requirements=requirements, route=route),
                **base_env,
            }
            overlays = service_env_overlays(runtime, service_name=service_name, base_env=overlay_source)
            final_env = {**base_env, **_source_alias_env(overlay_source), **overlays}
            port = _context_port(context, service_name) or 0
            services[service_name] = {
                "env": safe_env_preview(final_env, service_name=service_name),
                "env_overlays": {
                    key: _redacted_env_value(key, value)
                    for key, value in sorted(overlays.items(), key=lambda item: item[0])
                },
                "command_source": _command_source(runtime, service_name=service_name, context=context, port=port),
                "argv": _command_argv(runtime, service_name=service_name, context=context, port=port),
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


def _redacted_env_value(key: str, value: object) -> str:
    if _is_secret_key(key):
        return "<redacted>"
    return str(value)


def _is_secret_key(key: str) -> bool:
    upper = key.upper()
    if upper.startswith("ENVCTL_SOURCE_"):
        upper = upper[len("ENVCTL_SOURCE_") :]
    return any(token in upper for token in ("PASSWORD", "SECRET", "SERVICE_ROLE", "JWT", "TOKEN", "KEY"))


def _source_alias_env(env: Mapping[str, object]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for key, value in env.items():
        name = str(key).strip()
        if not name or name.startswith("ENVCTL_SOURCE_"):
            continue
        if not name.replace("_", "").isalnum() or name[0].isdigit():
            continue
        text = str(value)
        if text:
            aliases[f"ENVCTL_SOURCE_{name}"] = text
    return aliases


def _project_names(state: RunState, *, runtime: Any | None) -> list[str]:
    names: set[str] = set(state.requirements)
    roots = state.metadata.get("project_roots")
    if isinstance(roots, dict):
        names.update(str(name) for name in roots)
    for service_name, service in state.services.items():
        names.add(_service_project_name(service_name, service, runtime=runtime))
    launch = _launch_metadata(state)
    names.update(launch)
    return sorted(name for name in names if name)


def _service_payload(service: ServiceRecord | None) -> dict[str, object]:
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


def _dependency_payload(
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
            entry["api_url"] = f"http://localhost:{api_port}" if api_port else None
            entry["anon_key_present"] = _anon_key_present(project_launch)
        payload[definition.id] = entry
    return payload


def _anon_key_present(project_launch: Mapping[str, object] | None) -> bool:
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


def _safe_launch_env(raw_launch: object, *, service_name: str) -> dict[str, str]:
    if not isinstance(raw_launch, Mapping):
        return {}
    raw_env = raw_launch.get("env")
    if not isinstance(raw_env, Mapping):
        return {}
    return safe_env_preview(raw_env, service_name=service_name)


def _cors_payload(
    *,
    backend_launch: object,
    backend_env: Mapping[str, str],
    frontend_url: object,
    config: Any | None,
    env: Mapping[str, str] | None,
) -> dict[str, object]:
    if isinstance(backend_launch, Mapping) and isinstance(backend_launch.get("cors"), Mapping):
        cors = dict(backend_launch["cors"])  # type: ignore[index]
        origins = cors.get("origins")
        if not isinstance(origins, list):
            env_key = str(cors.get("env_key") or _cors_env_key(config=config, env=env))
            origins = [token.strip() for token in str(backend_env.get(env_key, "")).split(",") if token.strip()]
            cors["origins"] = origins
        return cors
    env_key = _cors_env_key(config=config, env=env)
    origins = [token.strip() for token in str(backend_env.get(env_key, "")).split(",") if token.strip()]
    return {
        "projected": bool(frontend_url and str(frontend_url) in origins),
        "env_key": env_key,
        "frontend_origin": frontend_url,
        "origins": origins,
        "effective_input": backend_env.get(env_key),
    }


def _frontend_env_mismatch_warnings(
    *,
    project: str,
    frontend_env: Mapping[str, str],
    backend_service: ServiceRecord | None,
    supabase: object,
) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    backend_port = backend_service.actual_port if backend_service is not None else None
    if backend_port:
        api_port = _url_port(str(frontend_env.get("VITE_API_URL") or frontend_env.get("VITE_BACKEND_URL") or ""))
        if api_port is not None and api_port != int(backend_port):
            warnings.append(
                {
                    "code": "frontend_env_backend_port_mismatch",
                    "project": project,
                    "env_key": "VITE_API_URL",
                    "expected_port": int(backend_port),
                    "actual_port": api_port,
                    "message": (
                        f"{project} frontend VITE_API_URL points at port {api_port}, "
                        f"but active backend is on port {backend_port}."
                    ),
                }
            )
    if isinstance(supabase, Mapping):
        expected = _url_port(str(supabase.get("api_url") or ""))
        actual = _url_port(str(frontend_env.get("VITE_SUPABASE_URL") or ""))
        if expected is not None and actual is not None and expected != actual:
            warnings.append(
                {
                    "code": "frontend_env_supabase_port_mismatch",
                    "project": project,
                    "env_key": "VITE_SUPABASE_URL",
                    "expected_port": expected,
                    "actual_port": actual,
                    "message": (
                        f"{project} frontend VITE_SUPABASE_URL points at port {actual}, "
                        f"but active Supabase API is on port {expected}."
                    ),
                }
            )
    return warnings


def _url_port(value: str) -> int | None:
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    return parsed.port


def _requirements_for_project(state: RunState, project: str) -> RequirementsResult | None:
    if project in state.requirements:
        return state.requirements[project]
    if len(state.requirements) == 1:
        return next(iter(state.requirements.values()))
    return None


def _service_for_project_type(
    state: RunState,
    *,
    project: str,
    service_type: str,
    runtime: Any | None,
) -> ServiceRecord | None:
    for service_name, service in state.services.items():
        if _service_project_name(service_name, service, runtime=runtime) != project:
            continue
        if str(service.type).strip().lower() == service_type:
            return service
    return None


def _service_project_name(service_name: str, service: ServiceRecord, *, runtime: Any | None) -> str:
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


def _launch_metadata(state: RunState) -> dict[str, dict[str, object]]:
    raw = state.metadata.get("runtime_launch_diagnostics")
    if not isinstance(raw, dict):
        return {}
    return {
        str(project): dict(payload)
        for project, payload in raw.items()
        if isinstance(payload, dict) and str(project).strip()
    }


def _dependency_ports_payload(requirements: RequirementsResult) -> dict[str, dict[str, int | None]]:
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


def _requirements_preview(runtime: Any, *, context: object, mode: str, route: Route) -> RequirementsResult:
    components: dict[str, dict[str, object]] = {}
    for definition in dependency_definitions():
        enabled = bool(runtime._requirement_enabled_for_mode(mode, definition.id, route=route))
        resources: dict[str, int] = {}
        for resource in definition.resources:
            plan = getattr(context, "ports", {}).get(resource.legacy_port_key)
            value = int(getattr(plan, "final", 0) or 0)
            if value <= 0:
                value = _default_dependency_port(runtime, definition.id, resource.legacy_port_key)
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


def _default_dependency_port(runtime: Any, dependency_id: str, legacy_port_key: str) -> int:
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


def _context_port(context: object, name: str) -> int | None:
    plan = getattr(context, "ports", {}).get(name)
    value = getattr(plan, "final", None)
    return int(value) if isinstance(value, int) and value > 0 else None


def _cors_projection_preview(runtime: Any, *, frontend_port: int | None, backend_env: Mapping[str, str]) -> dict[str, object]:
    env_key = _cors_env_key(config=getattr(runtime, "config", None), env=getattr(runtime, "env", None))
    if not frontend_port:
        return {"env": {}, "diagnostics": {"projected": False, "env_key": env_key, "origins": []}}
    host = resolve_public_host(env=getattr(runtime, "env", None), config=getattr(runtime, "config", None))
    origins = _merge_cors_origins(str(backend_env.get(env_key, "") or ""), frontend_port=frontend_port, host=host)
    frontend_origin = f"http://{host}:{frontend_port}"
    return {
        "env": {
            "FRONTEND_BASE_URL": frontend_origin,
            "ENVCTL_SOURCE_FRONTEND_URL": frontend_origin,
            env_key: ",".join(origins),
        },
        "diagnostics": {
            "projected": True,
            "env_key": env_key,
            "frontend_origin": frontend_origin,
            "origins": origins,
            "effective_input": ",".join(origins),
        },
    }


def _cors_env_key(*, config: Any | None, env: Mapping[str, str] | None) -> str:
    config_raw = getattr(config, "raw", {}) if config is not None else {}
    raw = ""
    if isinstance(env, Mapping):
        raw = str(env.get("ENVCTL_BACKEND_CORS_ENV_KEY") or "")
    if not raw and isinstance(config_raw, Mapping):
        raw = str(config_raw.get("ENVCTL_BACKEND_CORS_ENV_KEY") or "")
    return raw.strip() or "CORS_ORIGINS_RAW"


def _command_source(runtime: Any, *, service_name: str, context: object, port: int) -> str | None:
    resolver = getattr(runtime, "_service_command_source", None)
    if not callable(resolver):
        return None
    try:
        return resolver(service_name=service_name, project_root=getattr(context, "root"), port=port)
    except Exception:
        return None


def _command_argv(runtime: Any, *, service_name: str, context: object, port: int) -> list[str]:
    resolver = getattr(runtime, "_service_start_command_resolved", None)
    if not callable(resolver):
        return []
    try:
        argv, _source = resolver(service_name=service_name, project_root=getattr(context, "root"), port=port)
    except Exception:
        return []
    return [str(part) for part in argv]


def port_plan(project: str, port: int) -> PortPlan:
    return PortPlan(project=project, requested=port, assigned=port, final=port, source="explain")


def _merge_cors_origins(existing: str, *, frontend_port: int, host: str) -> list[str]:
    origins: list[str] = []

    def add(value: str) -> None:
        normalized = value.strip()
        if normalized and normalized not in origins:
            origins.append(normalized)

    for token in existing.replace(";", ",").split(","):
        add(token)
    add(f"http://{host}:{frontend_port}")
    if host in {"localhost", "127.0.0.1"}:
        add(f"http://localhost:{frontend_port}")
        add(f"http://127.0.0.1:{frontend_port}")
    return origins
