from __future__ import annotations

import concurrent.futures
import os
from pathlib import Path
import re
import threading
import time

from envctl_engine.runtime.command_router import Route
from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.requirements.orchestrator import RequirementOutcome
from envctl_engine.runtime.runtime_context import resolve_port_allocator
from envctl_engine.shared.parsing import parse_bool, parse_int
from envctl_engine.state.models import RequirementsResult, ServiceRecord
from envctl_engine.startup.protocols import ProjectContextLike, StartupOrchestratorLike, StartupRuntime


def format_requirements_progress_message(*, active: set[str], pending: set[str]) -> str:
    active_list = sorted(str(name).strip() for name in active if str(name).strip())
    pending_list = sorted(str(name).strip() for name in pending if str(name).strip())
    if active_list:
        message = "Loading requirements: " + ", ".join(active_list)
        if pending_list:
            message += " | queued: " + ", ".join(pending_list)
        return message
    if pending_list:
        return "Preparing requirements: " + ", ".join(pending_list)
    return "Preparing requirements..."


def start_project_context(
    orchestrator: StartupOrchestratorLike,
    *,
    context: ProjectContextLike,
    mode: str,
    route: Route,
    run_id: str,
) -> tuple[RequirementsResult, dict[str, ServiceRecord], list[str]]:
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
        f"backend={context.ports['backend'].final} frontend={context.ports['frontend'].final}",
        project=context.name,
    )
    return requirements, project_services, list(rt._consume_project_startup_warnings(context.name))


_DOCKER_SOCKET_PATTERNS = (
    re.compile(r"unix://(?P<path>[^\s;]+docker\.sock)"),
    re.compile(r"dial unix (?P<path>[^\s:;]+docker\.sock)"),
)


def _requirements_failure_message(project_name: str, requirements: RequirementsResult) -> str:
    failed_components: list[str] = []
    docker_failed_components: list[str] = []
    docker_socket_paths: list[str] = []
    for definition in dependency_definitions():
        component = requirements.component(definition.id)
        if not bool(component.get("enabled", False)) or bool(component.get("success", False)):
            continue
        failed_components.append(definition.id)
        error = str(component.get("error") or "")
        if _docker_daemon_unavailable(error):
            docker_failed_components.append(definition.id)
            socket_path = _docker_socket_path(error)
            if socket_path is not None:
                docker_socket_paths.append(socket_path)
    if failed_components and len(docker_failed_components) == len(failed_components):
        services = ", ".join(docker_failed_components)
        message = "Docker is not running or not reachable"
        unique_paths = sorted({path for path in docker_socket_paths if path})
        if len(unique_paths) == 1:
            message += f" at {unique_paths[0]}"
        message += ". Start Docker Desktop or your Docker daemon, wait for it to become ready, and retry envctl."
        message += f" Blocked requirements for {project_name}: {services}."
        return message
    return f"Requirements unavailable for {project_name}: " + ", ".join(requirements.failures)


def _docker_daemon_unavailable(error: str) -> bool:
    normalized = error.strip().lower()
    if not normalized:
        return False
    docker_markers = (
        "failed to connect to the docker api",
        "cannot connect to the docker daemon",
        "is the docker daemon running",
        "error during connect",
    )
    if not any(marker in normalized for marker in docker_markers):
        return False
    return "docker.sock" in normalized or "docker daemon" in normalized


def _docker_socket_path(error: str) -> str | None:
    for pattern in _DOCKER_SOCKET_PATTERNS:
        match = pattern.search(error)
        if match is not None:
            return match.group("path")
    return None


def _component_port_summary(requirements: RequirementsResult, dependency_id: str) -> int | None:
    component = requirements.component(dependency_id)
    final_port = component.get("final")
    if isinstance(final_port, int) and final_port > 0:
        return final_port
    requested_port = component.get("requested")
    if isinstance(requested_port, int) and requested_port > 0:
        return requested_port
    return None


def _synthetic_requirements_result(
    rt: StartupRuntime, *, context: ProjectContextLike, mode: str, route: Route | None
) -> RequirementsResult:
    components: dict[str, dict[str, object]] = {}
    for definition in dependency_definitions():
        enabled = bool(rt._requirement_enabled(definition.id, mode=mode, route=route))
        plan = context.ports.get(definition.resources[0].legacy_port_key)
        final_port = int(getattr(plan, "final", 0) or 0) if plan is not None else 0
        components[definition.id] = {
            "requested": final_port or None,
            "final": final_port or None,
            "resources": {"requested": final_port or None, "primary": final_port or None},
            "retries": 0,
            "success": enabled,
            "simulated": True,
            "enabled": enabled,
            "reason_code": "synthetic_noop" if enabled else "disabled",
            "failure_class": None,
            "error": None,
            "container_name": None,
        }
    return RequirementsResult(
        project=context.name,
        components=components,
        health="healthy",
        failures=[],
    )


