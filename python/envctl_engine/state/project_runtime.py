from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from envctl_engine.dashboard_metadata import (
    DASHBOARD_CONFIGURED_SERVICE_TYPES_KEY,
    DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY,
    DASHBOARD_STOPPED_SERVICES_KEY,
    normalize_dashboard_service_types,
)
from envctl_engine.shared.services import service_project_name
from envctl_engine.state.fingerprints import text_fingerprint
from envctl_engine.state.models import RequirementsResult, RunState


PROJECT_SCOPED_METADATA_MAP_KEYS = (
    "project_roots",
    "project_pr_links",
    "project_test_summaries",
    "project_action_reports",
    DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY,
)
_PROJECT_TEST_METADATA_COMPANION_KEYS = (
    "project_test_results_root",
    "project_test_results_updated_at",
)


@dataclass(slots=True)
class ProjectRuntimeResolution:
    ok: bool
    command: str
    requested_projects: list[str]
    active_projects: list[str]
    selected_projects: list[str]
    state: RunState | None = None
    error: str | None = None
    matches: list[str] | None = None

    @property
    def requested_project(self) -> str | None:
        return self.requested_projects[0] if self.requested_projects else None

    def payload(self) -> dict[str, object]:
        if self.ok:
            return {
                "ok": True,
                "requested_project": self.requested_project,
                "active_projects": list(self.active_projects),
                "selected_projects": list(self.selected_projects),
            }
        if self.error == "requested_project_not_running":
            return requested_project_not_running_payload(
                requested_project=self.requested_project or "",
                active_projects=self.active_projects,
            )
        if self.error == "multiple_projects_not_supported":
            return {
                "ok": False,
                "error": "multiple_projects_not_supported",
                "requested_projects": list(self.requested_projects),
                "active_projects": list(self.active_projects),
            }
        if self.error == "ambiguous_project_selector":
            return {
                "ok": False,
                "error": "ambiguous_project_selector",
                "requested_project": self.requested_project,
                "active_projects": list(self.active_projects),
                "matches": list(self.matches or []),
            }
        return {
            "ok": False,
            "error": self.error or "project_resolution_failed",
            "requested_projects": list(self.requested_projects),
            "active_projects": list(self.active_projects),
        }


def active_project_names(state: RunState, *, runtime: Any | None = None) -> list[str]:
    names: set[str] = set()
    for name in getattr(state, "requirements", {}) or {}:
        normalized = str(name).strip()
        if normalized:
            names.add(normalized)
    for service_name, service in (getattr(state, "services", {}) or {}).items():
        explicit_project = str(getattr(service, "project", "") or "").strip()
        project = explicit_project
        if not project and runtime is not None:
            resolver = getattr(runtime, "_project_name_from_service", None)
            if callable(resolver):
                try:
                    project = str(resolver(str(service_name)) or "").strip()
                except Exception:
                    project = ""
        if not project:
            project = service_project_name(service)
        if project:
            names.add(project)
    metadata_roots = getattr(state, "metadata", {}).get("project_roots")
    if isinstance(metadata_roots, Mapping):
        for name in metadata_roots:
            normalized = str(name).strip()
            if normalized:
                names.add(normalized)
    return sorted(names, key=lambda value: (value.lower(), value))


