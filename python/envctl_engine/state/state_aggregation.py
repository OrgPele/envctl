from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from envctl_engine.dashboard_metadata import DASHBOARD_STOPPED_SERVICES_KEY
from envctl_engine.state.fingerprints import text_fingerprint
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.state.project_runtime import (
    PROJECT_SCOPED_METADATA_MAP_KEYS,
    filter_project_scoped_metadata,
)
from envctl_engine.state.run_index import RunIndexCandidate


ServiceProjectResolver = Callable[[str, ServiceRecord], str]
ProjectNamesResolver = Callable[[RunState], Sequence[str]]
SourceRunIdsResolver = Callable[[RunState], Sequence[str]]


@dataclass(frozen=True, slots=True)
class IndexedState:
    candidate: RunIndexCandidate
    state: RunState


def normalized_project_names(project_names: Sequence[str]) -> frozenset[str]:
    return frozenset(str(name).strip().casefold() for name in project_names if str(name).strip())


def select_indexed_owners(
    indexed_states: Sequence[IndexedState],
    *,
    selected_projects: Sequence[str],
    service_project_name: ServiceProjectResolver,
) -> list[IndexedState]:
    if not indexed_states:
        return []
    owner_by_project: dict[str, str] = {}
    for indexed_state in indexed_states:
        for project_name in indexed_state.candidate.project_names:
            owner_by_project.setdefault(project_name, indexed_state.candidate.run_id)
    if not owner_by_project and not normalized_project_names(selected_projects):
        return [indexed_states[0]]

    requested = normalized_project_names(selected_projects) or frozenset(owner_by_project)
    chosen_run_ids = {owner_by_project[project_name] for project_name in requested if project_name in owner_by_project}
    if not chosen_run_ids:
        return []

    chosen_states: list[IndexedState] = []
    for indexed_state in indexed_states:
        run_id = indexed_state.candidate.run_id
        if run_id not in chosen_run_ids:
            continue
        owned_projects = frozenset(
            project_name for project_name, owner_run_id in owner_by_project.items() if owner_run_id == run_id
        )
        candidate_projects = normalized_project_names(indexed_state.candidate.project_names)
        filtered = filter_state_to_owned_projects(
            indexed_state.state,
            owned_projects,
            service_project_name=service_project_name,
            fallback_project=(
                next(iter(owned_projects))
                if len(owned_projects) == 1 and len(candidate_projects) == 1
                else None
            ),
        )
        chosen_states.append(IndexedState(candidate=indexed_state.candidate, state=filtered))
    return chosen_states


def state_from_indexed_owners(
    chosen_states: Sequence[IndexedState],
    *,
    project_names_from_state: ProjectNamesResolver,
    source_run_ids: SourceRunIdsResolver,
) -> RunState | None:
    if not chosen_states:
        return None
    if len(chosen_states) == 1:
        chosen = chosen_states[0]
        if normalized_project_names(chosen.candidate.project_names) == normalized_project_names(
            project_names_from_state(chosen.state)
        ):
            return chosen.state
    return merge_indexed_states(
        chosen_states,
        project_names_from_state=project_names_from_state,
        source_run_ids=source_run_ids,
    )


