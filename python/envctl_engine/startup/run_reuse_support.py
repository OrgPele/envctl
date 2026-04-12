from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from envctl_engine.requirements.core import dependency_ids
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState


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
        return self.decision_kind in {"resume_exact", "resume_subset"}


def build_startup_identity_metadata(
    runtime: Any,
    *,
    runtime_mode: str,
    project_contexts: list[object],
    base_metadata: Mapping[str, object] | None = None,
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
    identity_payload = _startup_identity_payload(runtime, runtime_mode=runtime_mode, project_contexts=project_contexts)
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

    current_identity = _startup_identity_payload(runtime, runtime_mode=runtime_mode, project_contexts=contexts)
    previous_identity = candidate.metadata.get("startup_identity")
    if isinstance(previous_identity, dict):
        if str(previous_identity.get("fingerprint", "")).strip() != str(current_identity.get("fingerprint", "")).strip():
            return RunReuseDecision(
                candidate_state=candidate,
                decision_kind="fresh_run",
                reason="startup_fingerprint_mismatch",
                selected_projects=selected_payload,
                state_projects=state_payload,
                startup_enabled=startup_enabled,
            )

    weak_identity = any(identity.root is None for identity in state_identities)
    selected_keys = _identity_keys(selected_identities, weak=weak_identity)
    state_keys = _identity_keys(state_identities, weak=weak_identity)
    exact_match = selected_keys == state_keys
    subset_match = runtime_mode == "trees" and selected_keys.issubset(state_keys)
    expand_match = runtime_mode == "trees" and route.command == "plan" and state_keys.issubset(selected_keys)

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
        reason="project_selection_mismatch",
        selected_projects=selected_payload,
        state_projects=state_payload,
        weak_identity=weak_identity,
        startup_enabled=startup_enabled,
    )


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


def _startup_identity_payload(runtime: Any, *, runtime_mode: str, project_contexts: list[object]) -> dict[str, object]:
    startup_enabled = _startup_enabled(runtime, runtime_mode)
    services = {
        "backend": _service_enabled(runtime, runtime_mode, "backend"),
        "frontend": _service_enabled(runtime, runtime_mode, "frontend"),
    }
    dependencies = [
        dependency_id
        for dependency_id in sorted(dependency_ids())
        if _requirement_enabled(runtime, runtime_mode, dependency_id)
    ]
    if not startup_enabled:
        dependencies = []
    payload = {
        "mode": runtime_mode,
        "projects": identities_to_payload(project_identities_from_contexts(project_contexts)),
        "startup_enabled": startup_enabled,
        "services": services,
        "dependencies": dependencies,
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
