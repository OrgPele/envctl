from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from envctl_engine.requirements.core import dependency_ids
from envctl_engine.requirements.external import dependency_external_mode
from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.services import service_project_name, service_slug_from_record
from envctl_engine.state.models import RunState
from envctl_engine.startup.startup_selection_support import (
    _restart_service_types_for_project,
)


@dataclass(frozen=True, slots=True)
class ProjectIdentity:
    name: str
    root: str | None


@dataclass(slots=True)
class RunReuseDecision:
    candidate_state: RunState | None
    decision_kind: str
    reason: str
    selected_projects: list[dict[str, str | None]]
    state_projects: list[dict[str, str | None]]
    mismatch_details: dict[str, object] = field(default_factory=dict)
    weak_identity: bool = False
    startup_enabled: bool = True

    @property
    def will_reuse_run(self) -> bool:
        return self.decision_kind != "fresh_run"

    @property
    def will_resume_services(self) -> bool:
        return self.decision_kind in {"resume_exact", "resume_subset", "reuse_expand"}


def build_startup_identity_metadata(
    runtime: Any,
    *,
    runtime_mode: str,
    project_contexts: list[object],
    base_metadata: Mapping[str, object] | None = None,
    route: Route | None = None,
) -> dict[str, object]:
    metadata = dict(base_metadata or {})
    project_roots = {
        str(getattr(context, "name", "")).strip(): root
        for context, root in (
            (context, normalize_project_root(getattr(context, "root", None)))
            for context in project_contexts
        )
        if str(getattr(context, "name", "")).strip() and root
    }
    identity_payload = _startup_identity_payload(
        runtime,
        runtime_mode=runtime_mode,
        project_contexts=project_contexts,
        route=route,
    )
    metadata["project_roots"] = project_roots
    metadata["startup_identity"] = identity_payload
    return metadata


def mark_run_reused(metadata: Mapping[str, object] | None, *, reason: str) -> dict[str, object]:
    updated = dict(metadata or {})
    raw_count = updated.get("run_reuse_count", 0)
    try:
        count = int(raw_count)
    except (TypeError, ValueError):
        count = 0
    updated["run_reuse_count"] = max(0, count) + 1
    updated["last_reopened_at"] = datetime.now(tz=UTC).isoformat()
    updated["last_reuse_reason"] = reason
    return updated


def dashboard_stopped_service_entries(state: object) -> list[dict[str, str]]:
    raw = getattr(state, "metadata", {}).get("dashboard_stopped_services")
    if not isinstance(raw, list):
        return []
    entries: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        project = str(item.get("project", "") or "").strip()
        service_type = str(item.get("type", "") or "").strip().lower()
        name = str(item.get("name", "") or "").strip()
        if not project or service_type not in {"backend", "frontend"}:
            continue
        entries.append(
            {
                "project": project,
                "type": service_type,
                "name": name or f"{project} {service_type.title()}",
            }
        )
    return entries


def metadata_without_dashboard_stopped_services(
    metadata: Mapping[str, object],
    *,
    restored_service_names: set[str],
) -> dict[str, object]:
    updated = dict(metadata)
    raw = updated.get("dashboard_stopped_services")
    if not isinstance(raw, list):
        return updated
    remaining: list[object] = []
    for item in raw:
        if not isinstance(item, Mapping):
            remaining.append(item)
            continue
        name = str(item.get("name", "") or "").strip()
        if name in restored_service_names:
            continue
        remaining.append(dict(item))
    if remaining:
        updated["dashboard_stopped_services"] = remaining
    else:
        updated.pop("dashboard_stopped_services", None)
    return updated