def resolve_requested_project_state(
    state: RunState,
    requested_projects: list[str] | tuple[str, ...],
    *,
    command: str,
    runtime: Any | None = None,
    allow_multi: bool = True,
) -> ProjectRuntimeResolution:
    requested = [str(project).strip() for project in requested_projects if str(project).strip()]
    active = active_project_names(state, runtime=runtime)
    if not requested:
        return ProjectRuntimeResolution(
            ok=True,
            command=command,
            requested_projects=[],
            active_projects=active,
            selected_projects=active,
            state=state,
        )
    if len(requested) > 1 and not allow_multi:
        return ProjectRuntimeResolution(
            ok=False,
            command=command,
            requested_projects=requested,
            active_projects=active,
            selected_projects=[],
            error="multiple_projects_not_supported",
        )
    canonical_by_exact = {project: project for project in active}
    selected: list[str] = []
    for project in requested:
        canonical = canonical_by_exact.get(project)
        if canonical is None:
            return ProjectRuntimeResolution(
                ok=False,
                command=command,
                requested_projects=requested,
                active_projects=active,
                selected_projects=selected,
                error="requested_project_not_running",
            )
        if canonical not in selected:
            selected.append(canonical)
    return ProjectRuntimeResolution(
        ok=True,
        command=command,
        requested_projects=requested,
        active_projects=active,
        selected_projects=selected,
        state=filter_state_to_projects(state, selected, runtime=runtime),
    )


def _service_project_name(service_name: str, service: object, *, runtime: Any | None = None) -> str:
    explicit_project = str(getattr(service, "project", "") or "").strip()
    if explicit_project:
        return explicit_project
    if runtime is not None:
        resolver = getattr(runtime, "_project_name_from_service", None)
        if callable(resolver):
            try:
                resolved = str(resolver(str(service_name)) or "").strip()
            except Exception:
                resolved = ""
            if resolved:
                return resolved
    return service_project_name(service)


def filter_state_to_projects(
    state: RunState,
    projects: list[str] | tuple[str, ...] | set[str],
    *,
    runtime: Any | None = None,
) -> RunState:
    selected = {str(project).strip() for project in projects if str(project).strip()}
    if not selected:
        return RunState(run_id=state.run_id, mode=state.mode)
    services = {
        name: service
        for name, service in state.services.items()
        if _service_project_name(name, service, runtime=runtime) in selected
    }
    requirements = _filtered_requirements(state.requirements, selected)
    metadata = filter_project_scoped_metadata(state.metadata, selected)
    metadata["project_names"] = sorted(selected, key=lambda value: (value.casefold(), value))
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


