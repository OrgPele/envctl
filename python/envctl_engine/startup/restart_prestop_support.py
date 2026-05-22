from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from envctl_engine.runtime.command_router import Route


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
