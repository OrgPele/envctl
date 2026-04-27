from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RequirementsResult, ServiceRecord

if TYPE_CHECKING:
    from envctl_engine.planning.plan_agent_launch_support import (
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
    requirements_by_project: dict[str, RequirementsResult] = field(default_factory=dict)
    services_by_project: dict[str, dict[str, ServiceRecord]] = field(default_factory=dict)
    started_context_names: list[str] = field(default_factory=list)
    dashboard_after_start: bool = False
    disabled_startup_mode: bool = False
    used_project_spinner_group: bool = False
    strict_truth_failed: bool = False
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
    local_startup_failures: list[LocalStartupFailure] = field(default_factory=list)

    @property
    def merged_services(self) -> dict[str, ServiceRecord]:
        services = dict(self.preserved_services)
        for project_services in self.services_by_project.values():
            services.update(project_services)
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