def prepare_dashboard_stopped_service_restore(
    *,
    runtime: Any,
    session: Any,
    candidate_state: Any,
    reuse_started: float,
    decision_kind: str,
    emit_phase: Callable[..., None],
) -> bool:
    active_service_names = set(candidate_state.services)
    stopped_entries = [
        entry
        for entry in dashboard_stopped_service_entries(candidate_state)
        if entry["name"] not in active_service_names
    ]
    if not stopped_entries:
        return False
    selected_context_by_name = {
        str(context.name).strip().casefold(): context
        for context in session.selected_contexts
        if str(getattr(context, "name", "")).strip()
    }
    restore_entries = [entry for entry in stopped_entries if entry["project"].casefold() in selected_context_by_name]
    if not restore_entries:
        return False
    target_project_names = sorted({entry["project"] for entry in restore_entries}, key=str.casefold)
    target_project_keys = {name.casefold() for name in target_project_names}
    contexts_to_start = [context for key, context in selected_context_by_name.items() if key in target_project_keys]
    if not contexts_to_start:
        return False
    stopped_service_names = sorted({entry["name"] for entry in restore_entries})
    stopped_service_types = sorted({entry["type"] for entry in restore_entries})
    session.base_metadata = metadata_without_dashboard_stopped_services(
        mark_run_reused(candidate_state.metadata, reason="restore_stopped_services"),
        restored_service_names=set(stopped_service_names),
    )
    session.preserved_services = dict(candidate_state.services)
    session.preserved_requirements = dict(candidate_state.requirements)
    session.contexts_to_start = contexts_to_start
    route = session.effective_route
    session.effective_route = Route(
        command=route.command,
        mode=route.mode,
        raw_args=route.raw_args,
        passthrough_args=route.passthrough_args,
        projects=target_project_names,
        flags={
            **route.flags,
            "_restart_request": True,
            "_restore_dashboard_stopped_services": True,
            "services": stopped_service_names,
            "restart_service_types": stopped_service_types,
            "restart_include_requirements": False,
        },
    )
    emit_phase(
        session,
        "auto_resume_evaluate",
        reuse_started,
        status="restore_stopped_services",
        match_mode="exact" if decision_kind == "resume_exact" else "subset",
        stopped_service_count=len(stopped_service_names),
        target_projects=target_project_names,
    )
    runtime._emit(
        "state.auto_resume.restore_stopped_services",
        run_id=candidate_state.run_id,
        mode=session.runtime_mode,
        command=route.command,
        projects=target_project_names,
        services=stopped_service_names,
    )
    runtime._emit(
        "state.run_reuse.applied",
        run_id=candidate_state.run_id,
        mode=session.runtime_mode,
        command=route.command,
        decision_kind="restore_stopped_services",
        reason="dashboard_stopped_services",
        restored_projects=target_project_names,
        restored_services=stopped_service_names,
    )
    return True


def prepare_dashboard_stopped_service_restore_with_runtime(
    runtime: Any,
    emit_phase: Callable[..., None],
    session: Any,
    *,
    candidate_state: Any,
    reuse_started: float,
    decision_kind: str,
) -> bool:
    return prepare_dashboard_stopped_service_restore(
        runtime=runtime,
        session=session,
        candidate_state=candidate_state,
        reuse_started=reuse_started,
        decision_kind=decision_kind,
        emit_phase=emit_phase,
    )


def fresh_start_replacement_services(
    *,
    route: Route,
    selected_contexts: list[object],
    candidate_state: object,
    configured_service_types: set[str],
    additional_services: tuple[object, ...],
    project_name_from_service: Callable[[str], str],
) -> set[str]:
    target_projects = {str(context.name).strip().lower() for context in selected_contexts}
    target_projects.discard("")
    if not target_projects:
        return set()
    selected_by_project = {
        str(context.name).strip().lower(): _restart_service_types_for_project(
            route=route,
            project_name=str(context.name),
            default_service_types=configured_service_types,
            additional_services=additional_services,
        )
        for context in selected_contexts
        if str(context.name).strip()
    }
    selected: set[str] = set()
    for service_name, service in getattr(candidate_state, "services", {}).items():
        project = service_project_name(service) or project_name_from_service(service_name)
        project_key = str(project).strip().lower()
        if project_key not in target_projects:
            continue
        service_type = service_slug_from_record(service)
        if service_type and service_type in selected_by_project.get(project_key, set()):
            selected.add(service_name)
    return selected