def _synthetic_service_records(
    rt: StartupRuntime, *, context: ProjectContextLike, mode: str
) -> dict[str, ServiceRecord]:
    project_services: dict[str, ServiceRecord] = {}
    if rt._service_enabled_for_mode(mode, "backend"):
        project_services[f"{context.name} Backend"] = ServiceRecord(
            name=f"{context.name} Backend",
            type="backend",
            cwd=str(context.root),
            requested_port=context.ports["backend"].final,
            actual_port=context.ports["backend"].final,
            status="unknown",
            synthetic=True,
        )
    if rt._service_enabled_for_mode(mode, "frontend"):
        project_services[f"{context.name} Frontend"] = ServiceRecord(
            name=f"{context.name} Frontend",
            type="frontend",
            cwd=str(context.root),
            requested_port=context.ports["frontend"].final,
            actual_port=context.ports["frontend"].final,
            status="unknown",
            synthetic=True,
        )
    return project_services


def _synthetic_running_service_records(
    rt: StartupRuntime, *, context: ProjectContextLike, mode: str
) -> dict[str, ServiceRecord]:
    project_services: dict[str, ServiceRecord] = {}
    if rt._service_enabled_for_mode(mode, "backend"):
        backend_port = context.ports["backend"].final
        project_services[f"{context.name} Backend"] = ServiceRecord(
            name=f"{context.name} Backend",
            type="backend",
            cwd=str(context.root),
            pid=os.getpid(),
            requested_port=backend_port,
            actual_port=backend_port,
            status="running",
            synthetic=True,
            listener_pids=[os.getpid()],
        )
    if rt._service_enabled_for_mode(mode, "frontend"):
        frontend_port = context.ports["frontend"].final
        project_services[f"{context.name} Frontend"] = ServiceRecord(
            name=f"{context.name} Frontend",
            type="frontend",
            cwd=str(context.root),
            pid=os.getpid() + 1,
            requested_port=frontend_port,
            actual_port=frontend_port,
            status="running",
            synthetic=True,
            listener_pids=[os.getpid() + 1],
        )
    return project_services


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


def _requirements_for_restart_context(
    orchestrator: StartupOrchestratorLike,
    *,
    context: ProjectContextLike,
    mode: str,
    route: Route | None,
) -> RequirementsResult:
    rt = orchestrator.runtime
    if route is None:
        return orchestrator.start_requirements_for_project(context, mode=mode, route=route)
    if not bool(route.flags.get("_restart_request")):
        return orchestrator.start_requirements_for_project(context, mode=mode, route=route)
    if orchestrator._restart_include_requirements(route):
        return orchestrator.start_requirements_for_project(context, mode=mode, route=route)

    previous = rt._try_load_existing_state(mode=mode, strict_mode_match=True)
    if previous is not None:
        existing = previous.requirements.get(context.name)
        if isinstance(existing, RequirementsResult):
            rt._emit(
                "requirements.restart.reuse",
                project=context.name,
                include_requirements=False,
            )
            return existing

    rt._emit(
        "requirements.restart.reuse_missing",
        project=context.name,
        include_requirements=False,
    )
    return orchestrator.start_requirements_for_project(context, mode=mode, route=route)


