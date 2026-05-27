from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.services import service_project_name, service_slug_from_record
from envctl_engine.startup.startup_selection_support import _restart_service_types_for_project


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


@dataclass(frozen=True, slots=True)
class FreshStartServiceReplacer:
    runtime: Any
    session: Any
    candidate_state: Any
    reason: str
    fresh_start_replacement_services: Callable[..., set[str]]
    announce_session_identifiers: Callable[[Any], None]
    report_progress: Callable[[Route, str], None]
    terminate_restart_orphan_listeners: Callable[..., None]

    def replace(self) -> None:
        if self.reason != "startup_fingerprint_mismatch":
            return
        route = self.session.effective_route
        if route.flags.get("runtime_scope") == "dependencies":
            return
        selected_services = self.fresh_start_replacement_services(self.session, candidate_state=self.candidate_state)
        if not selected_services:
            return
        self.announce_session_identifiers(self.session)
        self.report_progress(
            route,
            f"Startup selection changed; replacing {len(selected_services)} existing service(s)...",
        )
        self.runtime._emit(
            "state.run_reuse.replace_existing_services",
            run_id=self.candidate_state.run_id,
            mode=self.session.runtime_mode,
            reason=self.reason,
            selected_services=sorted(selected_services),
        )
        self.runtime._terminate_services_from_state(
            self.candidate_state,
            selected_services=selected_services,
            aggressive=False,
            verify_ownership=True,
        )
        self.terminate_restart_orphan_listeners(
            state=self.candidate_state,
            selected_services=selected_services,
            aggressive=True,
        )


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
    FreshStartServiceReplacer(
        runtime=runtime,
        session=session,
        candidate_state=candidate_state,
        reason=reason,
        fresh_start_replacement_services=fresh_start_replacement_services,
        announce_session_identifiers=announce_session_identifiers,
        report_progress=report_progress,
        terminate_restart_orphan_listeners=terminate_restart_orphan_listeners,
    ).replace()


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