def replace_existing_project_services_for_fresh_start(
    *,
    runtime: Any,
    session: Any,
    candidate_state: Any,
    reason: str,
    fresh_start_replacement_services: Callable[..., set[str]],
    announce_session_identifiers: Callable[[Any], None],
    report_progress: Callable[[Route, str], None],
    terminate_restart_orphan_listeners: Callable[..., None],
) -> None:
    if reason != "startup_fingerprint_mismatch":
        return
    route = session.effective_route
    if route.flags.get("runtime_scope") == "dependencies":
        return
    selected_services = fresh_start_replacement_services(session, candidate_state=candidate_state)
    if not selected_services:
        return
    announce_session_identifiers(session)
    report_progress(
        route,
        f"Startup selection changed; replacing {len(selected_services)} existing service(s)...",
    )
    runtime._emit(
        "state.run_reuse.replace_existing_services",
        run_id=candidate_state.run_id,
        mode=session.runtime_mode,
        reason=reason,
        selected_services=sorted(selected_services),
    )
    runtime._terminate_services_from_state(
        candidate_state,
        selected_services=selected_services,
        aggressive=False,
        verify_ownership=True,
    )
    terminate_restart_orphan_listeners(
        state=candidate_state,
        selected_services=selected_services,
        aggressive=True,
    )


def replace_existing_project_services_for_fresh_start_with_defaults(
    *,
    runtime: Any,
    session: Any,
    candidate_state: Any,
    reason: str,
    configured_service_types: set[str],
    additional_services: tuple[object, ...],
    announce_session_identifiers: Callable[[Any], None],
    report_progress: Callable[[Route, str], None],
    terminate_restart_orphan_listeners: Callable[..., None],
) -> None:
    replace_existing_project_services_for_fresh_start(
        runtime=runtime,
        session=session,
        candidate_state=candidate_state,
        reason=reason,
        fresh_start_replacement_services=lambda _, *, candidate_state: fresh_start_replacement_services(
            route=session.effective_route,
            selected_contexts=list(session.selected_contexts),
            candidate_state=candidate_state,
            configured_service_types=configured_service_types,
            additional_services=additional_services,
            project_name_from_service=runtime._project_name_from_service,
        ),
        announce_session_identifiers=announce_session_identifiers,
        report_progress=report_progress,
        terminate_restart_orphan_listeners=terminate_restart_orphan_listeners,
    )


