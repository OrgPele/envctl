from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.run_reuse_decision import mark_run_reused


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


@dataclass(frozen=True, slots=True)
class DashboardStoppedServiceRestorer:
    runtime: Any
    session: Any
    candidate_state: Any
    reuse_started: float
    decision_kind: str
    emit_phase: Callable[..., None]

    def prepare(self) -> bool:
        restore_entries = self._restore_entries()
        if not restore_entries:
            return False
        contexts_to_start = self._contexts_to_start(restore_entries)
        if not contexts_to_start:
            return False
        self._apply_restore(restore_entries=restore_entries, contexts_to_start=contexts_to_start)
        return True

    def _restore_entries(self) -> list[dict[str, str]]:
        active_service_names = set(self.candidate_state.services)
        stopped_entries = [
            entry
            for entry in dashboard_stopped_service_entries(self.candidate_state)
            if entry["name"] not in active_service_names
        ]
        if not stopped_entries:
            return []
        selected_keys = {
            str(context.name).strip().casefold()
            for context in self.session.selected_contexts
            if str(getattr(context, "name", "")).strip()
        }
        return [entry for entry in stopped_entries if entry["project"].casefold() in selected_keys]

    def _contexts_to_start(self, restore_entries: list[dict[str, str]]) -> list[object]:
        target_project_keys = {entry["project"].casefold() for entry in restore_entries}
        selected_context_by_name = {
            str(context.name).strip().casefold(): context
            for context in self.session.selected_contexts
            if str(getattr(context, "name", "")).strip()
        }
        return [context for key, context in selected_context_by_name.items() if key in target_project_keys]

    def _apply_restore(self, *, restore_entries: list[dict[str, str]], contexts_to_start: list[object]) -> None:
        stopped_service_names = sorted({entry["name"] for entry in restore_entries})
        stopped_service_types = sorted({entry["type"] for entry in restore_entries})
        target_project_names = sorted({entry["project"] for entry in restore_entries}, key=str.casefold)
        self.session.base_metadata = metadata_without_dashboard_stopped_services(
            mark_run_reused(self.candidate_state.metadata, reason="restore_stopped_services"),
            restored_service_names=set(stopped_service_names),
        )
        self.session.preserved_services = dict(self.candidate_state.services)
        self.session.preserved_requirements = dict(self.candidate_state.requirements)
        self.session.contexts_to_start = contexts_to_start
        self._apply_restart_route(
            target_project_names=target_project_names,
            stopped_service_names=stopped_service_names,
            stopped_service_types=stopped_service_types,
        )
        self._emit_restore(
            target_project_names=target_project_names,
            stopped_service_names=stopped_service_names,
        )

    def _apply_restart_route(
        self,
        *,
        target_project_names: list[str],
        stopped_service_names: list[str],
        stopped_service_types: list[str],
    ) -> None:
        route = self.session.effective_route
        self.session.effective_route = Route(
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

    def _emit_restore(self, *, target_project_names: list[str], stopped_service_names: list[str]) -> None:
        route = self.session.effective_route
        self.emit_phase(
            self.session,
            "auto_resume_evaluate",
            self.reuse_started,
            status="restore_stopped_services",
            match_mode="exact" if self.decision_kind == "resume_exact" else "subset",
            stopped_service_count=len(stopped_service_names),
            target_projects=target_project_names,
        )
        self.runtime._emit(
            "state.auto_resume.restore_stopped_services",
            run_id=self.candidate_state.run_id,
            mode=self.session.runtime_mode,
            command=route.command,
            projects=target_project_names,
            services=stopped_service_names,
        )
        self.runtime._emit(
            "state.run_reuse.applied",
            run_id=self.candidate_state.run_id,
            mode=self.session.runtime_mode,
            command=route.command,
            decision_kind="restore_stopped_services",
            reason="dashboard_stopped_services",
            restored_projects=target_project_names,
            restored_services=stopped_service_names,
        )


def prepare_dashboard_stopped_service_restore(
    *,
    runtime: Any,
    session: Any,
    candidate_state: Any,
    reuse_started: float,
    decision_kind: str,
    emit_phase: Callable[..., None],
) -> bool:
    return DashboardStoppedServiceRestorer(
        runtime=runtime,
        session=session,
        candidate_state=candidate_state,
        reuse_started=reuse_started,
        decision_kind=decision_kind,
        emit_phase=emit_phase,
    ).prepare()


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
