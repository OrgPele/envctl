from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.state.models import RequirementsResult, RunState


def release_requirement_ports(runtime: Any, requirements: RequirementsResult) -> None:
    for port in sorted(requirement_port_values(requirements)):
        runtime.port_planner.release(port)


def requirement_port_values(requirements: RequirementsResult) -> set[int]:
    ports: set[int] = set()
    for definition in dependency_definitions():
        component = requirements.component(definition.id)
        if not bool(component.get("enabled", False)):
            continue
        if bool(component.get("external")):
            continue
        final = component.get("final")
        if isinstance(final, int) and final > 0:
            ports.add(final)
    return ports


def component_port_values(component: Mapping[str, object]) -> set[int]:
    ports: set[int] = set()
    final = component.get("final")
    if isinstance(final, int) and final > 0:
        ports.add(final)
    resources = component.get("resources")
    if isinstance(resources, Mapping):
        for value in resources.values():
            if isinstance(value, int) and value > 0:
                ports.add(value)
    return ports


def requirement_key_for_project(state: RunState, project_name: str) -> str | None:
    target = str(project_name).strip().lower()
    if not target:
        return None
    for key in state.requirements:
        if str(key).strip().lower() == target:
            return key
    return None