def filter_state_to_owned_projects(
    state: RunState,
    indexed_projects: frozenset[str],
    *,
    service_project_name: ServiceProjectResolver,
    fallback_project: str | None = None,
) -> RunState:
    if not indexed_projects:
        return state

    fallback_key = str(fallback_project or "").strip().casefold()
    fallback_display = _owned_project_display_name(state, fallback_key) if fallback_key else ""
    known_project_keys = _known_state_project_keys(state).union(indexed_projects)
    services: dict[str, ServiceRecord] = {}
    ambiguous_services: list[str] = []
    for name, service in state.services.items():
        resolved_project = service_project_name(name, service).strip()
        if resolved_project and resolved_project.casefold() not in known_project_keys:
            resolved_project = ""
        if not resolved_project:
            resolved_project = _service_project_from_cwd_roots(
                state,
                service,
            )
        if not resolved_project and fallback_key:
            resolved_project = fallback_display or fallback_key
            service = replace(service, project=resolved_project)
        elif resolved_project and not str(getattr(service, "project", "") or "").strip():
            service = replace(service, project=resolved_project)
        if not resolved_project:
            ambiguous_services.append(name)
            continue
        if resolved_project.casefold() in indexed_projects:
            services[name] = service
    if ambiguous_services:
        raise RuntimeError(
            "Cannot safely determine project ownership for service(s): "
            + ", ".join(sorted(ambiguous_services))
            + "; candidate projects: "
            + ", ".join(sorted(indexed_projects))
        )
    requirements = {
        name: requirement
        for name, requirement in state.requirements.items()
        if str(getattr(requirement, "project", "") or name).strip().casefold() in indexed_projects
        or (
            state.mode == "trees"
            and str(getattr(requirement, "project", "") or name).strip().casefold() == "main"
            and bool(state.metadata.get("shared_dependencies"))
        )
    }
    metadata = filter_project_scoped_metadata(
        state.metadata,
        indexed_projects,
        case_sensitive=False,
    )
    metadata["project_names"] = _display_project_names(
        state,
        indexed_projects=indexed_projects,
        service_project_name=service_project_name,
    )
    filter_startup_identity_projects(metadata, indexed_projects)
    return RunState(
        run_id=state.run_id,
        mode=state.mode,
        schema_version=state.schema_version,
        backend_mode=state.backend_mode,
        services=services,
        requirements=requirements,
        pointers=dict(state.pointers),
        metadata=metadata,
    )


def _owned_project_display_name(state: RunState, project_key: str) -> str:
    if not project_key:
        return ""
    metadata_names = state.metadata.get("project_names")
    if isinstance(metadata_names, Sequence) and not isinstance(metadata_names, (str, bytes)):
        for name in metadata_names:
            rendered = str(name).strip()
            if rendered.casefold() == project_key:
                return rendered
    for storage_key, requirements in state.requirements.items():
        rendered = str(getattr(requirements, "project", "") or storage_key).strip()
        if rendered.casefold() == project_key:
            return rendered
    return project_key


def _known_state_project_keys(state: RunState) -> set[str]:
    projects: set[str] = set()
    metadata_names = state.metadata.get("project_names")
    if isinstance(metadata_names, Sequence) and not isinstance(metadata_names, (str, bytes)):
        projects.update(str(name).strip().casefold() for name in metadata_names if str(name).strip())
    metadata_roots = state.metadata.get("project_roots")
    if isinstance(metadata_roots, Mapping):
        projects.update(str(name).strip().casefold() for name in metadata_roots if str(name).strip())
    projects.update(
        str(getattr(requirements, "project", "") or storage_key).strip().casefold()
        for storage_key, requirements in state.requirements.items()
        if str(getattr(requirements, "project", "") or storage_key).strip()
    )
    return projects


def _service_project_from_cwd_roots(
    state: RunState,
    service: ServiceRecord,
) -> str:
    cwd = str(getattr(service, "cwd", "") or "").strip()
    roots = state.metadata.get("project_roots")
    if not cwd or not isinstance(roots, Mapping):
        return ""
    try:
        cwd_path = Path(cwd).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return ""
    matches: list[str] = []
    for project, root in roots.items():
        project_name = str(project).strip()
        if not project_name:
            continue
        try:
            root_path = Path(str(root)).expanduser().resolve(strict=False)
            cwd_path.relative_to(root_path)
        except (OSError, RuntimeError, ValueError):
            continue
        matches.append(project_name)
    return matches[0] if len(matches) == 1 else ""


def _display_project_names(
    state: RunState,
    *,
    indexed_projects: frozenset[str],
    service_project_name: ServiceProjectResolver,
) -> list[str]:
    display_by_key: dict[str, str] = {}

    def add(raw_name: object) -> None:
        name = str(raw_name or "").strip()
        key = name.casefold()
        if name and key in indexed_projects:
            display_by_key.setdefault(key, name)

    metadata_names = state.metadata.get("project_names")
    if isinstance(metadata_names, Sequence) and not isinstance(metadata_names, (str, bytes)):
        for project in metadata_names:
            add(project)
    metadata_roots = state.metadata.get("project_roots")
    if isinstance(metadata_roots, Mapping):
        for project in metadata_roots:
            add(project)
    for project, requirements in state.requirements.items():
        add(getattr(requirements, "project", "") or project)
    for service_name, service in state.services.items():
        add(service_project_name(service_name, service))
    return [display_by_key.get(key, key) for key in sorted(indexed_projects)]