def start_requirements_for_project(
    orchestrator: StartupOrchestratorLike,
    context: ProjectContextLike,
    *,
    mode: str,
    route: Route | None = None,
) -> RequirementsResult:
    rt = orchestrator.runtime
    port_allocator = resolve_port_allocator(rt)
    failures: list[str] = []
    timing_enabled = _requirements_timing_enabled(orchestrator, route)
    requirements_started = time.monotonic()
    component_timings_ms: dict[str, float] = {}
    definitions = dependency_definitions()
    reserve_lock = threading.Lock()
    progress_state_lock = threading.Lock()

    definition_ports = {
        definition.id: context.ports[definition.resources[0].legacy_port_key] for definition in definitions
    }

    def plan_for_dependency(dependency_id: str):
        return definition_ports[dependency_id]

    setup_hook = rt._invoke_envctl_hook(context=context, hook_name="envctl_setup_infrastructure")
    if setup_hook.found and not setup_hook.success:
        failures.append(f"setup_hook:{setup_hook.error or 'failed'}")
        components = {}
        for definition in definitions:
            plan = plan_for_dependency(definition.id)
            components[definition.id] = {
                "requested": plan.requested,
                "final": plan.final,
                "resources": {"requested": plan.requested, "primary": plan.final},
                "retries": 0,
                "success": False,
                "simulated": False,
                "enabled": rt._requirement_enabled(definition.id, mode=mode, route=route),
            }
        return RequirementsResult(
            project=context.name,
            components=components,
            health="degraded",
            failures=failures,
        )
    if setup_hook.found and setup_hook.success:
        payload = setup_hook.payload if isinstance(setup_hook.payload, dict) else {}
        if bool(payload.get("skip_default_requirements")):
            return rt._requirements_result_from_hook_payload(
                context=context,
                mode=mode,
                payload=payload,
            )

    def reserve_next(port: int) -> int:
        with reserve_lock:
            return port_allocator.reserve_next(port, owner=f"{context.name}:requirements")

    enabled_lookup = {
        definition.id: bool(rt._requirement_enabled(definition.id, mode=mode, route=route))
        for definition in definitions
    }
    enabled_definitions = [definition for definition in definitions if enabled_lookup[definition.id]]
    pending_requirements = {definition.id for definition in enabled_definitions}
    active_requirements: set[str] = set()

    def emit_requirements_progress() -> None:
        if not enabled_definitions:
            return
        orchestrator._report_progress(
            route,
            format_requirements_progress_message(
                active=active_requirements,
                pending=pending_requirements,
            ),
            project=context.name,
        )

    def run_component(component: str, plan: object, *, strict: bool = False) -> RequirementOutcome:
        component_started = time.monotonic()
        with progress_state_lock:
            pending_requirements.discard(component)
            active_requirements.add(component)
            emit_requirements_progress()
        try:
            outcome = rt._start_requirement_component(
                context,
                component,
                plan,
                reserve_next,
                strict=strict,
                route=route,
            )
            duration_ms = round((time.monotonic() - component_started) * 1000.0, 2)
            component_timings_ms[component] = duration_ms
            rt._emit(
                "requirements.timing.component",
                project=context.name,
                requirement=component,
                duration_ms=duration_ms,
                enabled=True,
                success=bool(getattr(outcome, "success", False)),
                retries=int(getattr(outcome, "retries", 0)),
                final_port=getattr(outcome, "final_port", None),
                failure_class=str(getattr(outcome, "failure_class", "")),
            )
            return outcome
        finally:
            with progress_state_lock:
                active_requirements.discard(component)
                emit_requirements_progress()

    emit_requirements_progress()
    outcomes: dict[str, RequirementOutcome] = {}
    for definition in definitions:
        if definition.id in pending_requirements:
            continue
        outcome = rt._skipped_requirement(definition.id, plan_for_dependency(definition.id))
        component_timings_ms[definition.id] = 0.0
        rt._emit(
            "requirements.timing.component",
            project=context.name,
            requirement=definition.id,
            duration_ms=0.0,
            enabled=False,
            success=bool(getattr(outcome, "success", False)),
            retries=int(getattr(outcome, "retries", 0)),
            final_port=getattr(outcome, "final_port", None),
            failure_class=str(getattr(outcome, "failure_class", "")),
        )
        outcomes[definition.id] = outcome
    raw_parallel = rt.env.get("ENVCTL_REQUIREMENTS_PARALLEL") or rt.config.raw.get("ENVCTL_REQUIREMENTS_PARALLEL")
    parallel_enabled = parse_bool(raw_parallel, True) and len(enabled_definitions) > 1
    raw_workers = rt.env.get("ENVCTL_REQUIREMENTS_PARALLEL_MAX") or rt.config.raw.get(
        "ENVCTL_REQUIREMENTS_PARALLEL_MAX"
    )
    worker_limit = max(parse_int(raw_workers, 4), 1)
    worker_count = min(worker_limit, len(enabled_definitions)) if parallel_enabled else 1
    rt._emit(
        "requirements.execution",
        project=context.name,
        mode="parallel" if parallel_enabled and worker_count > 1 else "sequential",
        workers=worker_count,
        enabled=sorted(definition.id for definition in enabled_definitions),
    )
    if timing_enabled and not orchestrator._suppress_timing_output(route):
        print(
            "Requirements execution for "
            f"{context.name}: "
            f"{'parallel' if parallel_enabled and worker_count > 1 else 'sequential'} "
            f"(workers={worker_count})"
        )

    if parallel_enabled and worker_count > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map: dict[concurrent.futures.Future[RequirementOutcome], str] = {}
            for definition in enabled_definitions:
                strict = bool(definition.id == "n8n" and rt.config.strict_n8n_bootstrap)
                future = executor.submit(
                    run_component, definition.id, plan_for_dependency(definition.id), strict=strict
                )
                future_map[future] = definition.id
            for future in concurrent.futures.as_completed(future_map):
                definition_id = future_map[future]
                outcomes[definition_id] = future.result()
    else:
        for definition in enabled_definitions:
            strict = bool(definition.id == "n8n" and rt.config.strict_n8n_bootstrap)
            outcomes[definition.id] = run_component(definition.id, plan_for_dependency(definition.id), strict=strict)

    for outcome in outcomes.values():
        if not outcome.success:
            failures.append(f"{outcome.service_name}:{outcome.failure_class}:{outcome.error}")

    health = "healthy" if not failures else "degraded"
    total_duration_ms = round((time.monotonic() - requirements_started) * 1000.0, 2)
    rt._emit(
        "requirements.timing.summary",
        project=context.name,
        duration_ms=total_duration_ms,
        components=component_timings_ms,
        failures=len(failures),
    )
    if timing_enabled and not orchestrator._suppress_timing_output(route):
        component_parts = " ".join(
            f"{name}={component_timings_ms.get(name, 0.0):.1f}ms"
            for name in (definition.id for definition in definitions)
        )
        print(f"Requirements timing for {context.name}: {component_parts} total={total_duration_ms:.1f}ms")
    components: dict[str, dict[str, object]] = {}
    for definition in definitions:
        outcome = outcomes[definition.id]
        components[definition.id] = {
            "requested": outcome.requested_port,
            "final": outcome.final_port,
            "resources": {"requested": outcome.requested_port, "primary": outcome.final_port},
            "retries": outcome.retries,
            "success": outcome.success,
            "simulated": outcome.simulated,
            "enabled": enabled_lookup[definition.id],
            "reason_code": outcome.reason_code,
            "failure_class": outcome.failure_class.value if getattr(outcome, "failure_class", None) else None,
            "error": outcome.error,
            "container_name": outcome.container_name,
        }
    return RequirementsResult(
        project=context.name,
        components=components,
        health=health,
        failures=failures,
    )


