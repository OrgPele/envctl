from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.lifecycle_requirement_ports import component_port_values
from envctl_engine.state.models import RunState


def select_dependency_components_for_stop(state: RunState, route: Route) -> dict[str, set[str]]:
    if route.flags.get("runtime_scope") == "entire-system":
        requested_projects = {str(project).strip().casefold() for project in route.projects if str(project).strip()}
        return {
            project_name: {
                definition.id
                for definition in dependency_definitions()
                if bool(requirements.component(definition.id).get("enabled", False))
            }
            for project_name, requirements in state.requirements.items()
            if not requested_projects or str(project_name).strip().casefold() in requested_projects
        }
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
    stop_component_fn: Callable[[Mapping[str, object]], None] | None = None,
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
                if stop_component_fn is not None:
                    stop_component_fn(component)
                release_component_ports_fn(component)
            requirements.components[dependency_id] = {}
        if not requirements_have_enabled_components(requirements):
            state.requirements.pop(project_name, None)


def release_requirement_component_ports(
    component: Mapping[str, object],
    *,
    release_port_fn: Callable[[int], None],
) -> None:
    for port in sorted(component_port_values(component)):
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


def stop_requirement_component_containers(runtime: Any, component: Mapping[str, object]) -> None:
    if bool(component.get("external")) or bool(component.get("simulated")):
        return
    container_name = str(component.get("container_name") or "").strip()
    if not container_name:
        return
    process_runner = getattr(runtime, "process_runner", None)
    if process_runner is None:
        return
    if str(component.get("id") or "").strip().lower() == "supabase":
        listed = process_runner.run(
            [
                "docker",
                "ps",
                "--all",
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={container_name}",
            ],
            timeout=30.0,
        )
        if listed.returncode != 0:
            raise RuntimeError(str(listed.stderr or listed.stdout or "failed listing Supabase containers").strip())
        container_ids = [line.strip() for line in str(listed.stdout or "").splitlines() if line.strip()]
        if container_ids:
            removed = process_runner.run(["docker", "rm", "--force", *container_ids], timeout=60.0)
            if removed.returncode != 0:
                detail = removed.stderr or removed.stdout or "failed stopping Supabase containers"
                raise RuntimeError(str(detail).strip())
            return
        # Native Supabase DB startup records the concrete container name and
        # does not attach a Compose project label. Fall through to direct
        # removal when the saved component is not a Compose stack.
    removed = process_runner.run(["docker", "rm", "--force", container_name], timeout=30.0)
    if removed.returncode != 0 and "No such container" not in str(removed.stderr or ""):
        raise RuntimeError(str(removed.stderr or removed.stdout or f"failed stopping {container_name}").strip())
