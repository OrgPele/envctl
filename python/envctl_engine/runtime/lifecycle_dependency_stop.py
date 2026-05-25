from __future__ import annotations

from collections.abc import Callable, Mapping

from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState


def select_dependency_components_for_stop(state: RunState, route: Route) -> dict[str, set[str]]:
    raw_components = route.flags.get("stop_dependency_components")
    if not isinstance(raw_components, list):
        return {}

    known_definitions = {definition.id for definition in dependency_definitions()}
    selected: dict[str, set[str]] = {}
    project_key_by_lower = {str(project).strip().casefold(): project for project in state.requirements}
    for raw in raw_components:
        project_name, separator, dependency_id = str(raw).partition(":")
        if not separator:
            continue
        project_key = project_key_by_lower.get(project_name.strip().casefold())
        if project_key is None:
            continue
        normalized_dependency = dependency_id.strip().lower()
        if normalized_dependency not in known_definitions:
            continue
        component = state.requirements[project_key].component(normalized_dependency)
        if not bool(component.get("enabled", False)):
            continue
        selected.setdefault(project_key, set()).add(normalized_dependency)
    return selected


def release_selected_dependency_components(
    state: RunState,
    selected_dependencies: dict[str, set[str]],
    *,
    release_component_ports_fn: Callable[[Mapping[str, object]], None],
) -> None:
    for project_name, dependency_ids in selected_dependencies.items():
        requirements = state.requirements.get(project_name)
        if requirements is None:
            continue
        for dependency_id in dependency_ids:
            component = requirements.component(dependency_id)
            if not bool(component.get("enabled", False)):
                continue
            if not bool(component.get("external")):
                release_component_ports_fn(component)
            requirements.components[dependency_id] = {}
        if not requirements_have_enabled_components(requirements):
            state.requirements.pop(project_name, None)


def release_requirement_component_ports(
    component: Mapping[str, object],
    *,
    release_port_fn: Callable[[int], None],
) -> None:
    ports: set[int] = set()
    final = component.get("final")
    if isinstance(final, int) and final > 0:
        ports.add(final)
    resources = component.get("resources")
    if isinstance(resources, Mapping):
        for value in resources.values():
            if isinstance(value, int) and value > 0:
                ports.add(value)
    for port in sorted(ports):
        release_port_fn(port)


def requirements_have_enabled_components(requirements: object) -> bool:
    components = getattr(requirements, "components", {})
    if not isinstance(components, Mapping):
        return False
    return any(
        bool(component.get("enabled", False))
        for component in components.values()
        if isinstance(component, Mapping)
    )