def _requirements_timing_enabled(orchestrator: StartupOrchestratorLike, route: Route | None) -> bool:
    rt = orchestrator.runtime
    raw_force = rt.env.get("ENVCTL_DEBUG_RESTORE_TIMING") or rt.config.raw.get("ENVCTL_DEBUG_RESTORE_TIMING")
    if bool(raw_force) and str(raw_force).strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if route is not None and (bool(route.flags.get("debug_ui")) or bool(route.flags.get("debug_ui_deep"))):
        return True
    raw_mode = (rt.env.get("ENVCTL_DEBUG_UI_MODE") or rt.config.raw.get("ENVCTL_DEBUG_UI_MODE") or "").strip().lower()
    return raw_mode in {"standard", "deep"}


def _docker_prewarm_enabled(orchestrator: StartupOrchestratorLike, route: Route | None) -> bool:
    _ = route
    rt = orchestrator.runtime
    raw = rt.env.get("ENVCTL_DOCKER_PREWARM") or rt.config.raw.get("ENVCTL_DOCKER_PREWARM")
    return parse_bool(raw, True)


def _docker_prewarm_timeout_seconds(orchestrator: StartupOrchestratorLike, route: Route | None) -> int:
    _ = route
    rt = orchestrator.runtime
    raw = rt.env.get("ENVCTL_DOCKER_PREWARM_TIMEOUT_SECONDS") or rt.config.raw.get(
        "ENVCTL_DOCKER_PREWARM_TIMEOUT_SECONDS"
    )
    value = parse_int(raw, 10)
    return max(value, 1)


def _prewarm_requires_startup_requirements(
    orchestrator: StartupOrchestratorLike, *, mode: str, route: Route | None
) -> bool:
    rt = orchestrator.runtime
    for definition in dependency_definitions():
        if bool(rt._requirement_enabled(definition.id, mode=mode, route=route)):
            return True
    return False


def _maybe_prewarm_docker(orchestrator: StartupOrchestratorLike, *, route: Route | None, mode: str) -> None:
    rt = orchestrator.runtime
    if not _docker_prewarm_enabled(orchestrator, route):
        rt._emit("requirements.docker_prewarm", used=False, reason="disabled")
        return
    if not _prewarm_requires_startup_requirements(orchestrator, mode=mode, route=route):
        rt._emit("requirements.docker_prewarm", used=False, reason="no_enabled_requirements")
        return
    if not rt._command_exists("docker"):
        rt._emit("requirements.docker_prewarm", used=False, reason="docker_missing")
        return
    timeout_s = _docker_prewarm_timeout_seconds(orchestrator, route)
    started = time.monotonic()
    result = rt.process_runner.run(["docker", "ps"], timeout=float(timeout_s))
    duration_ms = round((time.monotonic() - started) * 1000.0, 2)
    returncode = int(result.returncode)
    stderr = str(result.stderr or "")
    stdout = str(result.stdout or "")
    timed_out = bool(returncode == 124 or "timed out" in stderr.lower() or "timed out" in stdout.lower())
    rt._emit(
        "requirements.docker_prewarm",
        used=True,
        command=["docker", "ps"],
        timeout_s=timeout_s,
        duration_ms=duration_ms,
        returncode=returncode,
        timed_out=timed_out,
        success=returncode == 0 and not timed_out,
    )


def _startup_breakdown_enabled(orchestrator: StartupOrchestratorLike, route: Route | None) -> bool:
    rt = orchestrator.runtime
    raw = rt.env.get("ENVCTL_DEBUG_STARTUP_BREAKDOWN") or rt.config.raw.get("ENVCTL_DEBUG_STARTUP_BREAKDOWN")
    if parse_bool(raw, False):
        return True
    if route is not None and (bool(route.flags.get("debug_ui")) or bool(route.flags.get("debug_ui_deep"))):
        return True
    raw_mode = (rt.env.get("ENVCTL_DEBUG_UI_MODE") or rt.config.raw.get("ENVCTL_DEBUG_UI_MODE") or "").strip().lower()
    return raw_mode in {"deep"}


def _service_attach_parallel_enabled(
    orchestrator: StartupOrchestratorLike, *, route: Route | None, selected_service_types: set[str]
) -> bool:
    if selected_service_types != {"backend", "frontend"}:
        return False
    if route is not None:
        route_value = route.flags.get("service_parallel")
        if isinstance(route_value, bool):
            return route_value
    rt = orchestrator.runtime
    raw = rt.env.get("ENVCTL_SERVICE_ATTACH_PARALLEL") or rt.config.raw.get("ENVCTL_SERVICE_ATTACH_PARALLEL")
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _service_prep_parallel_enabled(
    orchestrator: StartupOrchestratorLike,
    *,
    route: Route | None,
    selected_service_types: set[str],
    attach_parallel: bool,
) -> bool:
    if selected_service_types != {"backend", "frontend"}:
        return False
    if route is not None:
        route_value = route.flags.get("service_prep_parallel")
        if isinstance(route_value, bool):
            return route_value
    rt = orchestrator.runtime
    raw = rt.env.get("ENVCTL_SERVICE_PREP_PARALLEL") or rt.config.raw.get("ENVCTL_SERVICE_PREP_PARALLEL")
    if str(raw).strip():
        return parse_bool(raw, True)
    return attach_parallel


