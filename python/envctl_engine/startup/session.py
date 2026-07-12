from __future__ import annotations

from collections.abc import Collection, Mapping
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, cast

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord

if TYPE_CHECKING:
    from envctl_engine.planning.plan_agent.models import (
        CreatedPlanWorktree,
        PlanAgentAttachTarget,
        PlanAgentLaunchResult,
    )
    from envctl_engine.startup.protocols import ProjectContextLike


@dataclass(slots=True)
class ProjectStartupResult:
    requirements: RequirementsResult
    services: dict[str, ServiceRecord]
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class LocalStartupFailure:
    project: str
    error: str
    reason: str

    def to_metadata(self) -> dict[str, str]:
        return {
            "project": self.project,
            "error": self.error,
            "reason": self.reason,
        }


@dataclass(slots=True)
class StartupSession:
    requested_route: Route
    effective_route: Route
    requested_command: str
    runtime_mode: str
    run_id: str | None
    startup_started_at: float = field(default_factory=time.monotonic)
    startup_event_index: int = 0
    selected_contexts: list[ProjectContextLike] = field(default_factory=list)
    contexts_to_start: list[ProjectContextLike] = field(default_factory=list)
    resumed_context_names: list[str] = field(default_factory=list)
    preserved_services: dict[str, ServiceRecord] = field(default_factory=dict)
    preserved_requirements: dict[str, RequirementsResult] = field(default_factory=dict)
    restart_state: RunState | None = None
    requirements_by_project: dict[str, RequirementsResult] = field(default_factory=dict)
    services_by_project: dict[str, dict[str, ServiceRecord]] = field(default_factory=dict)
    unterminated_services: dict[str, ServiceRecord] = field(default_factory=dict)
    started_context_names: list[str] = field(default_factory=list)
    dashboard_after_start: bool = False
    disabled_startup_mode: bool = False
    used_project_spinner_group: bool = False
    strict_truth_failed: bool = False
    authority_committed: bool = False
    preserve_existing_state_on_failure: bool = False
    service_state_collisions: set[str] = field(default_factory=set)
    service_state_collision_rows: list[dict[str, object]] = field(default_factory=list)
    requirement_state_collision_rows: list[dict[str, object]] = field(default_factory=list)
    failure_message: str | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    debug_plan_snapshot: bool = False
    base_metadata: dict[str, Any] = field(default_factory=dict)
    identifiers_announced: bool = False
    plan_agent_attach_target: PlanAgentAttachTarget | None = None
    plan_agent_launch_result: PlanAgentLaunchResult | None = None
    plan_agent_launch_requested: bool = False
    pending_plan_agent_worktrees: tuple[CreatedPlanWorktree, ...] = ()
    plan_agent_dependency_bootstrap_results: tuple[Any, ...] = ()
    plan_agent_handoff_degraded: bool = False
    plan_agent_stale_session_name: str = ""
    plan_agent_stale_attach_command: str = ""
    plan_agent_handoff_validation_reason: str = ""
    plan_agent_recovery_command: str = ""
    local_startup_failures: list[LocalStartupFailure] = field(default_factory=list)

    @property
    def merged_services(self) -> dict[str, ServiceRecord]:
        replacement_names = set(self.unterminated_services)
        for project_services in self.services_by_project.values():
            replacement_names.update(project_services)
        collisions = sorted(set(self.preserved_services).intersection(replacement_names))
        if collisions:
            self.service_state_collisions.update(collisions)
            self.preserve_existing_state_on_failure = True
            raise RuntimeError(
                "Refusing to overwrite preserved service state with newly started services: "
                + ", ".join(collisions)
            )
        services = dict(self.preserved_services)
        for project_services in self.services_by_project.values():
            services.update(project_services)
        services.update(self.unterminated_services)
        return services

    @property
    def merged_requirements(self) -> dict[str, RequirementsResult]:
        requirements = dict(self.preserved_requirements)
        collisions: list[str] = []
        for project, replacement in self.requirements_by_project.items():
            # App-only restart reuses the exact persisted RequirementsResult.
            # Its durable storage key can be a collision alias, while project
            # startup naturally reports the canonical project name. Retain the
            # existing storage identity instead of serializing the same stack
            # twice under two keys.
            if any(existing is replacement for existing in requirements.values()):
                continue
            preserved_key = _preserved_requirement_key(requirements, project)
            preserved = requirements.get(preserved_key) if preserved_key is not None else None
            if preserved is not None and preserved == replacement:
                # Preserve the existing storage key, including a collision
                # alias, when deserialization produced an equal object.
                continue
            if (
                preserved is not None
                and self.effective_route.flags.get("launch_dependencies") is False
                and not _requirements_have_enabled_components(replacement)
            ):
                # App-only and no-infrastructure starts still return a
                # RequirementsResult containing disabled port projections.
                # Those projections do not own resources and must not collide
                # with, duplicate, or replace the preserved dependency stack.
                continue
            if preserved is not None:
                collisions.append(project)
                continue
            requirements[project] = replacement
        if collisions:
            self.preserve_existing_state_on_failure = True
            raise RuntimeError(
                "Refusing to overwrite preserved requirement state with newly started requirements: "
                + ", ".join(sorted(collisions))
            )
        return requirements

    @property
    def plan_agent_session_started(self) -> bool:
        if self.plan_agent_attach_target is not None:
            return True
        launch_result = self.plan_agent_launch_result
        if launch_result is None:
            return False
        status = str(getattr(launch_result, "status", "")).strip().lower()
        if status not in {"launched", "partial"}:
            return False
        outcomes = tuple(cast(tuple[object, ...], getattr(launch_result, "outcomes", ()) or ()))
        if not outcomes:
            return status == "launched"
        return any(str(getattr(outcome, "status", "")).strip().lower() == "launched" for outcome in outcomes)

    @property
    def plan_agent_launch_degraded(self) -> bool:
        launch_result = self.plan_agent_launch_result
        if launch_result is None:
            return False
        return str(getattr(launch_result, "status", "")).strip().lower() == "partial"


