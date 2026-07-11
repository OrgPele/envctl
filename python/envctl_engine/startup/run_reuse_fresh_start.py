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
    target_projects = {str(getattr(context, "name", "")).strip().lower() for context in selected_contexts}
    target_projects.discard("")
    if not target_projects:
        return set()
    selected_by_project = {
        str(getattr(context, "name", "")).strip().lower(): _restart_service_types_for_project(
            route=route,
            project_name=str(getattr(context, "name", "")),
            default_service_types=configured_service_types,
            additional_services=additional_services,
        )
        for context in selected_contexts
        if str(getattr(context, "name", "")).strip()
    }
    runtime_scope = str(route.flags.get("runtime_scope") or "").strip().lower()
    has_app_launch_selection = any(key in route.flags for key in ("launch_backend", "launch_frontend"))
    replace_all_for_explicit_fresh_start = (
        bool(route.flags.get("no_resume"))
        and not bool(route.flags.get("services"))
        and not has_app_launch_selection
        and runtime_scope not in {"backend", "frontend", "dependencies", "fullstack"}
    )
    selected: set[str] = set()
    for service_name, service in getattr(candidate_state, "services", {}).items():
        project = service_project_name(service) or project_name_from_service(service_name)
        project_key = str(project).strip().lower()
        if project_key not in target_projects:
            continue
        if replace_all_for_explicit_fresh_start:
            selected.add(service_name)
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
        if self.reason not in {"explicit_no_resume", "startup_fingerprint_mismatch"}:
            return
        route = self.session.effective_route
        if route.flags.get("runtime_scope") == "dependencies":
            return
        selected_services = self.fresh_start_replacement_services(self.session, candidate_state=self.candidate_state)
        if not selected_services:
            return
        self.announce_session_identifiers(self.session)
        message = (
            f"Fresh start requested; replacing {len(selected_services)} existing service(s)..."
            if self.reason == "explicit_no_resume"
            else f"Startup selection changed; replacing {len(selected_services)} existing service(s)..."
        )
        self.report_progress(route, message)
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
        self._rebind_replacement_ports(selected_services)

    def _rebind_replacement_ports(self, selected_services: set[str]) -> None:
        port_planner = getattr(self.runtime, "port_planner", None)
        release = getattr(port_planner, "release", None)
        if not callable(release):
            return
        contexts = {
            str(getattr(context, "name", "")).casefold(): context
            for context in getattr(self.session, "selected_contexts", [])
        }
        for name in sorted(selected_services):
            service = getattr(self.candidate_state, "services", {}).get(name)
            if service is None or not bool(getattr(service, "listener_expected", True)):
                continue
            project = service_project_name(service) or self.runtime._project_name_from_service(name)
            service_type = service_slug_from_record(service)
            context = contexts.get(str(project).casefold())
            plans = getattr(context, "ports", {}) if context is not None else {}
            plan = plans.get(service_type) if service_type else None
            old_port = getattr(service, "actual_port", None) or getattr(service, "requested_port", None)
            current_port = getattr(plan, "final", None)
            if plan is None or not isinstance(old_port, int) or old_port <= 0:
                continue
            owner = f"{getattr(context, 'name', project)}:{service_type}"
            if isinstance(current_port, int) and current_port > 0:
                release(current_port, owner=owner)
            plan.assigned = old_port
            plan.final = old_port
            plan.source = "fresh_start_replacement"
            self.runtime._emit(
                "port.rebound.after_fresh_start_cleanup",
                project=project,
                service=service_type,
                previous_port=old_port,
                port=old_port,
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
