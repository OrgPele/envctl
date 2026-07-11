from __future__ import annotations

from collections.abc import Callable, Iterable

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.lifecycle_dependency_stop import select_dependency_components_for_stop
from envctl_engine.shared.services import service_matches_selector
from envctl_engine.state.models import RunState


def select_services_for_stop(
    state: RunState,
    route: Route,
    *,
    project_name_from_service_fn: Callable[[str], str],
    selectors_from_passthrough_fn: Callable[[list[str]], Iterable[str]],
    interactive_stop_selection_fn: Callable[[Route, RunState], object | None],
    services_from_selection_fn: Callable[[object, RunState], set[str]],
) -> set[str]:
    if route.command != "stop":
        return set(state.services.keys())
    if bool(route.flags.get("all")):
        return set(state.services.keys())

    selected, has_selectors = _selected_services_from_route(
        state,
        route,
        project_name_from_service_fn=project_name_from_service_fn,
        selectors_from_passthrough_fn=selectors_from_passthrough_fn,
    )

    runtime_scope = route.flags.get("runtime_scope")
    if runtime_scope in {"backend", "frontend"}:
        scoped = {
            name
            for name, service in state.services.items()
            if service_matches_runtime_scope(name, service, str(runtime_scope))
        }
        return scoped.intersection(selected) if has_selectors else scoped
    if runtime_scope in {"fullstack", "entire-system"}:
        return selected if has_selectors else set(state.services.keys())
    if runtime_scope == "dependencies":
        return set()

    if not selected and has_selectors:
        return set()
    if not selected and select_dependency_components_for_stop(state, route):
        return set()
    if not selected:
        selection = interactive_stop_selection_fn(route, state)
        if selection is not None:
            if bool(getattr(selection, "cancelled", False)):
                return set()
            selected = services_from_selection_fn(selection, state)
    if not selected:
        return set(state.services.keys())
    return selected


def service_matches_runtime_scope(name: str, service: object, runtime_scope: str) -> bool:
    service_type = str(getattr(service, "type", "") or "").strip().lower()
    if service_type == runtime_scope:
        return True
    lowered_name = str(name).strip().lower()
    return lowered_name.endswith(f" {runtime_scope}")


def _selected_services_from_route(
    state: RunState,
    route: Route,
    *,
    project_name_from_service_fn: Callable[[str], str],
    selectors_from_passthrough_fn: Callable[[list[str]], Iterable[str]],
) -> tuple[set[str], bool]:
    selected: set[str] = set()
    has_selectors = False
    services_flag = route.flags.get("services")
    if isinstance(services_flag, list):
        has_selectors = has_selectors or bool(services_flag)
        selected.update(_services_matching_service_selectors(state, services_flag))

    project_names = _project_selectors(route, selectors_from_passthrough_fn=selectors_from_passthrough_fn)
    has_selectors = has_selectors or bool(project_names)
    if project_names:
        selected.update(
            _services_matching_project_selectors(
                state,
                project_names,
                project_name_from_service_fn=project_name_from_service_fn,
            )
        )

    return selected, has_selectors


def _services_matching_service_selectors(state: RunState, services_flag: list[object]) -> set[str]:
    selected: set[str] = set()
    for raw in services_flag:
        target = str(raw).strip().lower()
        if not target:
            continue
        for name, service in state.services.items():
            if name.lower() == target or service_matches_selector(service, target):
                selected.add(name)
    return selected


def _project_selectors(
    route: Route,
    *,
    selectors_from_passthrough_fn: Callable[[list[str]], Iterable[str]],
) -> set[str]:
    project_names = {name.lower() for name in route.projects}
    project_names.update(str(name).strip().lower() for name in selectors_from_passthrough_fn(route.passthrough_args))
    project_names.discard("")
    return project_names


def _services_matching_project_selectors(
    state: RunState,
    project_names: set[str],
    *,
    project_name_from_service_fn: Callable[[str], str],
) -> set[str]:
    selected: set[str] = set()
    for name in state.services:
        project = project_name_from_service_fn(name).lower()
        if project and project in project_names:
            selected.add(name)
    return selected
