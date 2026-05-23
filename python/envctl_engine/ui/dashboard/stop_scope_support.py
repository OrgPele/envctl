from __future__ import annotations

from typing import Any, Callable

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.shared.services import (
    project_name_from_service_name,
    service_display_name,
    service_project_name,
    service_slug_from_record,
)
from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.selection_support import route_has_explicit_target


def apply_stop_scope_selection(
    route: Route,
    state: RunState,
    runtime: Any,
    *,
    stop_resource_items_fn: Any,
    apply_stop_resource_tokens_fn: Any,
    selector_fn: Callable[..., list[str] | None] | None = None,
) -> Route | None:
    if stop_route_has_explicit_scope(route, runtime):
        return route

    items = stop_resource_items_fn(state, runtime)
    if not items:
        return route

    if selector_fn is None:
        from envctl_engine.ui.textual.screens.selector import _run_selector_with_impl as selector_fn
    values = selector_fn(
        prompt="Choose services/dependencies to stop (Space toggles, a selects all visible; Enter stops selected)",
        options=items,
        multi=True,
        emit=getattr(runtime, "_emit", None),
    )
    if values is None:
        print("No stop scope selected.")
        return None
    values = [str(value).strip() for value in values if str(value).strip()]
    if not values:
        print("No stop scope selected.")
        return None

    apply_stop_resource_tokens_fn(route, state, runtime, values)
    return route


def stop_route_has_explicit_scope(route: Route, runtime: Any) -> bool:
    if str(route.flags.get("runtime_scope") or "").strip():
        return True
    return route_has_explicit_target(route, runtime)


def stop_resource_items(
    state: RunState,
    runtime: Any,
    *,
    project_names_from_state_fn: Any,
    stop_project_order_fn: Any,
    stop_services_by_project_fn: Any,
    stop_dependencies_by_project_fn: Any,
    stop_service_detail_fn: Any,
) -> list[SelectorItem]:
    project_order = stop_project_order_fn(state, runtime)
    many_projects = len(project_order) > 1
    service_lookup = stop_services_by_project_fn(state, runtime)
    dependency_lookup = stop_dependencies_by_project_fn(state)
    items: list[SelectorItem] = []

    for project_name in project_order:
        services = service_lookup.get(project_name, [])
        dependencies = dependency_lookup.get(project_name, [])
        if not services and not dependencies:
            continue
        section = f"▸ {project_name}" if many_projects else "Resources"
        scope = [
            *(f"service:{service_name}" for service_name, _service_type in services),
            *(f"dependency:{project_name}:{dependency_id}" for dependency_id, _label in dependencies),
        ]
        if many_projects:
            items.append(
                SelectorItem(
                    id=f"stop:worktree:{project_name}",
                    label=f"▸ {project_name} — entire worktree (apps + dependencies)",
                    kind="worktree",
                    token=f"__STOP__:worktree:{project_name}",
                    scope_signature=tuple(sorted(scope)) or (f"project:{project_name}",),
                    section=section,
                )
            )
        elif len(scope) > 1:
            items.append(
                SelectorItem(
                    id=f"stop:worktree:{project_name}",
                    label="All resources — apps + dependencies",
                    kind="worktree",
                    token=f"__STOP__:worktree:{project_name}",
                    scope_signature=tuple(sorted(scope)) or (f"project:{project_name}",),
                    section=section,
                )
            )

        for service_name, service_type in services:
            label_prefix = "  ↳ " if many_projects else ""
            readable = service_display_name(service_type)
            detail = service_name if many_projects else stop_service_detail_fn(service_name, service_type)
            label = f"{label_prefix}{readable}"
            if detail:
                label = f"{label} — {detail}"
            items.append(
                SelectorItem(
                    id=f"stop:service:{service_name}",
                    label=label,
                    kind="service",
                    token=f"__STOP__:service:{service_name}",
                    scope_signature=(f"service:{service_name}",),
                    section=section,
                )
            )

        for dependency_id, dependency_label in dependencies:
            label_prefix = "  ↳ " if many_projects else ""
            items.append(
                SelectorItem(
                    id=f"stop:dependency:{project_name}:{dependency_id}",
                    label=f"{label_prefix}{dependency_label}",
                    kind="dependency",
                    token=f"__STOP__:dependency:{project_name}:{dependency_id}",
                    scope_signature=(f"dependency:{project_name}:{dependency_id}",),
                    section=section,
                )
            )

    return items