def start_project_services(
    orchestrator: StartupOrchestratorLike,
    context: ProjectContextLike,
    *,
    requirements: RequirementsResult,
    run_id: str,
    route: Route | None = None,
) -> dict[str, ServiceRecord]:
    rt = orchestrator.runtime
    port_allocator = resolve_port_allocator(rt)
    process_runtime = orchestrator._process_runtime(rt)
    effective_mode = str(route.mode if route is not None else "main").strip().lower() or "main"
    backend_plan = context.ports["backend"]
    frontend_plan = context.ports["frontend"]
    backend_cwd = context.root / str(getattr(rt.config, "backend_dir_name", "backend"))
    frontend_cwd = context.root / str(getattr(rt.config, "frontend_dir_name", "frontend"))
    if not backend_cwd.is_dir():
        backend_cwd = context.root
    if not frontend_cwd.is_dir():
        frontend_cwd = context.root

    services_hook = rt._invoke_envctl_hook(context=context, hook_name="envctl_define_services")
    if services_hook.found:
        if not services_hook.success:
            raise RuntimeError(
                f"envctl_define_services hook failed for {context.name}: {services_hook.error or 'failed'}"
            )
        payload = services_hook.payload if isinstance(services_hook.payload, dict) else {}
        hook_records = rt._services_from_hook_payload(context=context, payload=payload)
        if hook_records:
            return hook_records
        if bool(payload.get("skip_default_services")):
            raise RuntimeError(
                f"envctl_define_services hook requested skip_default_services for {context.name} "
                "but returned no services"
            )

    run_logs_dir = rt._run_dir_path(run_id)
    safe_project_name = context.name.replace("/", "_").replace(" ", "_")
    backend_log_path = str(run_logs_dir / f"{safe_project_name}_backend.log")
    frontend_log_path = str(run_logs_dir / f"{safe_project_name}_frontend.log")
    project_env_internal_builder = getattr(rt, "_project_service_env_internal", None)
    if callable(project_env_internal_builder):
        project_env_internal = project_env_internal_builder(context, requirements=requirements, route=route)
    else:
        project_env_internal = rt._project_service_env(context, requirements=requirements, route=route)

    def project_env_for_service(service_name: str) -> dict[str, str]:
        try:
            return rt._project_service_env(
                context,
                requirements=requirements,
                route=route,
                service_name=service_name,
            )
        except TypeError as exc:
            if "service_name" not in str(exc):
                raise
            return rt._project_service_env(context, requirements=requirements, route=route)

    backend_project_env_base = project_env_for_service("backend")
    frontend_project_env_base = project_env_for_service("frontend")
    backend_env_file, backend_env_is_default = rt._resolve_backend_env_file(
        context=context,
        backend_cwd=backend_cwd,
    )
    frontend_env_file = rt._resolve_frontend_env_file(
        context=context,
        frontend_cwd=frontend_cwd,
    )
    backend_env_extra = rt._service_env_from_file(
        base_env=backend_project_env_base,
        env_file=backend_env_file,
        include_app_env_file=True,
    )
    frontend_env_extra = rt._service_env_from_file(
        base_env=frontend_project_env_base,
        env_file=frontend_env_file,
        include_app_env_file=False,
    )
    backend_url = f"http://localhost:{backend_plan.final}"
    frontend_env_extra["VITE_BACKEND_URL"] = backend_url
    frontend_env_extra["VITE_API_URL"] = f"{backend_url}/api/v1"
    configured_service_types = {
        service_name
        for service_name in ("backend", "frontend")
        if rt._service_enabled_for_mode(effective_mode, service_name)
    }
    selected_service_types = orchestrator._restart_service_types_for_project(
        route=route,
        project_name=context.name,
        default_service_types=configured_service_types,
    )
    if not selected_service_types:
        rt._emit(
            "service.attach.skipped",
            project=context.name,
            mode=effective_mode,
            reason="all_services_disabled",
        )
        return {}
    service_started = time.monotonic()
    prepare_backend_duration_ms = 0.0
    prepare_frontend_duration_ms = 0.0
    prepare_backend = "backend" in selected_service_types
    prepare_frontend = "frontend" in selected_service_types
    attach_parallel = _service_attach_parallel_enabled(
        orchestrator,
        route=route,
        selected_service_types=selected_service_types,
    )
    prep_parallel = _service_prep_parallel_enabled(
        orchestrator,
        route=route,
        selected_service_types=selected_service_types,
        attach_parallel=attach_parallel,
    )

    def prepare_backend_runtime() -> float:
        started = time.monotonic()
        rt._prepare_backend_runtime(
            context=context,
            backend_cwd=backend_cwd,
            backend_log_path=backend_log_path,
            project_env_base=project_env_internal,
            route=route,
            backend_env_file=backend_env_file,
            backend_env_is_default=backend_env_is_default,
        )
        return round((time.monotonic() - started) * 1000.0, 2)

    def prepare_frontend_runtime() -> float:
        started = time.monotonic()
        rt._prepare_frontend_runtime(
            context=context,
            frontend_cwd=frontend_cwd,
            frontend_log_path=frontend_log_path,
            project_env_base=frontend_project_env_base,
            frontend_env_file=frontend_env_file,
            backend_port=backend_plan.final,
            route=route,
        )
        return round((time.monotonic() - started) * 1000.0, 2)

    if prepare_backend and prepare_frontend and prep_parallel:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_map: dict[concurrent.futures.Future[float], str] = {}
            future_map[executor.submit(prepare_backend_runtime)] = "backend"
            future_map[executor.submit(prepare_frontend_runtime)] = "frontend"
            for future in concurrent.futures.as_completed(future_map):
                prep = future_map[future]
                duration = future.result()
                if prep == "backend":
                    prepare_backend_duration_ms = duration
                else:
                    prepare_frontend_duration_ms = duration
    else:
        if prepare_backend:
            prepare_backend_duration_ms = prepare_backend_runtime()
        if prepare_frontend:
            prepare_frontend_duration_ms = prepare_frontend_runtime()
    if prepare_backend:
        rt._emit(
            "service.timing.component",
            project=context.name,
            component="prepare_backend_runtime",
            duration_ms=prepare_backend_duration_ms,
        )
    if prepare_frontend:
        rt._emit(
            "service.timing.component",
            project=context.name,
            component="prepare_frontend_runtime",
            duration_ms=prepare_frontend_duration_ms,
        )
    rebound_delta = parse_int(rt.env.get("ENVCTL_TEST_FRONTEND_REBOUND_DELTA"), 0)
    backend_command_source = None
    if "backend" in selected_service_types:
        backend_command_source = rt._service_command_source(
            service_name="backend",
            project_root=context.root,
            port=backend_plan.final,
        )
    frontend_command_source = None
    if "frontend" in selected_service_types:
        frontend_command_source = rt._service_command_source(
            service_name="frontend",
            project_root=context.root,
            port=(frontend_plan.final + rebound_delta if rebound_delta > 0 else frontend_plan.final),
        )

    def reserve_next(port: int) -> int:
        return port_allocator.reserve_next(port, owner=f"{context.name}:services")

    def start_process(
        command: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        log_path: Path,
    ) -> object:
        start_background = getattr(process_runtime, "start_background", None)
        if callable(start_background):
            return start_background(
                command,
                cwd=cwd,
                env=env,
                stdout_path=log_path,
                stderr_path=log_path,
            )
        return process_runtime.start(
            command,
            cwd=cwd,
            env=env,
            stdout_path=log_path,
            stderr_path=log_path,
        )

    def start_backend(port: int) -> tuple[bool, str | None, int | None]:
        remaining = rt._conflict_remaining.get("backend", 0)  # type: ignore[attr-defined]
        if remaining > 0:
            rt._conflict_remaining["backend"] = remaining - 1  # type: ignore[attr-defined]
            rt._emit("service.start", project=context.name, service="backend", port=port, retry=True)  # type: ignore[attr-defined]
            return False, "bind: address already in use", None
        command_resolve_started = time.monotonic()
        command, _resolved_source = rt._service_start_command_resolved(  # type: ignore[attr-defined]
            service_name="backend",
            project_root=context.root,
            port=port,
        )
        rt._emit(  # type: ignore[attr-defined]
            "service.attach.phase",
            project=context.name,
            service="backend",
            phase="command_resolution",
            duration_ms=round((time.monotonic() - command_resolve_started) * 1000.0, 2),
        )
        launch_started = time.monotonic()
        process = start_process(
            command,
            cwd=backend_cwd,
            env=rt._command_env(port=port, extra=backend_env_extra),  # type: ignore[attr-defined]
            log_path=backend_log_path,
        )
        rt._emit(  # type: ignore[attr-defined]
            "service.attach.phase",
            project=context.name,
            service="backend",
            phase="process_launch",
            duration_ms=round((time.monotonic() - launch_started) * 1000.0, 2),
        )
        rt._emit("service.start", project=context.name, service="backend", port=port, retry=False)  # type: ignore[attr-defined]
        return True, None, getattr(process, "pid", os.getpid())

    def start_frontend(port: int) -> tuple[bool, str | None, int | None]:
        remaining = rt._conflict_remaining.get("frontend", 0)  # type: ignore[attr-defined]
        if remaining > 0:
            rt._conflict_remaining["frontend"] = remaining - 1  # type: ignore[attr-defined]
            rt._emit("service.start", project=context.name, service="frontend", port=port, retry=True)  # type: ignore[attr-defined]
            return False, "bind: address already in use", None
        launch_port = port + rebound_delta if rebound_delta > 0 else port
        if rebound_delta > 0:
            launch_port = port_allocator.reserve_next(  # type: ignore[attr-defined]
                launch_port,
                owner=f"{context.name}:services:frontend-launch",
            )
        command_resolve_started = time.monotonic()
        command, _resolved_source = rt._service_start_command_resolved(  # type: ignore[attr-defined]
            service_name="frontend",
            project_root=context.root,
            port=launch_port,
        )
        rt._emit(  # type: ignore[attr-defined]
            "service.attach.phase",
            project=context.name,
            service="frontend",
            phase="command_resolution",
            duration_ms=round((time.monotonic() - command_resolve_started) * 1000.0, 2),
        )
        launch_started = time.monotonic()
        process = start_process(
            command,
            cwd=frontend_cwd,
            env=rt._command_env(port=launch_port, extra=frontend_env_extra),  # type: ignore[attr-defined]
            log_path=frontend_log_path,
        )
        rt._emit(  # type: ignore[attr-defined]
            "service.attach.phase",
            project=context.name,
            service="frontend",
            phase="process_launch",
            duration_ms=round((time.monotonic() - launch_started) * 1000.0, 2),
        )
        rt._emit("service.start", project=context.name, service="frontend", port=port, retry=False)  # type: ignore[attr-defined]
        return True, None, getattr(process, "pid", os.getpid() + 1)

    backend_actual_override = parse_int(rt.env.get("ENVCTL_TEST_BACKEND_ACTUAL_PORT"), 0)
    frontend_actual_override = parse_int(rt.env.get("ENVCTL_TEST_FRONTEND_ACTUAL_PORT"), 0)

    def detect_backend_actual(pid: int | None, requested: int) -> int:
        rt._emit("service.bind.requested", project=context.name, service="backend", requested_port=requested)  # type: ignore[attr-defined]
        detect_started = time.monotonic()
        if backend_actual_override > 0:
            actual = backend_actual_override
        else:
            detected = rt._detect_service_actual_port(  # type: ignore[attr-defined]
                pid=pid,
                requested_port=requested,
                service_name="backend",
            )
            if detected is not None:
                actual = detected
                if actual != requested:
                    rt._emit("port.rebound", project=context.name, service="backend", port=actual)  # type: ignore[attr-defined]
            elif rt._listener_truth_enforced():  # type: ignore[attr-defined]
                detail = rt._service_listener_failure_detail(log_path=backend_log_path, pid=pid)  # type: ignore[attr-defined]
                error_suffix = f" ({detail})" if detail else ""
                rt._emit(  # type: ignore[attr-defined]
                    "service.failure",
                    project=context.name,
                    service="backend",
                    failure_class="listener_not_detected",
                    requested_port=requested,
                    detail=detail,
                )
                raise RuntimeError(
                    f"backend listener not detected for {context.name} on port {requested}{error_suffix}"
                )
            else:
                rt._emit(  # type: ignore[attr-defined]
                    "service.failure",
                    project=context.name,
                    service="backend",
                    failure_class="listener_unverified",
                    requested_port=requested,
                )
                actual = requested
        rt._emit("service.bind.actual", project=context.name, service="backend", actual_port=actual)  # type: ignore[attr-defined]
        rt._emit(  # type: ignore[attr-defined]
            "service.attach.phase",
            project=context.name,
            service="backend",
            phase="actual_port_detection",
            duration_ms=round((time.monotonic() - detect_started) * 1000.0, 2),
        )
        return actual

    def detect_frontend_actual(pid: int | None, requested: int) -> int:
        rt._emit("service.bind.requested", project=context.name, service="frontend", requested_port=requested)  # type: ignore[attr-defined]
        detect_started = time.monotonic()
        if frontend_actual_override > 0:
            actual = frontend_actual_override
        else:
            probe_port = requested + rebound_delta if rebound_delta > 0 else requested
            detected = rt._detect_service_actual_port(  # type: ignore[attr-defined]
                pid=pid,
                requested_port=probe_port,
                service_name="frontend",
            )
            if detected is None and probe_port != requested:
                detected = rt._detect_service_actual_port(  # type: ignore[attr-defined]
                    pid=pid,
                    requested_port=requested,
                    service_name="frontend",
                )
            if detected is not None:
                actual = detected
                if actual != requested:
                    rt._emit("port.rebound", project=context.name, service="frontend", port=actual)  # type: ignore[attr-defined]
            elif rt._listener_truth_enforced():  # type: ignore[attr-defined]
                detail = rt._service_listener_failure_detail(log_path=frontend_log_path, pid=pid)  # type: ignore[attr-defined]
                error_suffix = f" ({detail})" if detail else ""
                rt._emit(  # type: ignore[attr-defined]
                    "service.failure",
                    project=context.name,
                    service="frontend",
                    failure_class="listener_not_detected",
                    requested_port=requested,
                    detail=detail,
                )
                raise RuntimeError(
                    f"frontend listener not detected for {context.name} on port {probe_port}{error_suffix}"
                )
            else:
                rt._emit(  # type: ignore[attr-defined]
                    "service.failure",
                    project=context.name,
                    service="frontend",
                    failure_class="listener_unverified",
                    requested_port=requested,
                )
                actual = probe_port
        rt._emit("service.bind.actual", project=context.name, service="frontend", actual_port=actual)  # type: ignore[attr-defined]
        rt._emit(  # type: ignore[attr-defined]
            "service.attach.phase",
            project=context.name,
            service="frontend",
            phase="actual_port_detection",
            duration_ms=round((time.monotonic() - detect_started) * 1000.0, 2),
        )
        return actual

    def on_service_retry(
        service_type: str,
        failed_port: int,
        retry_port: int,
        attempt: int,
        error: str | None,
    ) -> None:
        rt._emit(  # type: ignore[attr-defined]
            "service.retry",
            project=context.name,
            service=service_type,
            failed_port=failed_port,
            retry_port=retry_port,
            attempt=attempt,
            error=(error or "").strip() or None,
        )

    attach_duration_ms = 0.0
    records: dict[str, ServiceRecord]

    def _running_service_record(
        *,
        service_name: str,
        requested_port: int,
        actual_port: int,
        pid: int | None,
        cwd: Path,
        log_path: str,
        listener_pid: int | None = None,
    ) -> ServiceRecord:
        return ServiceRecord(
            name=f"{context.name} {'Backend' if service_name == 'backend' else 'Frontend'}",
            type=service_name,
            cwd=str(cwd),
            status="running",
            requested_port=requested_port,
            actual_port=actual_port,
            pid=pid,
            listener_pids=[listener_pid] if listener_pid is not None else ([] if pid is None else [pid]),
            log_path=log_path,
            started_at=time.time(),
            synthetic=False,
        )

    rt._emit(  # type: ignore[attr-defined]
        "service.attach.execution",
        project=context.name,
        mode="parallel" if attach_parallel else "sequential",
        selected_service_types=sorted(selected_service_types),
    )
    if _requirements_timing_enabled(orchestrator, route) and not orchestrator._suppress_timing_output(route):
        print(
            "Service attach execution for "
            f"{context.name}: "
            f"{'parallel' if attach_parallel else 'sequential'} "
            f"(services={','.join(sorted(selected_service_types))})"
        )
    attach_started = time.monotonic()
    if selected_service_types == {"backend", "frontend"}:
        records = rt.services.start_project_with_attach(  # type: ignore[attr-defined]
            project=context.name,
            backend_port=backend_plan.final,
            frontend_port=frontend_plan.final,
            backend_cwd=str(backend_cwd),
            frontend_cwd=str(frontend_cwd),
            start_backend=start_backend,
            start_frontend=start_frontend,
            reserve_next=reserve_next,
            detect_backend_actual=detect_backend_actual,
            detect_frontend_actual=detect_frontend_actual,
            on_retry=on_service_retry,
            parallel_start=attach_parallel,
        )
    else:
        records = {}
        if "backend" in selected_service_types:
            backend = rt.services.start_service_with_retry(  # type: ignore[attr-defined]
                project=context.name,
                service_type="backend",
                cwd=str(backend_cwd),
                requested_port=backend_plan.final,
                start=start_backend,
                reserve_next=reserve_next,
                detect_actual=detect_backend_actual,
                on_retry=on_service_retry,
            )
            records[backend.name] = backend
        if "frontend" in selected_service_types:
            frontend = rt.services.start_service_with_retry(  # type: ignore[attr-defined]
                project=context.name,
                service_type="frontend",
                cwd=str(frontend_cwd),
                requested_port=frontend_plan.final,
                start=start_frontend,
                reserve_next=reserve_next,
                detect_actual=detect_frontend_actual,
                on_retry=on_service_retry,
            )
            records[frontend.name] = frontend
    attach_duration_ms = round((time.monotonic() - attach_started) * 1000.0, 2)
    total_duration_ms = round((time.monotonic() - service_started) * 1000.0, 2)
    rt._emit(  # type: ignore[attr-defined]
        "service.timing.component",
        project=context.name,
        component="start_project_with_attach",
        duration_ms=attach_duration_ms,
    )
    rt._emit(  # type: ignore[attr-defined]
        "service.timing.summary",
        project=context.name,
        duration_ms=total_duration_ms,
        components={
            "prepare_backend_runtime": prepare_backend_duration_ms,
            "prepare_frontend_runtime": prepare_frontend_duration_ms,
            "start_project_with_attach": attach_duration_ms,
        },
    )
    if _requirements_timing_enabled(orchestrator, route) and not orchestrator._suppress_timing_output(route):
        timing_parts: list[str] = []
        if "backend" in selected_service_types:
            timing_parts.append(f"prepare_backend_runtime={prepare_backend_duration_ms:.1f}ms")
        if "frontend" in selected_service_types:
            timing_parts.append(f"prepare_frontend_runtime={prepare_frontend_duration_ms:.1f}ms")
        timing_parts.append(f"start_project_with_attach={attach_duration_ms:.1f}ms")
        timing_parts.append(f"total={total_duration_ms:.1f}ms")
        print(f"Service timing for {context.name}: {' '.join(timing_parts)}")

    backend_record = records.get(f"{context.name} Backend")
    frontend_record = records.get(f"{context.name} Frontend")
    if backend_record is not None:
        backend_record.log_path = backend_log_path
        backend_plan.final = backend_record.actual_port or backend_plan.final
    if frontend_record is not None:
        frontend_record.log_path = frontend_log_path
        frontend_plan.final = frontend_record.actual_port or frontend_plan.final

    rt._emit(  # type: ignore[attr-defined]
        "service.attach",
        project=context.name,
        backend_port=backend_plan.final if "backend" in selected_service_types else None,
        frontend_port=frontend_plan.final if "frontend" in selected_service_types else None,
        service_group="full",
    )
    _ = backend_command_source, frontend_command_source
    return records


requirements_for_restart_context = _requirements_for_restart_context
requirements_timing_enabled = _requirements_timing_enabled
startup_breakdown_enabled = _startup_breakdown_enabled
maybe_prewarm_docker = _maybe_prewarm_docker
