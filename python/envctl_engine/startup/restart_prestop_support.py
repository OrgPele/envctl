from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.services import service_project_name, service_slug_from_record


@dataclass(frozen=True, slots=True)
class RestartPrestopPreservation:
    preserved_services: dict[str, object]
    preserved_requirements: dict[str, object]
    requirements_to_release: dict[str, object]


def restart_fallback_start_route(route: Route, *, restart_lookup_mode: str) -> Route:
    return Route(
        command="start",
        mode=restart_lookup_mode,
        raw_args=route.raw_args,
        passthrough_args=route.passthrough_args,
        projects=route.projects,
        flags={**route.flags, "_restart_request": True},
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
