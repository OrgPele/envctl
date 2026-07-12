from __future__ import annotations

from collections.abc import Mapping
import inspect
from typing import Any

from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.state.models import RequirementsResult, RunState
from envctl_engine.state.project_runtime import (
    requirement_key_for_project as _requirement_key_for_project,
    requirement_keys_for_project as _requirement_keys_for_project,
)


def release_requirement_ports(runtime: Any, requirements: RequirementsResult) -> None:
    reservations: list[tuple[int, tuple[str, ...], str | None]] = []
    for definition in dependency_definitions():
        component = requirements.component(definition.id)
        if not bool(component.get("enabled", False)) or bool(component.get("external")):
            continue
        owners = requirement_component_port_owners(requirements, definition.id)
        expected_session = _port_lock_session(component.get("port_lock_session"))
        reservations.extend((port, owners, expected_session) for port in component_port_values(component))
    for port, owners, expected_session in sorted(reservations, key=lambda item: item[0]):
        release_port_reservation(
            runtime.port_planner,
            port,
            owner_candidates=owners,
            expected_session=expected_session,
        )


def release_requirement_component_port_values(
    port_planner: Any,
    component: Mapping[str, object],
    *,
    owner_candidates: tuple[str, ...],
) -> None:
    expected_session = _port_lock_session(component.get("port_lock_session"))
    for port in sorted(component_port_values(component)):
        release_port_reservation(
            port_planner,
            port,
            owner_candidates=owner_candidates,
            expected_session=expected_session,
        )


def release_port_reservation(
    port_planner: Any,
    port: int,
    *,
    owner_candidates: tuple[str, ...],
    expected_session: str | None,
) -> bool:
    """Release one persisted reservation without crossing planner sessions."""

    owners = tuple(dict.fromkeys(owner for owner in owner_candidates if owner))
    normalized_session = _port_lock_session(expected_session)
    release_owned = getattr(port_planner, "release_owned", None)
    if normalized_session and callable(release_owned):
        for owner in owners:
            if bool(release_owned(port, owner, expected_session=normalized_session)):
                return True

    # A legacy record has no session identity. Its only safe eager release is
    # through the current planner session, whose release method checks its own
    # session before unlinking. For a persisted session, use this fallback only
    # when that exact planner session is still active.
    current_session = _port_lock_session(getattr(port_planner, "session_id", None))
    if normalized_session is None or current_session == normalized_session:
        _release_current_session(port_planner, port, owners)

    # Reaping is the compatibility path for dead foreign sessions. It is
    # deliberately attempted only through the planner's liveness proof.
    reap_stale = getattr(port_planner, "reap_stale", None)
    if callable(reap_stale):
        if owners:
            for owner in owners:
                if bool(reap_stale(port, owner=owner)):
                    return True
        elif bool(reap_stale(port)):
            return True
    return False


def _release_current_session(port_planner: Any, port: int, owners: tuple[str, ...]) -> None:
    release = getattr(port_planner, "release", None)
    if not callable(release):
        return
    if not owners:
        release(port)
        return
    try:
        parameters = inspect.signature(release).parameters.values()
    except (TypeError, ValueError):
        return
    supports_owner = any(
        parameter.name == "owner" or parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters
    )
    if not supports_owner:
        # Minimal test doubles and legacy adapters may expose release(port).
        # Production PortPlanner always takes owner and enforces its session.
        release(port)
        return
    for owner in owners:
        release(port, owner=owner)


def _port_lock_session(value: object) -> str | None:
    normalized = value.strip() if isinstance(value, str) else ""
    return normalized or None


def requirement_component_port_owners(
    requirements: RequirementsResult,
    dependency_id: str,
) -> tuple[str, ...]:
    """Return every owner form used while reserving one dependency's ports."""

    project = str(requirements.project).strip()
    normalized_dependency = str(dependency_id).strip().lower()
    if not project or not normalized_dependency:
        return ()
    owner_suffixes = {"requirements"}
    for definition in dependency_definitions():
        if definition.id != normalized_dependency:
            continue
        owner_suffixes.update(resource.legacy_port_key for resource in definition.resources)
        break
    return tuple(f"{project}:{suffix}" for suffix in sorted(owner_suffixes))


def requirement_port_values(requirements: RequirementsResult) -> set[int]:
    ports: set[int] = set()
    for definition in dependency_definitions():
        component = requirements.component(definition.id)
        if not bool(component.get("enabled", False)):
            continue
        if bool(component.get("external")):
            continue
        ports.update(component_port_values(component))
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
    return _requirement_key_for_project(state, project_name)


def requirement_keys_for_project(state: RunState, project_name: str) -> list[str]:
    return _requirement_keys_for_project(state, project_name)
