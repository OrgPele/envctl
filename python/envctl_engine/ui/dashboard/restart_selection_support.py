from __future__ import annotations

from typing import Any, Callable

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.shared.services import service_display_name, service_project_name
from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.selection_support import route_has_explicit_target


def apply_restart_selection(
    route: Route,
    state: RunState,
    runtime: Any,
    *,
    has_restartable_inactive_services_fn: Any,
    stop_dependencies_by_project_fn: Any,
    apply_restart_resource_selection_fn: Any,
    select_dashboard_projects_fn: Any,
    select_dashboard_service_types_fn: Any,
    service_names_for_projects_and_types_fn: Any,
    project_names_from_state_fn: Any,
    project_name_list_fn: Any,
    available_service_types_for_projects_fn: Any,
) -> Route | None:
    if route_has_explicit_target(route, runtime):
        if bool(route.flags.get("all")):
            route.flags = {**route.flags, "restart_include_requirements": True}
        else:
            route.flags = {**route.flags, "restart_include_requirements": False}
        return route
    if has_restartable_inactive_services_fn(state) or stop_dependencies_by_project_fn(state):
        return apply_restart_resource_selection_fn(route, state, runtime)
    projects = project_names_from_state_fn(state, runtime)
    selected_projects = select_dashboard_projects_fn(
        command="restart",
        state=state,
        projects=projects,
        runtime=runtime,
    )
    if selected_projects is None:
        print("No restart target selected.")
        return None
    route.projects = list(selected_projects)

    selected_service_types = select_dashboard_service_types_fn(
        command="restart",
        state=state,
        selected_projects=selected_projects,
        runtime=runtime,
    )
    if selected_service_types is None:
        print("No restart target selected.")
        return None
    selected_service_names = service_names_for_projects_and_types_fn(
        state,
        runtime,
        project_names=selected_projects,
        service_types=selected_service_types,
    )
    all_project_names = project_name_list_fn(projects)
    all_service_types = available_service_types_for_projects_fn(
        state,
        runtime,
        project_names=all_project_names,
    )
    include_requirements = set(selected_projects) == set(all_project_names) and set(selected_service_types) == set(
        all_service_types
    )
    route.flags = {
        **{
            key: value
            for key, value in route.flags.items()
            if key not in {"all", "services", "restart_service_types"}
        },
        "services": selected_service_names,
        "restart_service_types": list(selected_service_types),
        "restart_include_requirements": include_requirements,
    }
    return route


def apply_restart_resource_selection(
    route: Route,
    state: RunState,
    runtime: Any,
    *,
    restart_resource_items_fn: Any,
    apply_restart_resource_tokens_fn: Any,
    selector_fn: Callable[..., list[str] | None] | None = None,
) -> Route | None:
    items = restart_resource_items_fn(state, runtime)
    if not items:
        return route
    if selector_fn is None:
        from envctl_engine.ui.textual.screens.selector import _run_selector_with_impl as selector_fn
    values = selector_fn(
        prompt=(
            "Choose services/dependencies to restart or start "
            "(Space toggles, a selects all visible; Enter runs selected)"
        ),
        options=items,
        multi=True,
        emit=getattr(runtime, "_emit", None),
    )
    if values is None:
        print("No restart target selected.")
        return None
    tokens = [str(value).strip() for value in values if str(value).strip()]
    if not tokens:
        print("No restart target selected.")
        return None
    apply_restart_resource_tokens_fn(route, state, runtime, tokens)
    return route


