from __future__ import annotations

import time
import copy
from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from envctl_engine.requirements.common import build_container_name
from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.requirements.supabase import build_supabase_project_name
from envctl_engine.requirements.supabase_auth_users import (
    sync_results_to_requirement_payload,
    sync_supabase_auth_users,
)
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.engine_runtime_env import effective_dependency_scope
from envctl_engine.startup.protocols import ProjectContextLike, StartupOrchestratorLike
from envctl_engine.startup.requirements_execution import (
    REQUIREMENTS_PROGRESS_PROJECT_FLAG,
    maybe_prewarm_docker,
    requirements_failure_message,
    requirements_for_restart_context,
    requirements_timing_enabled,
    start_requirements_for_project as start_requirements_for_project_impl,
    startup_breakdown_enabled,
)
from envctl_engine.startup.service_execution import start_project_services as start_project_services_impl
from envctl_engine.startup.session import ProjectStartupResult
from envctl_engine.state.models import PortPlan, RequirementsResult


@dataclass(slots=True)
class _SharedProjectContext:
    name: str
    root: Path
    ports: Mapping[str, PortPlan]


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
    requirements = _requirements_for_project_context(orchestrator, context=context, mode=mode, route=route)
    if not rt._requirements_ready(requirements):
        raise RuntimeError(_requirements_failure_message(context.name, requirements))
    _sync_supabase_auth_users_before_services(
        orchestrator,
        context=context,
        mode=mode,
        route=route,
        requirements=requirements,
    )
    requirements_progress_message = _requirements_ready_progress_message(
        orchestrator,
        context=context,
        mode=mode,
        route=route,
        requirements=requirements,
    )
    if requirements_progress_message is not None:
        orchestrator._report_progress(route, requirements_progress_message, project=context.name)
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


def _sync_supabase_auth_users_before_services(
    orchestrator: StartupOrchestratorLike,
    *,
    context: ProjectContextLike,
    mode: str,
    route: Route,
    requirements: RequirementsResult,
) -> None:
    rt = orchestrator.runtime
    config_errors = tuple(getattr(rt.config, "supabase_auth_user_errors", ()) or ())
    if config_errors:
        raise RuntimeError("Invalid Supabase Auth user config: " + "; ".join(config_errors))
    configured_users = tuple(getattr(rt.config, "supabase_auth_users", ()) or ())
    enabled_users = tuple(
        user
        for user in configured_users
        if callable(getattr(user, "enabled_for_mode", None)) and user.enabled_for_mode(mode)
    )
    if not enabled_users:
        return
    component = requirements.component("supabase")
    if not bool(component.get("enabled", False)) or not bool(component.get("success", False)):
        return
    env = _supabase_project_env(runtime=rt, context=context, requirements=requirements, route=route)
    base_url = str(env.get("SUPABASE_URL", "") or "").strip()
    service_role_key = str(env.get("SUPABASE_SERVICE_ROLE_KEY", "") or "").strip()
    rt._emit(
        "supabase.auth_users.sync.start",
        project=context.name,
        mode=mode,
        users=len(enabled_users),
    )
    runtime_root = Path(getattr(rt, "runtime_root", getattr(rt.config, "runtime_scope_dir", ".")))
    summary = sync_supabase_auth_users(
        mode=mode,
        configured_users=enabled_users,
        base_url=base_url,
        service_role_key=service_role_key,
        runtime_root=runtime_root,
        dry_run=bool(route.flags.get("dry_run")),
    )
    for result in summary.results:
        rt._emit(
            "supabase.auth_users.sync.user",
            project=context.name,
            slug=result.name,
            status=result.status,
            supabase_user_id=result.id,
        )
    component["auth_users"] = sync_results_to_requirement_payload(summary)
    rt._emit(
        "supabase.auth_users.sync.finish",
        project=context.name,
        success=summary.success,
        users=len(summary.results),
    )
    if summary.success:
        return
    errors = [f"{item.name}: {item.error}" for item in summary.results if item.status == "failed" and item.error]
    message = "Supabase Auth user sync failed" + (": " + "; ".join(errors) if errors else "")
    if bool(getattr(rt.config, "supabase_auth_users_strict", True)):
        raise RuntimeError(message)
    rt._record_project_startup_warning(context.name, message)


def _supabase_project_env(**kwargs: object) -> dict[str, str]:
    from envctl_engine.requirements.dependencies.supabase import project_env

    return project_env(**kwargs)


def _requirements_for_project_context(
    orchestrator: StartupOrchestratorLike,
    *,
    context: ProjectContextLike,
    mode: str,
    route: Route,
) -> RequirementsResult:
    if mode != "trees" or effective_dependency_scope(route, mode) != "shared":
        return requirements_for_restart_context(orchestrator, context=context, mode=mode, route=route)
    return _shared_main_requirements(orchestrator, route=route, progress_project=context.name)


def _requirements_ready_progress_message(
    orchestrator: StartupOrchestratorLike,
    *,
    context: ProjectContextLike,
    mode: str,
    route: Route,
    requirements: RequirementsResult,
) -> str | None:
    component_summary = _requirements_component_summary(requirements)
    if mode != "trees" or effective_dependency_scope(route, mode) != "shared":
        return f"Requirements ready for {context.name}: " + component_summary
    if not component_summary:
        return None
    if _claim_first_shared_dependency_progress(orchestrator):
        return "Shared requirements ready: " + component_summary
    return "Shared requirements ready"