def evaluate_run_reuse(
    runtime: Any,
    *,
    runtime_mode: str,
    route: Route,
    contexts: list[object],
) -> RunReuseDecision:
    selected_identities = project_identities_from_contexts(contexts)
    selected_payload = identities_to_payload(selected_identities)
    startup_enabled = _startup_enabled(runtime, runtime_mode)
    if not selected_identities:
        return RunReuseDecision(
            candidate_state=None,
            decision_kind="fresh_run",
            reason="no_selected_projects",
            selected_projects=selected_payload,
            state_projects=[],
            startup_enabled=startup_enabled,
        )

    if not _auto_resume_start_enabled(route):
        return RunReuseDecision(
            candidate_state=None,
            decision_kind="fresh_run",
            reason="auto_resume_disabled",
            selected_projects=selected_payload,
            state_projects=[],
            startup_enabled=startup_enabled,
        )

    candidate = runtime._try_load_existing_state(mode=runtime_mode, strict_mode_match=True)
    if candidate is None:
        return RunReuseDecision(
            candidate_state=None,
            decision_kind="fresh_run",
            reason="no_matching_state",
            selected_projects=selected_payload,
            state_projects=[],
            startup_enabled=startup_enabled,
        )
    if candidate.mode != runtime_mode:
        return RunReuseDecision(
            candidate_state=candidate,
            decision_kind="fresh_run",
            reason="mode_mismatch",
            selected_projects=selected_payload,
            state_projects=identities_to_payload(project_identities_from_state(runtime, candidate)),
            startup_enabled=startup_enabled,
        )
    if bool(candidate.metadata.get("failed", False)):
        return RunReuseDecision(
            candidate_state=candidate,
            decision_kind="fresh_run",
            reason="failed_state",
            selected_projects=selected_payload,
            state_projects=identities_to_payload(project_identities_from_state(runtime, candidate)),
            startup_enabled=startup_enabled,
        )

    state_identities = project_identities_from_state(runtime, candidate)
    state_payload = identities_to_payload(state_identities)
    if not state_identities:
        return RunReuseDecision(
            candidate_state=candidate,
            decision_kind="fresh_run",
            reason="project_selection_mismatch",
            selected_projects=selected_payload,
            state_projects=state_payload,
            startup_enabled=startup_enabled,
        )

    root_mismatches = _root_mismatches(selected_identities, state_identities)
    if root_mismatches:
        return RunReuseDecision(
            candidate_state=candidate,
            decision_kind="fresh_run",
            reason="project_root_mismatch",
            selected_projects=selected_payload,
            state_projects=state_payload,
            mismatch_details={"projects": sorted(root_mismatches)},
            startup_enabled=startup_enabled,
        )

    weak_identity = any(identity.root is None for identity in state_identities)
    selected_keys = _identity_keys(selected_identities, weak=weak_identity)
    state_keys = _identity_keys(state_identities, weak=weak_identity)
    exact_match = selected_keys == state_keys
    subset_match = runtime_mode == "trees" and selected_keys.issubset(state_keys)
    expand_match = (
        runtime_mode == "trees" and route.command in {"start", "plan"} and state_keys.issubset(selected_keys)
    )
    if not (exact_match or subset_match or expand_match):
        return RunReuseDecision(
            candidate_state=candidate,
            decision_kind="fresh_run",
            reason="project_selection_mismatch",
            selected_projects=selected_payload,
            state_projects=state_payload,
            weak_identity=weak_identity,
            startup_enabled=startup_enabled,
        )

    previous_identity = candidate.metadata.get("startup_identity")
    if isinstance(previous_identity, dict):
        state_identity_under_current_runtime = _startup_identity_payload(
            runtime,
            runtime_mode=runtime_mode,
            project_contexts=list(state_identities),
            route=route,
        )
        identity_mismatch = _startup_identity_mismatch(
            previous_identity,
            state_identity_under_current_runtime,
        )
        if identity_mismatch:
            return RunReuseDecision(
                candidate_state=candidate,
                decision_kind="fresh_run",
                reason="startup_fingerprint_mismatch",
                selected_projects=selected_payload,
                state_projects=state_payload,
                mismatch_details=identity_mismatch,
                weak_identity=weak_identity,
                startup_enabled=startup_enabled,
            )

    if exact_match:
        if state_has_resumable_services(runtime, candidate):
            decision_kind = "resume_exact"
        elif _dashboard_state_reusable(candidate):
            decision_kind = "resume_dashboard_exact"
        else:
            decision_kind = "fresh_run"
        return RunReuseDecision(
            candidate_state=candidate,
            decision_kind=decision_kind,
            reason="exact_match" if decision_kind != "fresh_run" else "no_reusable_runtime",
            selected_projects=selected_payload,
            state_projects=state_payload,
            weak_identity=weak_identity,
            startup_enabled=startup_enabled,
        )

    if subset_match and state_has_resumable_services(runtime, candidate):
        return RunReuseDecision(
            candidate_state=candidate,
            decision_kind="resume_subset",
            reason="subset_match",
            selected_projects=selected_payload,
            state_projects=state_payload,
            weak_identity=weak_identity,
            startup_enabled=startup_enabled,
        )

    if expand_match and state_has_resumable_services(runtime, candidate):
        return RunReuseDecision(
            candidate_state=candidate,
            decision_kind="reuse_expand",
            reason="expand_match",
            selected_projects=selected_payload,
            state_projects=state_payload,
            weak_identity=weak_identity,
            startup_enabled=startup_enabled,
        )

    return RunReuseDecision(
        candidate_state=candidate,
        decision_kind="fresh_run",
        reason="no_reusable_runtime",
        selected_projects=selected_payload,
        state_projects=state_payload,
        weak_identity=weak_identity,
        startup_enabled=startup_enabled,
    )


