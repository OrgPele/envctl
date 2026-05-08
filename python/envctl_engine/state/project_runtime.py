from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from envctl_engine.shared.services import service_project_name
from envctl_engine.state.models import RequirementsResult, RunState


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
    canonical_by_normalized: dict[str, list[str]] = {}
    for project in active:
        canonical_by_normalized.setdefault(_normalize_project_selector(project), []).append(project)
    selected: list[str] = []
    for project in requested:
        canonical = canonical_by_exact.get(project)
        if canonical is None:
            matches = canonical_by_normalized.get(_normalize_project_selector(project), [])
            if len(matches) > 1:
                return ProjectRuntimeResolution(
                    ok=False,
                    command=command,
                    requested_projects=requested,
                    active_projects=active,
                    selected_projects=selected,
                    error="ambiguous_project_selector",
                    matches=matches,
                )
            canonical = matches[0] if matches else None
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
        state=filter_state_to_projects(state, selected),
    )



def _normalize_project_selector(project: str) -> str:
    return str(project).strip().casefold()


def filter_state_to_projects(state: RunState, projects: list[str] | tuple[str, ...] | set[str]) -> RunState:
    selected = {str(project).strip() for project in projects if str(project).strip()}
    if not selected:
        return RunState(run_id=state.run_id, mode=state.mode)
    services = {
        name: service
        for name, service in state.services.items()
        if service_project_name(service) in selected
    }
    requirements = _filtered_requirements(state.requirements, selected)
    metadata = dict(state.metadata)
    roots = metadata.get("project_roots")
    if isinstance(roots, Mapping):
        metadata["project_roots"] = {str(name): value for name, value in roots.items() if str(name) in selected}
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


def project_root_for_state(state: RunState, project: str) -> str | None:
    roots = getattr(state, "metadata", {}).get("project_roots")
    if isinstance(roots, Mapping):
        raw = roots.get(project)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    for service in state.services.values():
        if service_project_name(service) == project:
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