def _requirements_component_summary(requirements: RequirementsResult) -> str:
    return " ".join(
        f"{definition.id}={_component_port_summary(requirements, definition.id)}"
        for definition in dependency_definitions()
        if bool(requirements.component(definition.id).get("enabled", False))
    )


def _claim_first_shared_dependency_progress(orchestrator: StartupOrchestratorLike) -> bool:
    lock = getattr(orchestrator, "_shared_dependency_lock", None)
    if lock is None:
        already_reported = bool(getattr(orchestrator, "_shared_dependency_progress_reported", False))
        setattr(orchestrator, "_shared_dependency_progress_reported", True)
        return not already_reported
    with lock:
        already_reported = bool(getattr(orchestrator, "_shared_dependency_progress_reported", False))
        if already_reported:
            return False
        setattr(orchestrator, "_shared_dependency_progress_reported", True)
        return True


def _shared_main_requirements(
    orchestrator: StartupOrchestratorLike,
    *,
    route: Route,
    progress_project: str | None = None,
) -> RequirementsResult:
    cached = getattr(orchestrator, "_shared_dependency_requirements", None)
    if isinstance(cached, RequirementsResult):
        return cached
    lock = getattr(orchestrator, "_shared_dependency_lock", None)
    if lock is None:
        return _annotate_shared_main_requirements(
            orchestrator,
            _load_or_start_shared_main_requirements(
                orchestrator,
                route=route,
                progress_project=progress_project,
            ),
        )
    with lock:
        cached = getattr(orchestrator, "_shared_dependency_requirements", None)
        if isinstance(cached, RequirementsResult):
            return cached
        requirements = _load_or_start_shared_main_requirements(
            orchestrator,
            route=route,
            progress_project=progress_project,
        )
        requirements = _annotate_shared_main_requirements(orchestrator, requirements)
        setattr(orchestrator, "_shared_dependency_requirements", requirements)
        return requirements


def _load_or_start_shared_main_requirements(
    orchestrator: StartupOrchestratorLike,
    *,
    route: Route,
    progress_project: str | None = None,
) -> RequirementsResult:
    rt = orchestrator.runtime
    existing = rt._try_load_existing_state(mode="main", strict_mode_match=True)
    if existing is not None:
        requirements = existing.requirements.get("Main")
        if isinstance(requirements, RequirementsResult) and rt._requirements_ready(requirements):
            rt._emit("requirements.shared.reuse", project="Main", source_run_id=existing.run_id)
            return requirements
    main_context = _SharedProjectContext(
        name="Main",
        root=rt.config.execution_root,
        ports=cast(dict[str, PortPlan], cast(Any, rt.port_planner).plan_project_stack("Main", index=0)),
    )
    rt._reserve_project_ports(main_context)
    shared_route = Route(
        command=route.command,
        mode="main",
        raw_args=route.raw_args,
        passthrough_args=route.passthrough_args,
        projects=route.projects,
        flags={key: value for key, value in route.flags.items() if key != "dependency_scope"},
    )
    progress_project_name = str(progress_project or "").strip()
    if progress_project_name:
        shared_route.flags[REQUIREMENTS_PROGRESS_PROJECT_FLAG] = progress_project_name
    requirements = requirements_for_restart_context(orchestrator, context=main_context, mode="main", route=shared_route)
    rt._emit("requirements.shared.start", project="Main")
    return requirements


def _annotate_shared_main_requirements(
    orchestrator: StartupOrchestratorLike,
    requirements: RequirementsResult,
) -> RequirementsResult:
    cloned = RequirementsResult(
        project=requirements.project,
        components=copy.deepcopy(requirements.components),
        health=requirements.health,
        failures=list(requirements.failures),
    )
    project_root = orchestrator.runtime.config.execution_root
    for dependency_id, prefix in (
        ("postgres", "envctl-postgres"),
        ("redis", "envctl-redis"),
        ("n8n", "envctl-n8n"),
    ):
        component = cloned.component(dependency_id)
        if bool(component.get("enabled", False)):
            component["container_name"] = build_container_name(
                prefix=prefix,
                project_root=project_root,
                project_name="Main",
            )
    supabase = cloned.component("supabase")
    if bool(supabase.get("enabled", False)):
        supabase["container_name"] = build_supabase_project_name(
            project_root=project_root,
            project_name="Main",
        ) + "-supabase-db-1"
    return cloned


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
    top_components = cast(list[dict[str, object]], payload["top_components"])
    top = ", ".join(f"{item['name']}={_float_ms(item.get('duration_ms')):.1f}ms" for item in top_components)
    requirements_ms = _float_ms(payload.get("requirements_ms"))
    services_ms = _float_ms(payload.get("services_ms"))
    startup_ms = _float_ms(payload.get("startup_ms"))
    print(
        "Startup summary: "
        f"requirements={requirements_ms:.1f}ms "
        f"services={services_ms:.1f}ms "
        f"total={startup_ms:.1f}ms" + (f" top=[{top}]" if top else "")
    )


def _float_ms(value: object) -> float:
    try:
        return round(float(cast(Any, value)), 2)
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
