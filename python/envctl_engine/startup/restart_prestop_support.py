from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.services import service_project_name, service_slug_from_record
from envctl_engine.startup.startup_selection_support import (
    _restart_selected_services,
    restart_include_requirements,
    restart_target_projects,
    restart_target_projects_for_selected_services,
)


@dataclass(frozen=True, slots=True)
class RestartPrestopPreservation:
    preserved_services: dict[str, object]
    preserved_requirements: dict[str, object]
    requirements_to_release: dict[str, object]


@dataclass(frozen=True, slots=True)
class RestartPrestopState:
    restart_lookup_mode: str
    state: object | None
    fallback_route: Route | None


@dataclass(frozen=True, slots=True)
class RestartPrestopSelection:
    selected_services: set[str]
    target_projects: set[str]
    include_requirements: bool


@dataclass(frozen=True, slots=True)
class RestartOrphanListenerScan:
    ports_by_type: dict[str, set[int]]
    selected_by_cwd: dict[str, set[str]]


@dataclass(frozen=True, slots=True)
class RestartOrphanListenerMatch:
    pid: int
    port: int


def restart_fallback_start_route(route: Route, *, restart_lookup_mode: str) -> Route:
    return Route(
        command="start",
        mode=restart_lookup_mode,
        raw_args=route.raw_args,
        passthrough_args=route.passthrough_args,
        projects=route.projects,
        flags={**route.flags, "_restart_request": True},
    )


def restart_prestop_state(*, route: Route, runtime: Any) -> RestartPrestopState:
    restart_lookup_mode = runtime._effective_start_mode(route)
    resumed = runtime._try_load_existing_state(mode=restart_lookup_mode)
    if resumed is not None and resumed.mode != restart_lookup_mode:
        runtime._emit(
            "restart.state_mode_mismatch",
            requested_mode=restart_lookup_mode,
            loaded_mode=resumed.mode,
            run_id=resumed.run_id,
        )
        resumed = None
    fallback_route = None
    if resumed is None:
        fallback_route = restart_fallback_start_route(route, restart_lookup_mode=restart_lookup_mode)
    return RestartPrestopState(
        restart_lookup_mode=restart_lookup_mode,
        state=resumed,
        fallback_route=fallback_route,
    )


def restart_start_route(
    route: Route,
    *,
    restart_lookup_mode: str,
    selected_services: set[str],
    target_projects: set[str],
    include_requirements: bool,
) -> Route:
    return Route(
        command="start",
        mode=restart_lookup_mode,
        raw_args=route.raw_args,
        passthrough_args=route.passthrough_args,
        projects=route.projects,
        flags={
            **route.flags,
            "_restart_request": True,
            "_restart_selected_services": sorted(selected_services),
            "_restart_target_projects": sorted(target_projects),
            "_restart_include_requirements": include_requirements,
        },
    )


def restart_prestop_selection(*, state: Any, route: Route, runtime: Any) -> RestartPrestopSelection:
    selected_services = _restart_selected_services(state=state, route=route)
    target_projects = restart_target_projects(state=state, route=route, runtime=runtime)
    include_requirements = restart_include_requirements(route)
    if include_requirements and not target_projects:
        target_projects = restart_target_projects_for_selected_services(
            selected_services=selected_services,
            state=state,
            runtime=runtime,
        )
    return RestartPrestopSelection(
        selected_services=selected_services,
        target_projects=target_projects,
        include_requirements=include_requirements,
    )


def restart_prestop_preservation(
    state: Any,
    *,
    selected_services: set[str],
    include_requirements: bool,
    target_projects: set[str],
) -> RestartPrestopPreservation:
    requirements_to_release: dict[str, object] = {}
    preserved_requirements: dict[str, object] = {}
    for project_name, requirements in getattr(state, "requirements", {}).items():
        if include_requirements and (not target_projects or project_name in target_projects):
            requirements_to_release[project_name] = requirements
        else:
            preserved_requirements[project_name] = requirements
    preserved_services = {
        name: service for name, service in getattr(state, "services", {}).items() if name not in selected_services
    }
    return RestartPrestopPreservation(
        preserved_services=preserved_services,
        preserved_requirements=preserved_requirements,
        requirements_to_release=requirements_to_release,
    )


def restart_port_assignments(
    state: Any,
    *,
    selected_services: set[str],
    project_name_from_service: Callable[[str], str],
) -> dict[str, dict[str, int]]:
    by_project: dict[str, dict[str, int]] = {}
    for service_name, service in getattr(state, "services", {}).items():
        if service_name not in selected_services:
            continue
        project_name = service_project_name(service) or project_name_from_service(service_name)
        service_type = service_slug_from_record(service)
        if not project_name or not service_type:
            continue
        port = getattr(service, "actual_port", None)
        if not isinstance(port, int) or port <= 0:
            port = getattr(service, "requested_port", None)
        if isinstance(port, int) and port > 0:
            by_project.setdefault(project_name.lower(), {})[service_type] = port
    return by_project


def apply_restart_port_assignments(
    contexts: Iterable[Any],
    assignments: dict[str, dict[str, int]],
    *,
    set_plan_port: Callable[[Any, int], None],
) -> None:
    for context in contexts:
        ports = assignments.get(str(getattr(context, "name", "")).strip().lower())
        if not ports:
            continue
        context_ports = getattr(context, "ports", {})
        for service_type, port in ports.items():
            plan = context_ports.get(service_type)
            if plan is None:
                continue
            set_plan_port(plan, port)
            plan.source = "restart"


def restart_orphan_listener_scan(
    state: Any,
    *,
    selected_services: set[str],
    backend_port_base: int,
    frontend_port_base: int,
    port_spacing: int,
) -> RestartOrphanListenerScan:
    span = max(int(port_spacing or 20), 1)
    ports_by_type: dict[str, set[int]] = {
        "backend": set(range(int(backend_port_base), int(backend_port_base) + span)),
        "frontend": set(range(int(frontend_port_base), int(frontend_port_base) + span)),
    }
    selected_by_cwd: dict[str, set[str]] = {}
    for service_name, service in getattr(state, "services", {}).items():
        if service_name not in selected_services:
            continue
        service_type = str(getattr(service, "type", "") or "").strip().lower()
        cwd = str(getattr(service, "cwd", "") or "").strip()
        if service_type not in ports_by_type or not cwd:
            continue
        selected_by_cwd.setdefault(cwd, set()).add(service_type)
        for attr_name in ("actual_port", "requested_port"):
            port = getattr(service, attr_name, None)
            if isinstance(port, int) and port > 0:
                ports_by_type[service_type].update(range(max(1, port - span), port + span + 1))
    return RestartOrphanListenerScan(
        ports_by_type=ports_by_type,
        selected_by_cwd=selected_by_cwd,
    )


def restart_matching_orphan_listeners(
    scan: RestartOrphanListenerScan,
    *,
    listener_pids_for_port: Callable[[int], Iterable[int]],
    process_cwd: Callable[[int], str | None],
) -> list[RestartOrphanListenerMatch]:
    matches: list[RestartOrphanListenerMatch] = []
    seen_pids: set[int] = set()
    for cwd, service_types in scan.selected_by_cwd.items():
        for service_type in service_types:
            for port in sorted(scan.ports_by_type.get(service_type, set())):
                for pid in listener_pids_for_port(port):
                    if pid in seen_pids or pid <= 0:
                        continue
                    if process_cwd(pid) != cwd:
                        continue
                    seen_pids.add(pid)
                    matches.append(RestartOrphanListenerMatch(pid=pid, port=port))
    return matches
