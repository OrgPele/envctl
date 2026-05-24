from __future__ import annotations

from pathlib import Path

from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.parsing import parse_bool
from envctl_engine.startup.protocols import StartupOrchestratorLike
from envctl_engine.startup.public_urls import resolve_public_host


def resolve_command_env_builder(rt: object):
    builder = getattr(rt, "_command_env", None)
    if callable(builder):
        return builder

    def build_command_env(*, port: int, extra: dict[str, str] | None = None) -> dict[str, str]:
        _ = port
        return dict(extra or {})

    return build_command_env


def ordered_service_layers(
    selected_service_types: list[str] | tuple[str, ...],
    additional_services: tuple[object, ...],
) -> list[tuple[str, ...]]:
    selected = [str(service).strip().lower() for service in selected_service_types if str(service).strip()]
    selected_set = set(selected)
    service_by_name = {str(getattr(service, "name", "")).strip().lower(): service for service in additional_services}
    order_index = {"backend": 0, "frontend": 1}
    for service in additional_services:
        name = str(getattr(service, "name", "")).strip().lower()
        order_index[name] = int(getattr(service, "start_order", 100) or 100) + 10
    dependencies: dict[str, set[str]] = {name: set() for name in selected}
    for name in selected:
        service = service_by_name.get(name)
        if service is None:
            continue
        for dependency in tuple(getattr(service, "depends_on", ()) or ()):
            normalized = str(dependency).strip().lower()
            if normalized in selected_set and normalized in service_by_name:
                dependencies[name].add(normalized)

    layers: list[tuple[str, ...]] = []
    remaining = set(selected)
    resolved: set[str] = set()
    while remaining:
        ready = sorted(
            (name for name in remaining if dependencies.get(name, set()) <= resolved),
            key=lambda name: (order_index.get(name, 1000), name),
        )
        if not ready:
            cycle_nodes = sorted(remaining)
            raise RuntimeError("additional service dependency cycle: " + " -> ".join(cycle_nodes))
        layers.append(tuple(ready))
        resolved.update(ready)
        remaining.difference_update(ready)
    return layers


def service_attach_parallel_enabled(
    orchestrator: StartupOrchestratorLike, *, route: Route | None, selected_service_types: set[str]
) -> bool:
    if not selected_service_types:
        return False
    if route is not None:
        route_value = route.flags.get("service_parallel")
        if isinstance(route_value, bool):
            return route_value
    rt = orchestrator.runtime
    raw = rt.env.get("ENVCTL_SERVICE_ATTACH_PARALLEL") or rt.config.raw.get("ENVCTL_SERVICE_ATTACH_PARALLEL")
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def service_prep_parallel_enabled(
    orchestrator: StartupOrchestratorLike,
    *,
    route: Route | None,
    selected_service_types: set[str],
    attach_parallel: bool,
) -> bool:
    if selected_service_types - {"backend", "frontend"}:
        return False
    if route is not None:
        route_value = route.flags.get("service_prep_parallel")
        if isinstance(route_value, bool):
            return route_value
    rt = orchestrator.runtime
    raw = rt.env.get("ENVCTL_SERVICE_PREP_PARALLEL") or rt.config.raw.get("ENVCTL_SERVICE_PREP_PARALLEL")
    if str(raw).strip():
        return parse_bool(raw, True)
    return attach_parallel


def backend_listener_expected_for_mode(config: object, mode: str) -> bool:
    helper = getattr(config, "backend_expects_listener_for_mode", None)
    if callable(helper):
        return bool(helper(mode))
    normalized = str(mode).strip().lower()
    if normalized == "trees":
        return bool(getattr(config, "trees_backend_expect_listener", True))
    return bool(getattr(config, "main_backend_expect_listener", True))


def _project_backend_cors_origin(
    rt: object,
    *,
    project: str,
    backend_env: dict[str, str],
    frontend_port: int,
) -> None:
    if frontend_port <= 0:
        return
    runtime_env = getattr(rt, "env", {})
    config_raw = getattr(getattr(rt, "config", None), "raw", {})
    raw_enabled = str(
        runtime_env.get(
            "ENVCTL_BACKEND_CORS_PROJECTION_ENABLE",
            config_raw.get("ENVCTL_BACKEND_CORS_PROJECTION_ENABLE", "true"),
        )
    ).strip().lower()
    if raw_enabled in {"0", "false", "no", "off"}:
        return
    host = resolve_public_host(env=runtime_env, config=getattr(rt, "config", None))
    frontend_url = f"http://{host}:{frontend_port}"
    backend_env["FRONTEND_BASE_URL"] = frontend_url
    backend_env["ENVCTL_SOURCE_FRONTEND_URL"] = frontend_url
    cors_key = str(
        runtime_env.get(
            "ENVCTL_BACKEND_CORS_ENV_KEY",
            config_raw.get("ENVCTL_BACKEND_CORS_ENV_KEY", "CORS_ORIGINS_RAW"),
        )
        or "CORS_ORIGINS_RAW"
    ).strip()
    if not cors_key:
        return
    origins = _merge_cors_origins(str(backend_env.get(cors_key, "") or ""), frontend_port=frontend_port, host=host)
    backend_env[cors_key] = ",".join(origins)
    emit = getattr(rt, "_emit", None)
    if callable(emit):
        emit(
            "backend.cors.projected",
            project=project,
            env_key=cors_key,
            frontend_origin=frontend_url,
            origin_count=len(origins),
        )


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


def additional_service_enabled_for_context(service: object, *, mode: str, project_root: Path) -> bool:
    enabled_for_project = getattr(service, "enabled_for_project_root", None)
    if callable(enabled_for_project):
        return bool(enabled_for_project(mode, project_root))
    enabled_for_mode = getattr(service, "enabled_for_mode", None)
    if callable(enabled_for_mode):
        return bool(enabled_for_mode(mode))
    return False
