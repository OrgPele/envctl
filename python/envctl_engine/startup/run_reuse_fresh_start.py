from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.services import service_project_name
from envctl_engine.startup.session import metadata_with_state_sources


def fresh_start_replacement_services(
    *,
    selected_contexts: list[object],
    candidate_state: object,
    project_name_from_service: Callable[[str], str],
) -> set[str]:
    """Select every old service owned by a project that is starting fresh."""

    target_projects = {str(context.name).strip().casefold() for context in selected_contexts}
    target_projects.discard("")
    if not target_projects:
        return set()
    return {
        service_name
        for service_name, service in getattr(candidate_state, "services", {}).items()
        if str(service_project_name(service) or project_name_from_service(service_name)).strip().casefold()
        in target_projects
    }


@dataclass(frozen=True, slots=True)
class FreshStartServiceReplacer:
    runtime: Any
    session: Any
    candidate_state: Any
    reason: str
    announce_session_identifiers: Callable[[Any], None]
    report_progress: Callable[[Route, str], None]
    terminate_restart_orphan_listeners: Callable[..., set[int]]

    def replace(self) -> None:
        route = self.session.effective_route
        dependencies_only = route.flags.get("runtime_scope") == "dependencies"
        selected_services = (
            set()
            if dependencies_only
            else fresh_start_replacement_services(
                selected_contexts=list(self.session.selected_contexts),
                candidate_state=self.candidate_state,
                project_name_from_service=self.runtime._project_name_from_service,
            )
        )
        target_projects = {
            str(context.name).strip().casefold()
            for context in self.session.selected_contexts
            if str(context.name).strip()
        }
        preserved_services = (
            dict(self.candidate_state.services)
            if dependencies_only
            else {
                name: service
                for name, service in self.candidate_state.services.items()
                if name not in selected_services
            }
        )
        preserved_requirements, requirements_to_release = _split_requirements(
            self.candidate_state,
            target_projects=target_projects,
        )
        if selected_services:
            self.announce_session_identifiers(self.session)
            progress_message = (
                f"Auto-resume disabled; replacing {len(selected_services)} existing service(s)..."
                if self.reason == "explicit_no_resume"
                else f"Startup selection changed; replacing {len(selected_services)} existing service(s)..."
            )
            self.report_progress(route, progress_message)
        self.runtime._emit(
            "state.run_reuse.replace_existing_services",
            run_id=self.candidate_state.run_id,
            mode=self.session.runtime_mode,
            reason=self.reason,
            selected_services=sorted(selected_services),
        )
        if selected_services:
            termination_result = self.runtime._terminate_services_from_state(
                self.candidate_state,
                selected_services=selected_services,
                aggressive=False,
                verify_ownership=True,
            )
            failed_services = _failed_service_names(termination_result)
            if failed_services:
                self.session.preserve_existing_state_on_failure = True
                raise RuntimeError(
                    "Fresh start aborted because existing services could not be stopped: "
                    + ", ".join(sorted(failed_services))
                )
            failed_orphan_pids = self.terminate_restart_orphan_listeners(
                state=self.candidate_state,
                selected_services=selected_services,
                aggressive=True,
            )
            if failed_orphan_pids:
                self.session.preserve_existing_state_on_failure = True
                raise RuntimeError(
                    "Fresh start aborted because orphan listeners could not be stopped: "
                    + ", ".join(str(pid) for pid in sorted(failed_orphan_pids))
                )
        for requirements in requirements_to_release.values():
            self.runtime._release_requirement_ports(requirements)
        self.session.preserved_services = preserved_services
        self.session.preserved_requirements = preserved_requirements
        self.session.base_metadata = metadata_with_state_sources(
            {
                **dict(self.candidate_state.metadata),
                **dict(self.session.base_metadata),
            },
            self.candidate_state,
        )


def replace_existing_project_services_for_fresh_start(
    *,
    runtime: Any,
    session: Any,
    candidate_state: Any,
    reason: str,
    announce_session_identifiers: Callable[[Any], None],
    report_progress: Callable[[Route, str], None],
    terminate_restart_orphan_listeners: Callable[..., set[int]],
) -> None:
    FreshStartServiceReplacer(
        runtime=runtime,
        session=session,
        candidate_state=candidate_state,
        reason=reason,
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
    announce_session_identifiers: Callable[[Any], None],
    report_progress: Callable[[Route, str], None],
    terminate_restart_orphan_listeners: Callable[..., set[int]],
) -> None:
    replace_existing_project_services_for_fresh_start(
        runtime=runtime,
        session=session,
        candidate_state=candidate_state,
        reason=reason,
        announce_session_identifiers=announce_session_identifiers,
        report_progress=report_progress,
        terminate_restart_orphan_listeners=terminate_restart_orphan_listeners,
    )


def _split_requirements(
    state: object,
    *,
    target_projects: set[str],
) -> tuple[dict[str, object], dict[str, object]]:
    preserved: dict[str, object] = {}
    replaced: dict[str, object] = {}
    for name, requirements in getattr(state, "requirements", {}).items():
        project = str(getattr(requirements, "project", "") or name).strip().casefold()
        destination = replaced if project in target_projects else preserved
        destination[name] = requirements
    return preserved, replaced


def _failed_service_names(result: object) -> set[str]:
    if not isinstance(result, (set, frozenset)):
        return set()
    return {str(name).strip() for name in result if str(name).strip()}