def merge_indexed_states(
    indexed_states: Sequence[IndexedState],
    *,
    project_names_from_state: ProjectNamesResolver,
    source_run_ids: SourceRunIdsResolver,
) -> RunState:
    ordered = sorted(indexed_states, key=lambda item: item.candidate.sequence)
    latest = max(
        indexed_states,
        key=lambda item: (
            item.candidate.activation_sequence,
            item.candidate.sequence,
            str(item.candidate.state_path),
        ),
    ).state
    services: dict[str, ServiceRecord] = {}
    requirements: dict[str, RequirementsResult] = {}
    pointers: dict[str, str] = {}
    project_roots: dict[str, object] = {}
    project_names: dict[str, str] = {}
    for indexed_state in ordered:
        state = indexed_state.state
        state_project_names = [str(name).strip() for name in project_names_from_state(state) if str(name).strip()]
        if not state_project_names:
            state_project_names = [
                str(name).strip()
                for name in indexed_state.candidate.project_names
                if str(name).strip()
            ]
        fallback_project = state_project_names[0] if len(state_project_names) == 1 else ""
        incoming_services = {
            name: (
                service
                if str(getattr(service, "project", "") or "").strip() or not fallback_project
                else replace(service, project=fallback_project)
            )
            for name, service in state.services.items()
        }
        _merge_indexed_services(
            services,
            incoming_services,
            service_project_name=_service_project_from_record,
        )
        _merge_indexed_requirements(requirements, state.requirements)
        pointers.update(state.pointers)
        for name in state_project_names:
            project_names.setdefault(name.casefold(), name)
        roots = state.metadata.get("project_roots")
        if isinstance(roots, Mapping):
            project_roots.update({str(name): root for name, root in roots.items()})

    selected_project_names = [project_names[key] for key in sorted(project_names)]
    metadata = merge_project_scoped_metadata(
        latest.metadata,
        ordered,
        project_names=selected_project_names,
    )
    metadata["project_names"] = selected_project_names
    all_source_run_ids = {
        source_run_id
        for indexed_state in ordered
        for source_run_id in (
            indexed_state.candidate.run_id,
            *source_run_ids(indexed_state.state),
        )
    }
    metadata["state_source_run_ids"] = sorted(all_source_run_ids)
    if project_roots:
        metadata["project_roots"] = project_roots
    merge_startup_identities(metadata, ordered, project_roots=project_roots)
    return RunState(
        run_id=latest.run_id,
        mode=latest.mode,
        schema_version=latest.schema_version,
        backend_mode=latest.backend_mode,
        services=services,
        requirements=requirements,
        pointers=pointers,
        metadata=metadata,
    )


def _service_project_from_record(name: str, service: ServiceRecord) -> str:
    project = str(getattr(service, "project", "") or "").strip()
    if project:
        return project
    rendered = str(name).strip()
    service_type = str(getattr(service, "type", "") or "").strip()
    suffix = f" {service_type}".casefold()
    return rendered[: -len(suffix)].strip() if suffix and rendered.casefold().endswith(suffix) else ""


def _merge_indexed_services(
    merged: dict[str, ServiceRecord],
    incoming: Mapping[str, ServiceRecord],
    *,
    service_project_name: ServiceProjectResolver,
) -> None:
    for storage_name, service in incoming.items():
        existing = merged.get(storage_name)
        if existing is None:
            merged[storage_name] = service
            continue
        existing_project = service_project_name(storage_name, existing).strip().casefold()
        incoming_project = service_project_name(storage_name, service).strip().casefold()
        if not existing_project or not incoming_project or existing_project == incoming_project:
            merged[storage_name] = service
            continue
        replacement_name = _unique_aggregate_storage_name(
            storage_name,
            owner=str(getattr(service, "project", "") or incoming_project),
            pid=getattr(service, "pid", None),
            occupied=set(merged).union(incoming),
        )
        merged[replacement_name] = replace(service, name=replacement_name)


def _merge_indexed_requirements(
    merged: dict[str, RequirementsResult],
    incoming: Mapping[str, RequirementsResult],
) -> None:
    for storage_key, requirements in incoming.items():
        existing = merged.get(storage_key)
        if existing is None:
            merged[storage_key] = requirements
            continue
        existing_project = str(existing.project or storage_key).strip().casefold()
        incoming_project = str(requirements.project or storage_key).strip().casefold()
        if not existing_project or not incoming_project or existing_project == incoming_project:
            merged[storage_key] = requirements
            continue
        replacement_key = _unique_aggregate_storage_name(
            storage_key,
            owner=str(requirements.project or incoming_project),
            pid=None,
            occupied=set(merged).union(incoming),
        )
        merged[replacement_key] = requirements


