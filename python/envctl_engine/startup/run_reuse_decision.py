from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Mapping

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.startup.run_reuse_identity import (
    ProjectIdentity,
    _auto_resume_start_enabled,
    _identity_keys,
    _root_mismatches,
    _startup_enabled,
    _startup_identity_mismatch,
    _startup_identity_payload,
    identities_to_payload,
    project_identities_from_contexts,
    project_identities_from_state,
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


@dataclass(frozen=True, slots=True)
class RunReuseEvaluator:
    runtime: Any
    runtime_mode: str
    route: Route
    contexts: tuple[object, ...]

    def evaluate(self) -> RunReuseDecision:
        selected_identities = project_identities_from_contexts(list(self.contexts))
        selected_payload = identities_to_payload(selected_identities)
        startup_enabled = _startup_enabled(self.runtime, self.runtime_mode)
        if not selected_identities:
            return self._fresh_without_state(
                reason="no_selected_projects",
                selected_payload=selected_payload,
                startup_enabled=startup_enabled,
            )
        if not _auto_resume_start_enabled(self.route):
            if bool(self.route.flags.get("no_resume")):
                candidate = self.runtime._try_load_existing_state(
                    mode=self.runtime_mode,
                    strict_mode_match=True,
                )
                if candidate is not None:
                    state_identities = project_identities_from_state(self.runtime, candidate)
                    return RunReuseDecision(
                        candidate_state=candidate,
                        decision_kind="fresh_run",
                        reason="explicit_no_resume",
                        selected_projects=selected_payload,
                        state_projects=identities_to_payload(state_identities),
                        startup_enabled=startup_enabled,
                    )
            return self._fresh_without_state(
                reason="auto_resume_disabled",
                selected_payload=selected_payload,
                startup_enabled=startup_enabled,
            )

        candidate = self.runtime._try_load_existing_state(mode=self.runtime_mode, strict_mode_match=True)
        if candidate is None:
            return self._fresh_without_state(
                reason="no_matching_state",
                selected_payload=selected_payload,
                startup_enabled=startup_enabled,
            )
        return self._evaluate_candidate(
            candidate=candidate,
            selected_identities=selected_identities,
            selected_payload=selected_payload,
            startup_enabled=startup_enabled,
        )

    def _fresh_without_state(
        self,
        *,
        reason: str,
        selected_payload: list[dict[str, str | None]],
        startup_enabled: bool,
    ) -> RunReuseDecision:
        return RunReuseDecision(
            candidate_state=None,
            decision_kind="fresh_run",
            reason=reason,
            selected_projects=selected_payload,
            state_projects=[],
            startup_enabled=startup_enabled,
        )

    def _evaluate_candidate(
        self,
        *,
        candidate: RunState,
        selected_identities: list[ProjectIdentity],
        selected_payload: list[dict[str, str | None]],
        startup_enabled: bool,
    ) -> RunReuseDecision:
        state_identities = project_identities_from_state(self.runtime, candidate)
        state_payload = identities_to_payload(state_identities)
        initial_rejection = self._initial_candidate_rejection(
            candidate=candidate,
            selected_payload=selected_payload,
            state_payload=state_payload,
            startup_enabled=startup_enabled,
        )
        if initial_rejection is not None:
            return initial_rejection

        root_mismatches = _root_mismatches(selected_identities, state_identities)
        if root_mismatches:
            return self._candidate_fresh(
                candidate=candidate,
                reason="project_root_mismatch",
                selected_payload=selected_payload,
                state_payload=state_payload,
                startup_enabled=startup_enabled,
                mismatch_details={"projects": sorted(root_mismatches)},
            )

        weak_identity = any(identity.root is None for identity in state_identities)
        selected_keys = _identity_keys(selected_identities, weak=weak_identity)
        state_keys = _identity_keys(state_identities, weak=weak_identity)
        exact_match = selected_keys == state_keys
        subset_match = self.runtime_mode == "trees" and selected_keys.issubset(state_keys)
        expand_match = (
            self.runtime_mode == "trees"
            and self.route.command in {"start", "plan"}
            and state_keys.issubset(selected_keys)
        )
        if not (exact_match or subset_match or expand_match):
            return self._candidate_fresh(
                candidate=candidate,
                reason="project_selection_mismatch",
                selected_payload=selected_payload,
                state_payload=state_payload,
                weak_identity=weak_identity,
                startup_enabled=startup_enabled,
            )

        identity_mismatch = self._startup_identity_mismatch(candidate, state_identities)
        if identity_mismatch:
            return self._candidate_fresh(
                candidate=candidate,
                reason="startup_fingerprint_mismatch",
                selected_payload=selected_payload,
                state_payload=state_payload,
                mismatch_details=identity_mismatch,
                weak_identity=weak_identity,
                startup_enabled=startup_enabled,
            )

        return self._matching_candidate_decision(
            candidate=candidate,
            exact_match=exact_match,
            subset_match=subset_match,
            expand_match=expand_match,
            selected_payload=selected_payload,
            state_payload=state_payload,
            weak_identity=weak_identity,
            startup_enabled=startup_enabled,
        )

    def _initial_candidate_rejection(
        self,
        *,
        candidate: RunState,
        selected_payload: list[dict[str, str | None]],
        state_payload: list[dict[str, str | None]],
        startup_enabled: bool,
    ) -> RunReuseDecision | None:
        if candidate.mode != self.runtime_mode:
            return self._candidate_fresh(
                candidate=candidate,
                reason="mode_mismatch",
                selected_payload=selected_payload,
                state_payload=state_payload,
                startup_enabled=startup_enabled,
            )
        if bool(candidate.metadata.get("failed", False)):
            return self._candidate_fresh(
                candidate=candidate,
                reason="failed_state",
                selected_payload=selected_payload,
                state_payload=state_payload,
                startup_enabled=startup_enabled,
            )
        if not state_payload:
            return self._candidate_fresh(
                candidate=candidate,
                reason="project_selection_mismatch",
                selected_payload=selected_payload,
                state_payload=state_payload,
                startup_enabled=startup_enabled,
            )
        return None

    def _startup_identity_mismatch(
        self,
        candidate: RunState,
        state_identities: list[ProjectIdentity],
    ) -> dict[str, object]:
        previous_identity = candidate.metadata.get("startup_identity")
        if not isinstance(previous_identity, dict):
            return {}
        state_identity_under_current_runtime = _startup_identity_payload(
            self.runtime,
            runtime_mode=self.runtime_mode,
            project_contexts=list(state_identities),
            route=self.route,
        )
        return _startup_identity_mismatch(previous_identity, state_identity_under_current_runtime)

    def _matching_candidate_decision(
        self,
        *,
        candidate: RunState,
        exact_match: bool,
        subset_match: bool,
        expand_match: bool,
        selected_payload: list[dict[str, str | None]],
        state_payload: list[dict[str, str | None]],
        weak_identity: bool,
        startup_enabled: bool,
    ) -> RunReuseDecision:
        if exact_match:
            if state_has_resumable_services(self.runtime, candidate):
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
        if subset_match and state_has_resumable_services(self.runtime, candidate):
            return self._reuse(
                candidate=candidate,
                decision_kind="resume_subset",
                reason="subset_match",
                selected_payload=selected_payload,
                state_payload=state_payload,
                weak_identity=weak_identity,
                startup_enabled=startup_enabled,
            )
        if expand_match and state_has_resumable_services(self.runtime, candidate):
            return self._reuse(
                candidate=candidate,
                decision_kind="reuse_expand",
                reason="expand_match",
                selected_payload=selected_payload,
                state_payload=state_payload,
                weak_identity=weak_identity,
                startup_enabled=startup_enabled,
            )
        return self._candidate_fresh(
            candidate=candidate,
            reason="no_reusable_runtime",
            selected_payload=selected_payload,
            state_payload=state_payload,
            weak_identity=weak_identity,
            startup_enabled=startup_enabled,
        )

    def _reuse(
        self,
        *,
        candidate: RunState,
        decision_kind: str,
        reason: str,
        selected_payload: list[dict[str, str | None]],
        state_payload: list[dict[str, str | None]],
        weak_identity: bool,
        startup_enabled: bool,
    ) -> RunReuseDecision:
        return RunReuseDecision(
            candidate_state=candidate,
            decision_kind=decision_kind,
            reason=reason,
            selected_projects=selected_payload,
            state_projects=state_payload,
            weak_identity=weak_identity,
            startup_enabled=startup_enabled,
        )

    def _candidate_fresh(
        self,
        *,
        candidate: RunState,
        reason: str,
        selected_payload: list[dict[str, str | None]],
        state_payload: list[dict[str, str | None]],
        mismatch_details: dict[str, object] | None = None,
        weak_identity: bool = False,
        startup_enabled: bool,
    ) -> RunReuseDecision:
        return RunReuseDecision(
            candidate_state=candidate,
            decision_kind="fresh_run",
            reason=reason,
            selected_projects=selected_payload,
            state_projects=state_payload,
            mismatch_details=mismatch_details or {},
            weak_identity=weak_identity,
            startup_enabled=startup_enabled,
        )


def mark_run_reused(metadata: Mapping[str, object] | None, *, reason: str) -> dict[str, object]:
    updated = dict(metadata or {})
    raw_count = updated.get("run_reuse_count", 0)
    count = int(raw_count) if isinstance(raw_count, (bool, float, int, str)) else 0
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
    return RunReuseEvaluator(
        runtime=runtime,
        runtime_mode=runtime_mode,
        route=route,
        contexts=tuple(contexts),
    ).evaluate()


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
