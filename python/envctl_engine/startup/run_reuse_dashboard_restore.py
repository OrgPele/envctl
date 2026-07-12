from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from envctl_engine.dashboard_metadata import normalize_dashboard_service_types
from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.services import service_display_name
from envctl_engine.startup.run_reuse_decision import mark_run_reused
from envctl_engine.startup.session import metadata_with_state_sources


def dashboard_stopped_service_entries(state: object) -> list[dict[str, str]]:
    raw = getattr(state, "metadata", {}).get("dashboard_stopped_services")
    if not isinstance(raw, list):
        return []
    entries: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        project = str(item.get("project", "") or "").strip()
        normalized_types = normalize_dashboard_service_types([item.get("type", "")])
        service_type = normalized_types[0] if normalized_types else ""
        name = str(item.get("name", "") or "").strip()
        if not project or not service_type:
            continue
        entries.append(
            {
                "project": project,
                "type": service_type,
                "name": name or f"{project} {service_display_name(service_type)}",
            }
        )
    return entries


def metadata_without_dashboard_stopped_services(
    metadata: Mapping[str, object],
    *,
    restored_service_names: set[str] | None = None,
    restored_service_types_by_project: Mapping[str, object] | None = None,
) -> dict[str, object]:
    updated = dict(metadata)
    raw = updated.get("dashboard_stopped_services")
    if not isinstance(raw, list):
        return updated
    restored_names = {
        str(selector).strip().casefold().removeprefix("service:").strip()
        for selector in (restored_service_names or set())
        if str(selector).strip()
    }
    restored_types = {
        str(project).strip().casefold(): set(normalize_dashboard_service_types(service_types))
        for project, service_types in (restored_service_types_by_project or {}).items()
        if str(project).strip() and isinstance(service_types, (list, tuple, set, frozenset))
    }
    remaining: list[object] = []
    for item in raw:
        if not isinstance(item, Mapping):
            remaining.append(item)
            continue
        name = str(item.get("name", "") or "").strip()
        project = str(item.get("project", "") or "").strip()
        service_type = str(item.get("type", "") or "").strip().lower()
        if name.casefold() in restored_names or service_type in restored_types.get(project.casefold(), set()):
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
        self.session.base_metadata = metadata_with_state_sources(
            mark_run_reused(self.candidate_state.metadata, reason="restore_stopped_services"),
            self.candidate_state,
        )
        self.session.preserved_services = dict(self.candidate_state.services)
        self.session.preserved_requirements = dict(self.candidate_state.requirements)
        self.session.contexts_to_start = contexts_to_start
        self._apply_restart_route(
            target_project_names=target_project_names,
            stopped_service_names=stopped_service_names,
            stopped_service_types=stopped_service_types,
            stopped_service_types_by_project={
                project: sorted(
                    {
                        entry["type"]
                        for entry in restore_entries
                        if entry["project"].casefold() == project.casefold()
                    }
                )
                for project in target_project_names
            },
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
        stopped_service_types_by_project: dict[str, list[str]],
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
                "_restart_service_types_by_project": stopped_service_types_by_project,
                "restart_include_requirements": False,
            },
        )

    def _emit_restore(self, *, target_project_names: list[str], stopped_service_names: list[str]) -> None:
        route = self.session.effective_route
        diagnostics = (
            lambda: self.emit_phase(
                self.session,
                "auto_resume_evaluate",
                self.reuse_started,
                status="restore_stopped_services",
                match_mode="exact" if self.decision_kind == "resume_exact" else "subset",
                stopped_service_count=len(stopped_service_names),
                target_projects=target_project_names,
            ),
            lambda: self.runtime._emit(
                "state.auto_resume.restore_stopped_services",
                run_id=self.candidate_state.run_id,
                mode=self.session.runtime_mode,
                command=route.command,
                projects=target_project_names,
                services=stopped_service_names,
            ),
            lambda: self.runtime._emit(
                "state.run_reuse.applied",
                run_id=self.candidate_state.run_id,
                mode=self.session.runtime_mode,
                command=route.command,
                decision_kind="restore_stopped_services",
                reason="dashboard_stopped_services",
                restored_projects=target_project_names,
                restored_services=stopped_service_names,
            ),
        )
        for diagnostic in diagnostics:
            try:
                diagnostic()
            except Exception:  # noqa: BLE001
                pass


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