def unconfirmed_service_names(
    termination_result: object,
    services: Mapping[str, object],
) -> set[str]:
    """Return services whose exit was not positively confirmed.

    The termination contract returns a collection of names that remain alive;
    an explicit empty collection therefore confirms complete cleanup. Legacy
    adapters and failed mocks may return ``None`` or another scalar. Treating
    those values as success loses process and port ownership, so they retain
    every service for a later verified cleanup pass.
    """

    if not isinstance(termination_result, Collection) or isinstance(
        termination_result,
        (str, bytes, Mapping),
    ):
        return set(services)
    raw_reported = list(termination_result)
    if any(not str(raw_name).strip() for raw_name in raw_reported):
        return set(services)
    reported = {str(raw_name).strip() for raw_name in raw_reported}
    if not reported.issubset(services):
        # An adapter that reports an unknown identity has not positively
        # confirmed the disposition of any tracked process. Fail closed so a
        # stale/case-mismatched name cannot make every real service disappear
        # from the durable recovery state.
        return set(services)
    return reported


def _preserved_requirement_key(
    requirements: Mapping[str, RequirementsResult],
    project: str,
) -> str | None:
    target = str(project).strip().casefold()
    exact = [key for key in requirements if str(key).strip().casefold() == target]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise RuntimeError(
            f"Ambiguous preserved requirements authority for {project}: "
            + ", ".join(sorted(exact))
        )
    aliases = [
        key
        for key, value in requirements.items()
        if str(getattr(value, "project", "") or "").strip().casefold() == target
    ]
    if len(aliases) == 1:
        return aliases[0]
    if len(aliases) > 1:
        raise RuntimeError(
            f"Ambiguous preserved requirements authority for {project}: "
            + ", ".join(sorted(aliases))
        )
    return None


def _requirements_have_enabled_components(requirements: RequirementsResult) -> bool:
    return any(
        bool(component.get("enabled", False))
        for component in requirements.components.values()
        if isinstance(component, Mapping)
    )


def metadata_with_state_sources(metadata: dict[str, Any], state: RunState) -> dict[str, Any]:
    """Return metadata that records every state replaced by a new startup run."""

    updated = dict(metadata)
    source_run_ids = {state.run_id}
    for source in (
        updated.get("state_source_run_ids"),
        state.metadata.get("state_source_run_ids"),
    ):
        if not isinstance(source, list):
            continue
        source_run_ids.update(str(run_id).strip() for run_id in source if str(run_id).strip())
    updated["state_source_run_ids"] = sorted(source_run_ids)
    return updated


def track_startup_failure(session: StartupSession, failure: BaseException) -> None:
    project = str(getattr(failure, "project", "") or "").strip()
    requirements = getattr(failure, "requirements", None)
    if project and isinstance(requirements, RequirementsResult):
        requirement_key = project
        if project in session.requirements_by_project:
            occupied_projects = set(session.preserved_requirements).union(session.requirements_by_project)
            base = f"{project} Restart Collision"
            requirement_key = base
            index = 2
            while requirement_key in occupied_projects:
                requirement_key = f"{base} {index}"
                index += 1
            session.requirement_state_collision_rows.append(
                {
                    "original_project": project,
                    "replacement_project": requirement_key,
                    "replacement_requirements_retained": True,
                }
            )
        session.requirements_by_project[requirement_key] = requirements
    services = getattr(failure, "unterminated_services", None)
    if not isinstance(services, dict):
        return
    occupied_names = set(session.preserved_services).union(session.unterminated_services)
    for project_services in session.services_by_project.values():
        occupied_names.update(project_services)
    tracked_identities = {
        id(service)
        for service in session.unterminated_services.values()
    }
    tracked_identities.update(
        id(service)
        for project_services in session.services_by_project.values()
        for service in project_services.values()
    )
    for name, service in services.items():
        if isinstance(name, str) and isinstance(service, ServiceRecord):
            if id(service) in tracked_identities:
                continue
            stored_name = name
            stored_service = service if service.project or not project else replace(service, project=project)
            if stored_name in occupied_names:
                pid = getattr(service, "pid", None)
                suffix = f"Restart Collision {pid}" if isinstance(pid, int) and pid > 0 else "Restart Collision"
                base = f"{name} {suffix}"
                stored_name = base
                index = 2
                while stored_name in occupied_names or stored_name in services:
                    stored_name = f"{base} {index}"
                    index += 1
                stored_service = replace(stored_service, name=stored_name)
                session.service_state_collisions.add(name)
                session.service_state_collision_rows.append(
                    {
                        "original_name": name,
                        "replacement_name": stored_name,
                        "replacement_pid": service.pid,
                        "replacement_project": service.project or project or None,
                    }
                )
                if name in session.preserved_services:
                    session.preserve_existing_state_on_failure = True
            occupied_names.add(stored_name)
            tracked_identities.add(id(service))
            session.unterminated_services[stored_name] = stored_service


def track_unterminated_services(session: StartupSession, failure: BaseException) -> None:
    track_startup_failure(session, failure)