def restart_resource_items(
    state: RunState,
    runtime: Any,
    *,
    restart_project_order_fn: Any,
    restart_services_by_project_fn: Any,
    stop_dependencies_by_project_fn: Any,
    stop_service_detail_fn: Any,
) -> list[SelectorItem]:
    project_order = restart_project_order_fn(state, runtime)
    many_projects = len(project_order) > 1
    service_lookup = restart_services_by_project_fn(state, runtime)
    dependency_lookup = stop_dependencies_by_project_fn(state)
    items: list[SelectorItem] = []

    for project_name in project_order:
        services = service_lookup.get(project_name, [])
        dependencies = dependency_lookup.get(project_name, [])
        if not services and not dependencies:
            continue
        section = f"▸ {project_name}" if many_projects else "Resources"
        scope = [
            *(f"service:{service_name}" for service_name, _service_type, _stopped in services),
            *(f"dependency:{project_name}:{dependency_id}" for dependency_id, _label in dependencies),
        ]
        if many_projects:
            items.append(
                SelectorItem(
                    id=f"restart:worktree:{project_name}",
                    label=f"▸ {project_name} — entire worktree (apps + dependencies)",
                    kind="worktree",
                    token=f"__RESTART__:worktree:{project_name}",
                    scope_signature=tuple(sorted(scope)) or (f"project:{project_name}",),
                    section=section,
                )
            )
        elif len(scope) > 1:
            items.append(
                SelectorItem(
                    id=f"restart:worktree:{project_name}",
                    label="All resources — apps + dependencies",
                    kind="worktree",
                    token=f"__RESTART__:worktree:{project_name}",
                    scope_signature=tuple(sorted(scope)) or (f"project:{project_name}",),
                    section=section,
                )
            )

        for service_name, service_type, stopped in services:
            label_prefix = "  ↳ " if many_projects else ""
            readable = service_display_name(service_type)
            detail = service_name if many_projects else stop_service_detail_fn(service_name, service_type)
            label = f"{label_prefix}{readable}"
            if detail:
                label = f"{label} — {detail}"
            if stopped:
                label = f"{label} (stopped)"
            items.append(
                SelectorItem(
                    id=f"restart:service:{service_name}",
                    label=label,
                    kind="service",
                    token=f"__RESTART__:service:{service_name}",
                    scope_signature=(f"service:{service_name}",),
                    section=section,
                )
            )

        for dependency_id, dependency_label in dependencies:
            label_prefix = "  ↳ " if many_projects else ""
            items.append(
                SelectorItem(
                    id=f"restart:dependency:{project_name}:{dependency_id}",
                    label=f"{label_prefix}{dependency_label}",
                    kind="dependency",
                    token=f"__RESTART__:dependency:{project_name}:{dependency_id}",
                    scope_signature=(f"dependency:{project_name}:{dependency_id}",),
                    section=section,
                )
            )
    return items


def apply_restart_resource_tokens(route: Route, state: RunState, runtime: Any, values: list[str]) -> None:
    from envctl_engine.ui.dashboard.stop_scope_support import stop_dependencies_by_project
    service_lookup = restart_services_by_project(state, runtime)
    dependency_lookup = stop_dependencies_by_project(state)
    service_type_by_name = {
        service_name: service_type
        for services in service_lookup.values()
        for service_name, service_type, _stopped in services
    }
    project_by_service = {
        service_name: project_name
        for project_name, services in service_lookup.items()
        for service_name, _service_type, _stopped in services
    }
    selected_services: set[str] = set()
    selected_dependencies: set[tuple[str, str]] = set()
    selected_projects: set[str] = set()

    for token in values:
        if token.startswith("__RESTART__:worktree:"):
            project_name = token.removeprefix("__RESTART__:worktree:")
            selected_projects.add(project_name)
            for service_name, _service_type, _stopped in service_lookup.get(project_name, []):
                selected_services.add(service_name)
            for dependency_id, _label in dependency_lookup.get(project_name, []):
                selected_dependencies.add((project_name, dependency_id))
            continue
        if token.startswith("__RESTART__:service:"):
            service_name = token.removeprefix("__RESTART__:service:")
            if service_name in service_type_by_name:
                selected_services.add(service_name)
                project_name = project_by_service.get(service_name)
                if project_name:
                    selected_projects.add(project_name)
            continue
        if token.startswith("__RESTART__:dependency:"):
            _, _, project_name, dependency_id = token.split(":", 3)
            if any(dependency_id == existing_id for existing_id, _label in dependency_lookup.get(project_name, [])):
                selected_dependencies.add((project_name, dependency_id))
                selected_projects.add(project_name)

    if selected_dependencies:
        selected_projects.update(project_name for project_name, _dependency_id in selected_dependencies)

    selected_service_types = sorted({service_type_by_name[name] for name in selected_services})
    selected_service_names = sorted(selected_services)
    flags = {
        key: value
        for key, value in route.flags.items()
        if key not in {"all", "services", "restart_service_types", "restart_include_requirements"}
    }
    flags["services"] = selected_service_names
    flags["restart_service_types"] = selected_service_types
    flags["restart_include_requirements"] = bool(selected_dependencies)
    route.flags = flags
    route.projects = sorted(selected_projects)


def has_dashboard_stopped_services(state: RunState, *, dashboard_stopped_services_by_project_fn: Any) -> bool:
    return bool(dashboard_stopped_services_by_project_fn(state))