def _startup_identity_mismatch(previous: Mapping[str, object], current: Mapping[str, object]) -> dict[str, object]:
    previous_fingerprint = str(previous.get("fingerprint", "")).strip()
    current_fingerprint = str(current.get("fingerprint", "")).strip()
    if previous_fingerprint and current_fingerprint and previous_fingerprint == current_fingerprint:
        return {}

    previous_payload = _startup_identity_comparison_payload(previous)
    current_payload = _startup_identity_comparison_payload(current)
    if previous_payload == current_payload:
        return {}

    changed_fields = [
        key
        for key in sorted(set(previous_payload) | set(current_payload))
        if previous_payload.get(key) != current_payload.get(key)
    ]
    return {"fields": changed_fields}


def _startup_identity_comparison_payload(identity: Mapping[str, object]) -> dict[str, object]:
    return {str(key): value for key, value in identity.items() if str(key) != "fingerprint"}


def project_identities_from_contexts(contexts: list[object]) -> list[ProjectIdentity]:
    identities: list[ProjectIdentity] = []
    for context in contexts:
        name = str(getattr(context, "name", "")).strip()
        if not name:
            continue
        identities.append(ProjectIdentity(name=name, root=normalize_project_root(getattr(context, "root", None))))
    return _sorted_identities(identities)


def project_identities_from_state(runtime: Any, state: RunState) -> list[ProjectIdentity]:
    metadata_roots = state.metadata.get("project_roots")
    roots = metadata_roots if isinstance(metadata_roots, dict) else {}
    names: dict[str, str | None] = {}
    for project_name, root_value in roots.items():
        normalized_name = str(project_name).strip()
        if not normalized_name:
            continue
        names[normalized_name] = normalize_project_root(root_value)
    for project_name in state.requirements:
        normalized_name = str(project_name).strip()
        if not normalized_name:
            continue
        names.setdefault(normalized_name, normalize_project_root(roots.get(normalized_name)))
    for service_name in state.services:
        project_name = runtime._project_name_from_service(service_name)
        normalized_name = str(project_name).strip()
        if not normalized_name:
            continue
        names.setdefault(normalized_name, normalize_project_root(roots.get(normalized_name)))
    return _sorted_identities(ProjectIdentity(name=name, root=root) for name, root in names.items())


def identities_to_payload(identities: list[ProjectIdentity]) -> list[dict[str, str | None]]:
    return [{"name": identity.name, "root": identity.root} for identity in identities]


def state_has_resumable_services(runtime: Any, state: RunState) -> bool:
    for service_name, service in state.services.items():
        project_name = runtime._project_name_from_service(service_name)
        if not project_name:
            continue
        service_type = str(getattr(service, "type", "")).strip().lower()
        if service_type in {"backend", "frontend"}:
            return True
    return False


def normalize_project_root(root: object) -> str | None:
    if root is None:
        return None
    raw = str(root).strip()
    if not raw:
        return None
    return str(Path(raw).expanduser().resolve(strict=False))



def _service_enabled_for_context(runtime: Any, runtime_mode: str, service: object, context: object) -> bool:
    enabled_for_project = getattr(service, "enabled_for_project_root", None)
    if callable(enabled_for_project):
        return bool(enabled_for_project(runtime_mode, getattr(context, "root", None)))
    enabled_for_mode = getattr(service, "enabled_for_mode", None)
    if callable(enabled_for_mode):
        return bool(enabled_for_mode(runtime_mode))
    return False


def _startup_service_payload(runtime: Any, runtime_mode: str, project_contexts: list[object]) -> dict[str, bool]:
    services = {
        "backend": _service_enabled(runtime, runtime_mode, "backend"),
        "frontend": _service_enabled(runtime, runtime_mode, "frontend"),
    }
    config = getattr(runtime, "config", None)
    for service in getattr(config, "additional_services", ()):
        name = str(getattr(service, "name", "") or "").strip()
        if not name:
            continue
        services[name] = any(
            _service_enabled_for_context(runtime, runtime_mode, service, context) for context in project_contexts
        )
    return services