def _unique_aggregate_storage_name(
    original: str,
    *,
    owner: str,
    pid: object,
    occupied: set[str],
) -> str:
    owner_label = str(owner).strip() or "unknown"
    pid_label = f" {pid}" if isinstance(pid, int) and pid > 0 else ""
    base = f"{original} State Collision {owner_label}{pid_label}"
    candidate = base
    index = 2
    while candidate in occupied:
        candidate = f"{base} {index}"
        index += 1
    return candidate


def merge_project_scoped_metadata(
    latest_metadata: Mapping[str, object],
    indexed_states: Sequence[IndexedState],
    *,
    project_names: Sequence[str],
) -> dict[str, object]:
    metadata = dict(latest_metadata)
    for key in PROJECT_SCOPED_METADATA_MAP_KEYS:
        merged: dict[str, object] = {}
        for indexed_state in indexed_states:
            raw = indexed_state.state.metadata.get(key)
            if isinstance(raw, Mapping):
                merged.update({str(project): value for project, value in raw.items()})
        if merged:
            metadata[key] = merged
        else:
            metadata.pop(key, None)

    stopped_by_identity: dict[tuple[str, str, str], dict[str, object]] = {}
    for indexed_state in indexed_states:
        raw_stopped = indexed_state.state.metadata.get(DASHBOARD_STOPPED_SERVICES_KEY)
        if not isinstance(raw_stopped, list):
            continue
        for item in raw_stopped:
            if not isinstance(item, Mapping):
                continue
            project = str(item.get("project", "")).strip()
            name = str(item.get("name", "")).strip()
            service_type = str(item.get("type", "")).strip().lower()
            if not project or not name or not service_type:
                continue
            stopped_by_identity[(project.casefold(), name.casefold(), service_type)] = dict(item)
    if stopped_by_identity:
        metadata[DASHBOARD_STOPPED_SERVICES_KEY] = [stopped_by_identity[key] for key in sorted(stopped_by_identity)]
    else:
        metadata.pop(DASHBOARD_STOPPED_SERVICES_KEY, None)

    if len(indexed_states) > 1:
        metadata.pop("project_test_results_root", None)
        metadata.pop("project_test_results_updated_at", None)
    return filter_project_scoped_metadata(
        metadata,
        list(project_names),
        case_sensitive=False,
    )


def filter_startup_identity_projects(
    metadata: dict[str, object],
    project_names: frozenset[str],
) -> None:
    raw_identity = metadata.get("startup_identity")
    if not isinstance(raw_identity, Mapping):
        return
    identity = dict(raw_identity)
    raw_projects = identity.get("projects")
    projects = raw_projects if isinstance(raw_projects, list) else []
    identity["projects"] = [
        project
        for project in projects
        if isinstance(project, Mapping) and str(project.get("name", "")).strip().casefold() in project_names
    ]
    identity.pop("fingerprint", None)
    identity["fingerprint"] = text_fingerprint(json.dumps(identity, sort_keys=True))
    metadata["startup_identity"] = identity


def merge_startup_identities(
    metadata: dict[str, object],
    indexed_states: Sequence[IndexedState],
    *,
    project_roots: Mapping[str, object],
) -> None:
    identities = [
        dict(identity)
        for indexed_state in indexed_states
        if isinstance((identity := indexed_state.state.metadata.get("startup_identity")), Mapping)
    ]
    if not identities:
        metadata.pop("startup_identity", None)
        return
    comparable = [
        {key: value for key, value in identity.items() if key not in {"fingerprint", "projects"}}
        for identity in identities
    ]
    if any(payload != comparable[0] for payload in comparable[1:]):
        metadata.pop("startup_identity", None)
        return
    identity = dict(comparable[0])
    identity["projects"] = [
        {"name": name, "root": str(root)}
        for name, root in sorted(project_roots.items(), key=lambda item: item[0].casefold())
    ]
    identity["fingerprint"] = text_fingerprint(json.dumps(identity, sort_keys=True))
    metadata["startup_identity"] = identity
