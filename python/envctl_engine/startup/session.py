from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RequirementsResult, ServiceRecord

if TYPE_CHECKING:
    from envctl_engine.startup.protocols import ProjectContextLike


@dataclass(slots=True)
class ProjectStartupResult:
    requirements: RequirementsResult
    services: dict[str, ServiceRecord]
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class StartupSession:
    requested_route: Route
    effective_route: Route
    requested_command: str
    runtime_mode: str
    run_id: str
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
    debug_plan_snapshot: bool = False

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