def has_restartable_inactive_services(
    state: RunState,
    *,
    dashboard_stopped_services_by_project_fn: Any,
    dashboard_configured_missing_services_by_project_fn: Any,
) -> bool:
    if dashboard_stopped_services_by_project_fn(state):
        return True
    return bool(dashboard_configured_missing_services_by_project_fn(state))


def restart_project_order(
    state: RunState,
    runtime: Any,
    *,
    stop_project_order_fn: Any,
    dashboard_stopped_services_by_project_fn: Any,
    dashboard_project_configured_services_fn: Any,
) -> list[str]:
    names = stop_project_order_fn(state, runtime)
    seen = {name.casefold() for name in names}
    for project_name in (
        *dashboard_stopped_services_by_project_fn(state),
        *dashboard_project_configured_services_fn(state),
    ):
        if project_name.casefold() in seen:
            continue
        seen.add(project_name.casefold())
        names.append(project_name)
    return names


def restart_services_by_project(state: RunState, runtime: Any) -> dict[str, list[tuple[str, str, bool]]]:
    from envctl_engine.dashboard_metadata import DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY
    from envctl_engine.ui.dashboard.stop_scope_support import stop_service_type
    services_by_project: dict[str, list[tuple[str, str, bool]]] = {}
    for service_name, service in state.services.items():
        project_name = service_project_name(service)
        if not project_name:
            project_name = str(runtime._project_name_from_service(service_name) or "").strip()
        if not project_name:
            project_name = "Services"
        service_type = stop_service_type(service_name, service)
        if not service_type:
            continue
        services_by_project.setdefault(project_name, []).append((service_name, service_type, False))
    active_names = set(state.services)
    stopped = dashboard_stopped_services_by_project(state)
    for project_name, services in stopped.items():
        for service_type, service_name in services.items():
            if service_name in active_names:
                continue
            services_by_project.setdefault(project_name, []).append((service_name, service_type, True))
    configured_missing_services = dashboard_configured_missing_services_by_project(state)
    for project_name, service_types in configured_missing_services.items():
        existing = {
            service_name
            for service_name, _service_type, _stopped in services_by_project.get(project_name, [])
        }
        for service_type in service_types:
            service_name = f"{project_name} {service_display_name(service_type)}"
            if service_name in active_names or service_name in existing:
                continue
            services_by_project.setdefault(project_name, []).append((service_name, service_type, True))
    if any(configured_missing_services.values()):
        emit = getattr(runtime, "_emit", None)
        if callable(emit):
            emit(
                "dashboard.restart.configured_missing_offered",
                run_id=state.run_id,
                services={
                    project: sorted(service_types)
                    for project, service_types in configured_missing_services.items()
                },
                metadata_key=DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY,
            )
    for services in services_by_project.values():
        services.sort(key=lambda item: (0 if item[1] == "backend" else 1, item[2], item[0].casefold()))
    return services_by_project


def dashboard_stopped_services_by_project(state: RunState) -> dict[str, dict[str, str]]:
    from envctl_engine.dashboard_metadata import normalize_dashboard_service_types

    metadata = state.metadata if isinstance(state.metadata, dict) else {}
    raw_stopped = metadata.get("dashboard_stopped_services")
    stopped: dict[str, dict[str, str]] = {}
    if not isinstance(raw_stopped, list):
        return stopped
    for item in raw_stopped:
        if not isinstance(item, dict):
            continue
        project = str(item.get("project", "") or "").strip()
        normalized_types = normalize_dashboard_service_types([item.get("type", "")])
        service_type = normalized_types[0] if normalized_types else ""
        name = str(item.get("name", "") or "").strip()
        if not project or not service_type:
            continue
        stopped.setdefault(project, {})[service_type] = name or f"{project} {service_display_name(service_type)}"
    return stopped


def dashboard_project_configured_services(state: RunState) -> dict[str, set[str]]:
    from envctl_engine.dashboard_metadata import dashboard_project_configured_services_from_metadata
    return dashboard_project_configured_services_from_metadata(state.metadata)


def dashboard_configured_missing_services_by_project(
    state: RunState,
    *,
    configured_services: dict[str, set[str]] | None = None,
    stopped_services: dict[str, dict[str, str]] | None = None,
) -> dict[str, set[str]]:
    from envctl_engine.dashboard_metadata import dashboard_configured_missing_services_by_project as _missing
    return _missing(
        configured_services=configured_services or dashboard_project_configured_services(state),
        stopped_services=stopped_services or dashboard_stopped_services_by_project(state),
        active_service_names=set(state.services),
    )