def apply_stop_resource_tokens(route: Route, state: RunState, runtime: Any, values: list[str]) -> None:
    service_lookup = stop_services_by_project(state, runtime)
    dependency_lookup = stop_dependencies_by_project(state)
    selected_services: set[str] = set()
    selected_dependencies: set[tuple[str, str]] = set()

    for token in values:
        if token.startswith("__STOP__:worktree:"):
            project_name = token.removeprefix("__STOP__:worktree:")
            for service_name, _service_type in service_lookup.get(project_name, []):
                selected_services.add(service_name)
            for dependency_id, _label in dependency_lookup.get(project_name, []):
                selected_dependencies.add((project_name, dependency_id))
            continue
        if token.startswith("__STOP__:service:"):
            service_name = token.removeprefix("__STOP__:service:")
            selected_services.add(service_name)
            continue
        if token.startswith("__STOP__:dependency:"):
            _, _, project_name, dependency_id = token.split(":", 3)
            if any(dependency_id == existing_id for existing_id, _label in dependency_lookup.get(project_name, [])):
                selected_dependencies.add((project_name, dependency_id))

    all_services = set(state.services)
    all_dependencies = {
        (project_name, dependency_id)
        for project_name, dependencies in dependency_lookup.items()
        for dependency_id, _label in dependencies
    }

    flags = {
        key: value
        for key, value in route.flags.items()
        if key
        not in {
            "runtime_scope",
            "backend",
            "frontend",
            "services",
            "stop_dependency_components",
            "stop_preserve_requirements",
        }
    }
    if (
        selected_services
        and selected_services == all_services
        and selected_dependencies == all_dependencies
        and all_dependencies
    ):
        flags["runtime_scope"] = "entire-system"
    else:
        if selected_services:
            flags["services"] = sorted(selected_services)
            flags["stop_preserve_requirements"] = True
        if selected_dependencies:
            flags["stop_dependency_components"] = [
                f"{project_name}:{dependency_id}"
                for project_name, dependency_id in sorted(selected_dependencies)
            ]
            flags["stop_preserve_requirements"] = True
    route.flags = flags


def stop_project_order(state: RunState, runtime: Any, *, project_names_from_state_fn: Any) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for project in project_names_from_state_fn(state, runtime):
        name = str(getattr(project, "name", "")).strip()
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            names.append(name)
    for project_name in state.requirements:
        name = str(project_name).strip()
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            names.append(name)
    return names


def stop_services_by_project(state: RunState, runtime: Any) -> dict[str, list[tuple[str, str]]]:
    services_by_project: dict[str, list[tuple[str, str]]] = {}
    for service_name, service in state.services.items():
        project_name = service_project_name(service)
        if not project_name:
            project_name = str(runtime._project_name_from_service(service_name) or "").strip()
        if not project_name:
            project_name = str(project_name_from_service_name(str(service_name))).strip()
        if not project_name:
            project_name = "Services"
        service_type = stop_service_type(service_name, service)
        if not service_type:
            continue
        services_by_project.setdefault(project_name, []).append((service_name, service_type))
    for services in services_by_project.values():
        services.sort(key=lambda item: (0 if item[1] == "backend" else 1, item[0].casefold()))
    return services_by_project


def stop_dependencies_by_project(state: RunState) -> dict[str, list[tuple[str, str]]]:
    labels = {definition.id: definition.display_name for definition in dependency_definitions()}
    dependencies_by_project: dict[str, list[tuple[str, str]]] = {}
    for project_name, requirements in state.requirements.items():
        project = str(project_name).strip()
        if not project:
            continue
        for definition in dependency_definitions():
            component = requirements.component(definition.id)
            if not bool(component.get("enabled", False)):
                continue
            dependencies_by_project.setdefault(project, []).append(
                (definition.id, labels.get(definition.id, definition.display_name))
            )
    return dependencies_by_project


def stop_service_type(service_name: str, service: object) -> str:
    service_type = service_slug_from_record(service)
    if service_type:
        return service_type
    lowered_name = str(service_name).strip().lower()
    if lowered_name.endswith(" backend"):
        return "backend"
    if lowered_name.endswith(" frontend"):
        return "frontend"
    return ""


def stop_service_detail(service_name: str, service_type: str) -> str:
    trimmed = str(service_name).strip()
    suffix = f" {service_display_name(service_type)}"
    if trimmed.endswith(suffix):
        return trimmed[: -len(suffix)].strip()
    return trimmed