def _startup_identity_payload(
    runtime: Any,
    *,
    runtime_mode: str,
    project_contexts: list[object],
    route: Route | None = None,
) -> dict[str, object]:
    startup_enabled = _startup_enabled(runtime, runtime_mode)
    services = _startup_service_payload(runtime, runtime_mode, project_contexts)
    dependencies = [
        dependency_id
        for dependency_id in sorted(dependency_ids())
        if _requirement_enabled(runtime, runtime_mode, dependency_id)
    ]
    if not startup_enabled:
        dependencies = []
    dependency_modes = {
        dependency_id: (
            "external"
            if dependency_external_mode(runtime, dependency_id, mode=runtime_mode, route=route)
            else "managed"
        )
        for dependency_id in dependencies
    }
    payload = {
        "mode": runtime_mode,
        "projects": identities_to_payload(project_identities_from_contexts(project_contexts)),
        "startup_enabled": startup_enabled,
        "services": services,
        "dependencies": dependencies,
        "dependency_modes": dependency_modes,
        "directories": {
            "backend": str(getattr(runtime.config, "backend_dir_name", "backend")),
            "frontend": str(getattr(runtime.config, "frontend_dir_name", "frontend")),
        },
    }
    payload["fingerprint"] = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return payload


def _sorted_identities(identities: list[ProjectIdentity] | Any) -> list[ProjectIdentity]:
    return sorted(
        list(identities),
        key=lambda item: (item.name.lower(), item.root or ""),
    )


def _identity_keys(identities: list[ProjectIdentity], *, weak: bool) -> set[tuple[str, str | None]]:
    if weak:
        return {(identity.name.lower(), None) for identity in identities}
    return {(identity.name.lower(), identity.root) for identity in identities}


def _root_mismatches(selected: list[ProjectIdentity], state: list[ProjectIdentity]) -> set[str]:
    state_by_name = {identity.name.lower(): identity for identity in state}
    mismatches: set[str] = set()
    for identity in selected:
        state_identity = state_by_name.get(identity.name.lower())
        if state_identity is None or identity.root is None or state_identity.root is None:
            continue
        if identity.root != state_identity.root:
            mismatches.add(identity.name)
    return mismatches


def _dashboard_state_reusable(state: RunState) -> bool:
    if not bool(state.metadata.get("dashboard_runs_disabled", False)):
        return False
    if state.services:
        return False
    metadata_roots = state.metadata.get("project_roots")
    return isinstance(metadata_roots, dict) and bool(metadata_roots)


def _startup_enabled(runtime: Any, runtime_mode: str) -> bool:
    config = getattr(runtime, "config", None)
    startup_enabled_for_mode = getattr(config, "startup_enabled_for_mode", None)
    if callable(startup_enabled_for_mode):
        return bool(startup_enabled_for_mode(runtime_mode))
    return True


def _service_enabled(runtime: Any, runtime_mode: str, service_name: str) -> bool:
    config = getattr(runtime, "config", None)
    service_enabled_for_mode = getattr(config, "service_enabled_for_mode", None)
    if callable(service_enabled_for_mode):
        return bool(service_enabled_for_mode(runtime_mode, service_name))
    return True


def _requirement_enabled(runtime: Any, runtime_mode: str, requirement_name: str) -> bool:
    config = getattr(runtime, "config", None)
    requirement_enabled_for_mode = getattr(config, "requirement_enabled_for_mode", None)
    if callable(requirement_enabled_for_mode):
        return bool(requirement_enabled_for_mode(runtime_mode, requirement_name))
    return True


def _auto_resume_start_enabled(route: Route) -> bool:
    if route.command not in {"start", "plan"}:
        return False
    if bool(route.flags.get("no_resume")):
        return False
    if bool(route.flags.get("planning_prs")):
        return False
    if bool(route.flags.get("setup_worktree")) or bool(route.flags.get("setup_worktrees")):
        return False
    return True
def run_reuse_debug_orch_groups(runtime: Any, *, requested_command: str) -> set[str]:
    if requested_command != "plan":
        return set()
    raw_orch_group = str(getattr(runtime, "env", {}).get("ENVCTL_DEBUG_PLAN_ORCH_GROUP", "")).strip().lower()
    return {token.strip() for token in raw_orch_group.replace("+", ",").split(",") if token.strip()}