def filter_project_scoped_metadata(
    metadata: Mapping[str, object],
    projects: list[str] | tuple[str, ...] | set[str] | frozenset[str],
    *,
    case_sensitive: bool = True,
) -> dict[str, object]:
    """Return metadata containing only records owned by the selected projects.

    Runtime state has several independently evolved project-keyed metadata
    surfaces. Keeping their filtering in one place prevents a selected state
    from retaining dashboard, PR, test, or action data for another run.
    """

    selected = {str(project).strip() for project in projects if str(project).strip()}
    normalized_selected = selected if case_sensitive else {project.casefold() for project in selected}

    def selected_project(project: object) -> bool:
        value = str(project).strip()
        if not value:
            return False
        return value in normalized_selected if case_sensitive else value.casefold() in normalized_selected

    filtered = dict(metadata)
    for key in PROJECT_SCOPED_METADATA_MAP_KEYS:
        raw = metadata.get(key)
        if not isinstance(raw, Mapping):
            if key in metadata:
                filtered.pop(key, None)
            continue
        retained = {str(project): value for project, value in raw.items() if selected_project(project)}
        if retained:
            filtered[key] = retained
        else:
            filtered.pop(key, None)

    raw_stopped = metadata.get(DASHBOARD_STOPPED_SERVICES_KEY)
    if isinstance(raw_stopped, list):
        stopped: list[dict[str, object]] = []
        for item in raw_stopped:
            if not isinstance(item, Mapping) or not selected_project(item.get("project", "")):
                continue
            if not str(item.get("name", "")).strip() or not str(item.get("type", "")).strip():
                continue
            stopped.append(dict(item))
        if stopped:
            filtered[DASHBOARD_STOPPED_SERVICES_KEY] = stopped
        else:
            filtered.pop(DASHBOARD_STOPPED_SERVICES_KEY, None)
    elif DASHBOARD_STOPPED_SERVICES_KEY in metadata:
        filtered.pop(DASHBOARD_STOPPED_SERVICES_KEY, None)

    raw_summaries = metadata.get("project_test_summaries")
    retained_summaries = filtered.get("project_test_summaries")
    summaries_were_narrowed = (
        isinstance(raw_summaries, Mapping)
        and isinstance(retained_summaries, Mapping)
        and len(retained_summaries) != len(raw_summaries)
    )
    if not isinstance(retained_summaries, Mapping) or not retained_summaries or summaries_were_narrowed:
        for key in _PROJECT_TEST_METADATA_COMPANION_KEYS:
            filtered.pop(key, None)

    if DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY in metadata or DASHBOARD_STOPPED_SERVICES_KEY in metadata:
        configured_types: set[str] = set()
        configured = filtered.get(DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY)
        if isinstance(configured, Mapping):
            for service_types in configured.values():
                configured_types.update(normalize_dashboard_service_types(service_types))
        stopped = filtered.get(DASHBOARD_STOPPED_SERVICES_KEY)
        if isinstance(stopped, list):
            configured_types.update(
                normalize_dashboard_service_types(
                    [item.get("type", "") for item in stopped if isinstance(item, Mapping)]
                )
            )
        if configured_types:
            filtered[DASHBOARD_CONFIGURED_SERVICE_TYPES_KEY] = sorted(configured_types)
        else:
            filtered.pop(DASHBOARD_CONFIGURED_SERVICE_TYPES_KEY, None)

    raw_identity = metadata.get("startup_identity")
    if isinstance(raw_identity, Mapping):
        identity = dict(raw_identity)
        raw_projects = identity.get("projects")
        identity_projects = raw_projects if isinstance(raw_projects, list) else []
        identity["projects"] = [
            dict(project)
            for project in identity_projects
            if isinstance(project, Mapping) and selected_project(project.get("name", ""))
        ]
        identity.pop("fingerprint", None)
        serialized = json.dumps(identity, sort_keys=True)
        identity["fingerprint"] = text_fingerprint(serialized)
        filtered["startup_identity"] = identity

    return filtered


def _filtered_requirements(
    requirements: Mapping[str, RequirementsResult],
    selected: set[str],
) -> dict[str, RequirementsResult]:
    direct = {project: req for project, req in requirements.items() if project in selected}
    if direct:
        return direct
    # Shared tree dependency state often stores requirements under Main. When a
    # single selected project has no direct dependency record, preserve the one
    # available requirements record so endpoint and health output can expose the
    # active shared dependency truth instead of pretending dependencies vanished.
    if len(selected) == 1 and len(requirements) == 1:
        only_req = next(iter(requirements.values()))
        selected_project = next(iter(selected))
        return {selected_project: only_req}
    return {}


def requested_project_not_running_payload(*, requested_project: str, active_projects: list[str]) -> dict[str, object]:
    return {
        "ok": False,
        "error": "requested_project_not_running",
        "requested_project": requested_project,
        "active_projects": list(active_projects),
    }


def dependency_mode_summary(state: RunState) -> dict[str, object]:
    metadata = getattr(state, "metadata", {}) or {}
    raw_mode = str(metadata.get("dependency_mode") or "").strip().lower()
    if raw_mode in {"shared", "isolated", "none"}:
        shared_raw = metadata.get("shared_dependencies")
        shared = bool(shared_raw) if isinstance(shared_raw, bool) else raw_mode == "shared"
        return {"dependency_mode": raw_mode, "shared_dependencies": shared}
    if str(metadata.get("dashboard_dependency_scope") or "").strip().lower() == "shared":
        return {"dependency_mode": "shared", "shared_dependencies": True}
    if state.mode == "main":
        return {"dependency_mode": "shared", "shared_dependencies": True}
    return {"dependency_mode": "unknown", "shared_dependencies": None}


