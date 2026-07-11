from __future__ import annotations

from collections.abc import Collection, Mapping
import time
from dataclasses import dataclass, field
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
    preserve_existing_state_on_failure: bool = False
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
        services = dict(self.preserved_services)
        for project_services in self.services_by_project.values():
            services.update(project_services)
        services.update(self.unterminated_services)
        return services

    @property
    def merged_requirements(self) -> dict[str, RequirementsResult]:
        requirements = dict(self.preserved_requirements)
        requirements.update(self.requirements_by_project)
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
    return {name for raw_name in termination_result if (name := str(raw_name).strip()) and name in services}


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
        session.requirements_by_project[project] = requirements
    services = getattr(failure, "unterminated_services", None)
    if not isinstance(services, dict):
        return
    for name, service in services.items():
        if isinstance(name, str) and isinstance(service, ServiceRecord):
            session.unterminated_services[name] = service


def track_unterminated_services(session: StartupSession, failure: BaseException) -> None:
    track_startup_failure(session, failure)
