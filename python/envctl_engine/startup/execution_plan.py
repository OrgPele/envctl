from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.protocols import ProjectContextLike
from envctl_engine.startup.session import ProjectStartupResult, StartupSession
from envctl_engine.state.models import RequirementsResult, ServiceRecord


@dataclass(frozen=True, slots=True)
class StartupProjectWorkItem:
    project_context: ProjectContextLike
    display_name: str
    mode: str
    route: Route
    run_id: str | None
    restored: bool = False
    newly_started: bool = True


@dataclass(frozen=True, slots=True)
class StartupExecutionPlan:
    selected_contexts: tuple[ProjectContextLike, ...]
    contexts_to_start: tuple[ProjectContextLike, ...]
    resumed_context_names: tuple[str, ...] = ()
    preserved_services: Mapping[str, ServiceRecord] = field(default_factory=dict)
    preserved_requirements: Mapping[str, RequirementsResult] = field(default_factory=dict)
    base_metadata: Mapping[str, object] = field(default_factory=dict)
    effective_route: Route | None = None
    reuse_decision_kind: str | None = None
    finalization_hint: str = "continue"

    def work_items(self, *, mode: str, run_id: str | None = None) -> tuple[StartupProjectWorkItem, ...]:
        route = self.effective_route
        if route is None:
            raise RuntimeError("effective_route is required to build startup work items")
        resumed = {name.strip().casefold() for name in self.resumed_context_names if name.strip()}
        start_keys = {
            str(getattr(context, "name", "") or "").strip().casefold()
            for context in self.contexts_to_start
            if str(getattr(context, "name", "") or "").strip()
        }
        items: list[StartupProjectWorkItem] = []
        for context in self.selected_contexts:
            display_name = str(getattr(context, "name", "") or "").strip()
            key = display_name.casefold()
            restored = bool(key and key in resumed and key not in start_keys)
            newly_started = bool(key and key in start_keys)
            items.append(
                StartupProjectWorkItem(
                    project_context=context,
                    display_name=display_name,
                    mode=mode,
                    route=route,
                    run_id=run_id,
                    restored=restored,
                    newly_started=newly_started,
                )
            )
        return tuple(items)


@dataclass(frozen=True, slots=True)
class RunReuseApplicationResult:
    status: str
    return_code: int | None = None
    updated_route: Route | None = None
    preserved_services: Mapping[str, ServiceRecord] = field(default_factory=dict)
    preserved_requirements: Mapping[str, RequirementsResult] = field(default_factory=dict)
    contexts_to_start: tuple[ProjectContextLike, ...] = ()
    resumed_context_names: tuple[str, ...] = ()
    base_metadata: Mapping[str, object] = field(default_factory=dict)
    reuse_decision_kind: str | None = None


def build_startup_execution_plan(
    session: StartupSession,
    *,
    reuse_decision_kind: str | None = None,
    finalization_hint: str = "continue",
) -> StartupExecutionPlan:
    return StartupExecutionPlan(
        selected_contexts=tuple(session.selected_contexts),
        contexts_to_start=tuple(session.contexts_to_start),
        resumed_context_names=tuple(session.resumed_context_names),
        preserved_services=dict(session.preserved_services),
        preserved_requirements=dict(session.preserved_requirements),
        base_metadata=dict(session.base_metadata),
        effective_route=session.effective_route,
        reuse_decision_kind=reuse_decision_kind,
        finalization_hint=finalization_hint,
    )


def apply_execution_plan_to_session(session: StartupSession, plan: StartupExecutionPlan) -> None:
    session.selected_contexts = list(plan.selected_contexts)
    session.contexts_to_start = list(plan.contexts_to_start)
    session.resumed_context_names = list(plan.resumed_context_names)
    session.preserved_services = dict(plan.preserved_services)
    session.preserved_requirements = dict(plan.preserved_requirements)
    session.base_metadata = dict(plan.base_metadata)
    if plan.effective_route is not None:
        session.effective_route = plan.effective_route


def apply_project_startup_result_to_session(
    session: StartupSession,
    context: ProjectContextLike,
    result: ProjectStartupResult,
) -> None:
    session.requirements_by_project[context.name] = result.requirements
    session.services_by_project[context.name] = result.services
    session.started_context_names.append(context.name)
