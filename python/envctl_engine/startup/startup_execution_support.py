from __future__ import annotations

import time

from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.protocols import ProjectContextLike, StartupOrchestratorLike
from envctl_engine.startup.requirements_execution import (
    maybe_prewarm_docker,
    requirements_failure_message,
    requirements_for_restart_context,
    requirements_timing_enabled,
    start_requirements_for_project as start_requirements_for_project_impl,
    startup_breakdown_enabled,
)
from envctl_engine.startup.service_execution import start_project_services as start_project_services_impl
from envctl_engine.startup.session import ProjectStartupResult
from envctl_engine.state.models import RequirementsResult


def start_project_context(
    orchestrator: StartupOrchestratorLike,
    *,
    context: ProjectContextLike,
    mode: str,
    route: Route,
    run_id: str,
) -> ProjectStartupResult:
    rt = orchestrator.runtime
    orchestrator._report_progress(route, f"Starting project {context.name}...", project=context.name)
    rt._reserve_project_ports(context)
    requirements = requirements_for_restart_context(orchestrator, context=context, mode=mode, route=route)
    if not rt._requirements_ready(requirements):
        raise RuntimeError(_requirements_failure_message(context.name, requirements))
    orchestrator._report_progress(
        route,
        f"Requirements ready for {context.name}: "
        + " ".join(
            f"{definition.id}={_component_port_summary(requirements, definition.id)}"
            for definition in dependency_definitions()
            if bool(requirements.component(definition.id).get("enabled", False))
        ),
        project=context.name,
    )
    project_services = orchestrator.start_project_services(
        context,
        requirements=requirements,
        run_id=run_id,
        route=route,
    )
    try:
        rt._assert_project_services_post_start_truth(context=context, services=project_services)
    except RuntimeError:
        rt._terminate_started_services(project_services)
        raise
    orchestrator._report_progress(
        route,
        f"Services ready for {context.name}: "
        + " ".join(
            f"{service_type}={_service_ready_label(project_services.get(f'{context.name} {service_type.title()}'))}"
            for service_type in ("backend", "frontend")
            if f"{context.name} {service_type.title()}" in project_services
        ),
        project=context.name,
    )
    return ProjectStartupResult(
        requirements=requirements,
        services=project_services,
        warnings=list(rt._consume_project_startup_warnings(context.name)),
    )


def startup_summary_payload(
    orchestrator: StartupOrchestratorLike,
    *,
    project_contexts: list[ProjectContextLike],
    start_event_index: int,
    startup_started_at: float,
) -> dict[str, object]:
    rt = orchestrator.runtime
    event_slice = list(rt.events[start_event_index:])
    requirement_totals: dict[str, float] = {}
    service_totals: dict[str, float] = {}
    for event in event_slice:
        event_name = str(event.get("event", "")).strip()
        if event_name == "requirements.timing.summary":
            project = str(event.get("project", "")).strip()
            if project:
                requirement_totals[project] = _float_ms(event.get("duration_ms"))
        elif event_name == "service.timing.summary":
            project = str(event.get("project", "")).strip()
            if project:
                service_totals[project] = _float_ms(event.get("duration_ms"))
    total_ms = round((time.monotonic() - startup_started_at) * 1000.0, 2)
    top_components: list[tuple[str, float]] = []
    for project, duration in requirement_totals.items():
        top_components.append((f"{project}:requirements", duration))
    for project, duration in service_totals.items():
        top_components.append((f"{project}:services", duration))
    top_components.sort(key=lambda item: item[1], reverse=True)
    return {
        "projects": [context.name for context in project_contexts],
        "requirements_ms": round(sum(requirement_totals.values()), 2),
        "services_ms": round(sum(service_totals.values()), 2),
        "startup_ms": total_ms,
        "top_components": [{"name": name, "duration_ms": round(duration, 2)} for name, duration in top_components[:3]],
    }


def print_startup_summary(
    orchestrator: StartupOrchestratorLike,
    *,
    project_contexts: list[ProjectContextLike],
    start_event_index: int,
    startup_started_at: float,
) -> None:
    payload = startup_summary_payload(
        orchestrator,
        project_contexts=project_contexts,
        start_event_index=start_event_index,
        startup_started_at=startup_started_at,
    )
    top = ", ".join(f"{item['name']}={float(item['duration_ms']):.1f}ms" for item in payload["top_components"])
    print(
        "Startup summary: "
        f"requirements={float(payload['requirements_ms']):.1f}ms "
        f"services={float(payload['services_ms']):.1f}ms "
        f"total={float(payload['startup_ms']):.1f}ms" + (f" top=[{top}]" if top else "")
    )


def _float_ms(value: object) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def _component_port_summary(requirements: RequirementsResult, dependency_id: str) -> int | None:
    component = requirements.component(dependency_id)
    final_port = component.get("final")
    if isinstance(final_port, int) and final_port > 0:
        return final_port
    requested_port = component.get("requested")
    if isinstance(requested_port, int) and requested_port > 0:
        return requested_port
    return None


def _service_ready_label(service: object | None) -> str:
    if service is None:
        return "disabled"
    actual_port = getattr(service, "actual_port", None)
    if isinstance(actual_port, int) and actual_port > 0:
        return str(actual_port)
    requested_port = getattr(service, "requested_port", None)
    if isinstance(requested_port, int) and requested_port > 0:
        return str(requested_port)
    if isinstance(getattr(service, "pid", None), int) and getattr(service, "listener_expected", True) is False:
        return "running"
    return str(getattr(service, "status", "unknown") or "unknown")


_requirements_failure_message = requirements_failure_message
_maybe_prewarm_docker = maybe_prewarm_docker
_requirements_timing_enabled = requirements_timing_enabled
_startup_breakdown_enabled = startup_breakdown_enabled
start_requirements_for_project = start_requirements_for_project_impl
start_project_services = start_project_services_impl