def project_root_for_state(state: RunState, project: str, *, runtime: Any | None = None) -> str | None:
    roots = getattr(state, "metadata", {}).get("project_roots")
    if isinstance(roots, Mapping):
        raw = roots.get(project)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    for service_name, service in state.services.items():
        if _service_project_name(service_name, service, runtime=runtime) == project:
            cwd = str(getattr(service, "cwd", "") or "").strip()
            if cwd:
                return cwd
    return None


def infer_cwd_project(state: RunState, *, runtime: Any | None = None) -> str | None:
    cwd = _runtime_cwd(runtime)
    if cwd is None:
        return None
    roots = getattr(state, "metadata", {}).get("project_roots")
    if isinstance(roots, Mapping):
        for project, raw_root in roots.items():
            root = _safe_resolve(raw_root)
            if root is not None and _path_is_within(cwd, root):
                return str(project)
    config = getattr(runtime, "config", None)
    base_dir = _safe_resolve(getattr(config, "base_dir", None))
    if base_dir is not None and _path_is_within(cwd, base_dir):
        return "Main"
    return None


def cwd_runtime_warnings(
    state: RunState,
    *,
    runtime: Any | None = None,
    requested_projects: list[str] | tuple[str, ...] | None = None,
) -> tuple[str | None, list[dict[str, object]]]:
    if requested_projects:
        return infer_cwd_project(state, runtime=runtime), []
    cwd_project = infer_cwd_project(state, runtime=runtime)
    active = _runtime_truth_project_names(state, runtime=runtime) or active_project_names(state, runtime=runtime)
    if cwd_project is None or not active or cwd_project in active:
        return cwd_project, []
    return cwd_project, [
        {
            "code": "cwd_runtime_mismatch",
            "cwd_project": cwd_project,
            "active_projects": active,
            "message": f"Current cwd project {cwd_project} does not match active runtime projects: {', '.join(active)}",
        }
    ]


def project_resolution_event_payload(
    resolution: ProjectRuntimeResolution,
    state: RunState,
    *,
    runtime: Any | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "command": resolution.command,
        "run_id": state.run_id,
        "mode": state.mode,
        "requested_projects": list(resolution.requested_projects),
        "selected_projects": list(resolution.selected_projects),
        "active_projects": list(resolution.active_projects),
        "cwd_project": infer_cwd_project(state, runtime=runtime),
    }
    if resolution.requested_project is not None:
        payload["requested_project"] = resolution.requested_project
    if resolution.error:
        payload["error"] = resolution.error
    if resolution.matches:
        payload["matches"] = list(resolution.matches)
    return payload


def _runtime_truth_project_names(state: RunState, *, runtime: Any | None = None) -> list[str]:
    names: set[str] = set()
    for name in getattr(state, "requirements", {}) or {}:
        normalized = str(name).strip()
        if normalized:
            names.add(normalized)
    for service_name, service in (getattr(state, "services", {}) or {}).items():
        explicit_project = str(getattr(service, "project", "") or "").strip()
        project = explicit_project
        if not project and runtime is not None:
            resolver = getattr(runtime, "_project_name_from_service", None)
            if callable(resolver):
                try:
                    project = str(resolver(str(service_name)) or "").strip()
                except Exception:
                    project = ""
        if not project:
            project = service_project_name(service)
        if project:
            names.add(project)
    return sorted(names, key=lambda value: (value.lower(), value))


def _runtime_cwd(runtime: Any | None) -> Path | None:
    env = getattr(runtime, "env", {}) if runtime is not None else {}
    raw = None
    if isinstance(env, Mapping):
        raw = env.get("ENVCTL_INVOCATION_CWD")
    if raw is None:
        raw = getattr(getattr(runtime, "config", None), "execution_root", None)
    return _safe_resolve(raw)


def _safe_resolve(value: object) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return Path(text).expanduser().resolve()
    except OSError:
        return None


def _path_is_within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents
