from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.services import service_project_name, service_slug_from_record
from envctl_engine.state.models import RunState
from envctl_engine.startup.run_reuse_identity import (
    ProjectIdentity as ProjectIdentity,
    _auto_resume_start_enabled as _auto_resume_start_enabled,
    _identity_keys as _identity_keys,
    _requirement_enabled as _requirement_enabled,
    _root_mismatches as _root_mismatches,
    _service_enabled as _service_enabled,
    _service_enabled_for_context as _service_enabled_for_context,
    _sorted_identities as _sorted_identities,
    _startup_enabled as _startup_enabled,
    _startup_identity_comparison_payload as _startup_identity_comparison_payload,
    _startup_identity_mismatch as _startup_identity_mismatch,
    _startup_identity_payload as _startup_identity_payload,
    _startup_service_payload as _startup_service_payload,
    build_startup_identity_metadata as build_startup_identity_metadata,
    identities_to_payload as identities_to_payload,
    normalize_project_root as normalize_project_root,
    project_identities_from_contexts as project_identities_from_contexts,
    project_identities_from_state as project_identities_from_state,
)
from envctl_engine.startup.startup_selection_support import (
    _restart_service_types_for_project,
)


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


def state_has_resumable_services(runtime: Any, state: RunState) -> bool:
    for service_name, service in state.services.items():
        project_name = runtime._project_name_from_service(service_name)
        if not project_name:
            continue
        service_type = str(getattr(service, "type", "")).strip().lower()
        if service_type in {"backend", "frontend"}:
            return True
    return False


def _dashboard_state_reusable(state: RunState) -> bool:
    if not bool(state.metadata.get("dashboard_runs_disabled", False)):
        return False
    if state.services:
        return False
    metadata_roots = state.metadata.get("project_roots")
    return isinstance(metadata_roots, dict) and bool(metadata_roots)


def run_reuse_debug_orch_groups(runtime: Any, *, requested_command: str) -> set[str]:
    if requested_command != "plan":
        return set()
    raw_orch_group = str(getattr(runtime, "env", {}).get("ENVCTL_DEBUG_PLAN_ORCH_GROUP", "")).strip().lower()
    return {token.strip() for token in raw_orch_group.replace("+", ",").split(",") if token.strip()}
