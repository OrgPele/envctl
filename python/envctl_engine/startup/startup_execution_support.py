from __future__ import annotations

import os
import time
import threading
import concurrent.futures
from typing import Any

from envctl_engine.runtime.command_router import Route
from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.shared.parsing import parse_bool, parse_int
from envctl_engine.state.models import RequirementsResult, ServiceRecord


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


def start_project_context(orchestrator,
    *,
    context: Any,
    mode: str,
    route: Route,
    run_id: str,
) -> tuple[RequirementsResult, dict[str, Any]]:
    rt: Any = orchestrator.runtime
    debug_skip_plan_project_execution = bool(
        route is not None
        and str(getattr(route, 'command', '')).strip().lower() == 'plan'
        and str(getattr(rt, 'env', {}).get('ENVCTL_DEBUG_SKIP_PLAN_PROJECT_EXECUTION', '')).strip().lower() in {'1', 'true', 'yes', 'on'}
    )
    debug_real_noop_execution = bool(
        route is not None
        and str(getattr(route, 'command', '')).strip().lower() == 'plan'
        and (
            bool(route.flags.get("_debug_real_noop_execution"))
            or str(getattr(rt, 'env', {}).get('ENVCTL_DEBUG_PLAN_REAL_NOOP_EXECUTION', '')).strip().lower() in {'1', 'true', 'yes', 'on'}
        )
    )
    debug_exec_group = str(route.flags.get("_debug_exec_group", "")).strip().lower() if route is not None else ""
    if debug_exec_group not in {"requirements", "services", "completion"}:
        debug_exec_group = "completion"
    debug_service_group = str(route.flags.get("_debug_service_group", "")).strip().lower() if route is not None else ""
    if debug_service_group not in {"bootstrap", "launch_attach", "record_merge"}:
        debug_service_group = ""
    debug_skip_plan_requirements = bool(
        route is not None
        and str(getattr(route, 'command', '')).strip().lower() == 'plan'
        and str(getattr(rt, 'env', {}).get('ENVCTL_DEBUG_SKIP_PLAN_REQUIREMENTS', '')).strip().lower() in {'1', 'true', 'yes', 'on'}
    )
    debug_skip_plan_services = bool(
        route is not None
        and str(getattr(route, 'command', '')).strip().lower() == 'plan'
        and str(getattr(rt, 'env', {}).get('ENVCTL_DEBUG_SKIP_PLAN_SERVICES', '')).strip().lower() in {'1', 'true', 'yes', 'on'}
    )
    if debug_skip_plan_project_execution:
        debug_skip_plan_requirements = True
        debug_skip_plan_services = True
    if debug_real_noop_execution:
        debug_skip_plan_requirements = debug_exec_group != "requirements"
        debug_skip_plan_services = debug_exec_group != "services"
        rt._emit(
            "startup.debug_execution_mode",
            project=context.name,
            command='plan',
            mode="real_noop_execution",
            exec_group=debug_exec_group,
        )
    orchestrator._report_progress(route, f"Starting project {context.name}...", project=context.name)
    rt._reserve_project_ports(context)  # type: ignore[attr-defined]
    if debug_skip_plan_requirements:
        skip_reason = (
            f"debug_plan_exec_group:{debug_exec_group}"
            if debug_real_noop_execution
            else ('debug_skip_plan_project_execution' if debug_skip_plan_project_execution else 'debug_skip_plan_requirements')
        )
        rt._emit('requirements.debug_skip', project=context.name, command='plan', reason=skip_reason)
        requirements = _synthetic_requirements_result(rt, context=context, mode=mode, route=route)
    else:
        requirements = orchestrator._requirements_for_restart_context(context=context, mode=mode, route=route)
    if not rt._requirements_ready(requirements):  # type: ignore[attr-defined]
        raise RuntimeError(
            f"Requirements unavailable for {context.name}: "
            + ", ".join(requirements.failures)
        )
    orchestrator._report_progress(
        route,
        f"Requirements ready for {context.name}: "
        + " ".join(
            f"{definition.id}={requirements.component(definition.id).get('final') or requirements.component(definition.id).get('requested')}"
            for definition in dependency_definitions()
            if bool(requirements.component(definition.id).get("enabled", False))
        ),
        project=context.name,
    )
    if debug_skip_plan_services:
        skip_reason = (
            f"debug_plan_exec_group:{debug_exec_group}"
            if debug_real_noop_execution
            else ('debug_skip_plan_project_execution' if debug_skip_plan_project_execution else 'debug_skip_plan_services')
        )
        rt._emit('service.debug_skip', project=context.name, command='plan', reason=skip_reason)
        project_services = _synthetic_service_records(rt, context=context, mode=mode)
    else:
        project_services = orchestrator.start_project_services(
            context,
            requirements=requirements,
            run_id=run_id,
            route=route,
        )
    try:
        skip_truth_assert = bool(debug_service_group in {"bootstrap", "record_merge"})
        if not debug_skip_plan_services and not skip_truth_assert:
            poststart_truth_group = str(getattr(route, "flags", {}).get("_debug_poststart_truth_group", "")).strip().lower() if route is not None else ""
            if poststart_truth_group not in {"pid_wait", "port_fallback", "truth_discovery"}:
                poststart_truth_group = ""
            if poststart_truth_group:
                rt._emit(  # type: ignore[attr-defined]
                    "startup.debug_poststart_truth_group",
                    project=context.name,
                    group=poststart_truth_group,
                    run_pid_wait=poststart_truth_group == "pid_wait",
                    run_port_fallback=poststart_truth_group == "port_fallback",
                    run_truth_discovery=poststart_truth_group == "truth_discovery",
                )
            previous_poststart_truth_group = getattr(rt, "_debug_poststart_truth_group", "")
            setattr(rt, "_debug_poststart_truth_group", poststart_truth_group)
            try:
                rt._assert_project_services_post_start_truth(context=context, services=project_services)  # type: ignore[attr-defined]
            finally:
                setattr(rt, "_debug_poststart_truth_group", previous_poststart_truth_group)
    except RuntimeError:
        rt._terminate_started_services(project_services)  # type: ignore[attr-defined]
        raise
    orchestrator._report_progress(
        route,
        f"Services ready for {context.name}: "
        f"backend={context.ports['backend'].final} frontend={context.ports['frontend'].final}",
        project=context.name,
    )
    return requirements, project_services


def _synthetic_requirements_result(rt: Any, *, context: Any, mode: str, route: Route | None) -> RequirementsResult:
    components: dict[str, dict[str, Any]] = {}
    for definition in dependency_definitions():
        enabled = bool(rt._requirement_enabled(definition.id, mode=mode, route=route))  # type: ignore[attr-defined]
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


def _synthetic_service_records(rt: Any, *, context: Any, mode: str) -> dict[str, Any]:
    project_services = {}
    if rt._service_enabled_for_mode(mode, 'backend'):
        project_services[f'{context.name} Backend'] = ServiceRecord(
            name=f'{context.name} Backend',
            type='backend',
            cwd=str(context.root),
            requested_port=context.ports['backend'].final,
            actual_port=context.ports['backend'].final,
            status='unknown',
            synthetic=True,
        )
    if rt._service_enabled_for_mode(mode, 'frontend'):
        project_services[f'{context.name} Frontend'] = ServiceRecord(
            name=f'{context.name} Frontend',
            type='frontend',
            cwd=str(context.root),
            requested_port=context.ports['frontend'].final,
            actual_port=context.ports['frontend'].final,
            status='unknown',
            synthetic=True,
        )
    return project_services


def _synthetic_running_service_records(rt: Any, *, context: Any, mode: str) -> dict[str, Any]:
    project_services = {}
    if rt._service_enabled_for_mode(mode, 'backend'):
        backend_port = context.ports['backend'].final
        project_services[f'{context.name} Backend'] = ServiceRecord(
            name=f'{context.name} Backend',
            type='backend',
            cwd=str(context.root),
            pid=os.getpid(),
            requested_port=backend_port,
            actual_port=backend_port,
            status='running',
            synthetic=True,
            listener_pids=[os.getpid()],
        )
    if rt._service_enabled_for_mode(mode, 'frontend'):
        frontend_port = context.ports['frontend'].final
        project_services[f'{context.name} Frontend'] = ServiceRecord(
            name=f'{context.name} Frontend',
            type='frontend',
            cwd=str(context.root),
            pid=os.getpid() + 1,
            requested_port=frontend_port,
            actual_port=frontend_port,
            status='running',
            synthetic=True,
            listener_pids=[os.getpid() + 1],
        )
    return project_services


def startup_summary_payload(orchestrator, *, project_contexts: list[Any], start_event_index: int, startup_started_at: float) -> dict[str, object]:
    rt: Any = orchestrator.runtime
    event_slice = list(getattr(rt, "events", [])[start_event_index:])
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
        "top_components": [
            {"name": name, "duration_ms": round(duration, 2)}
            for name, duration in top_components[:3]
        ],
    }


def print_startup_summary(orchestrator, *, project_contexts: list[Any], start_event_index: int, startup_started_at: float) -> None:
    payload = startup_summary_payload(
        orchestrator,
        project_contexts=project_contexts,
        start_event_index=start_event_index,
        startup_started_at=startup_started_at,
    )
    top = ", ".join(
        f"{item['name']}={float(item['duration_ms']):.1f}ms"
        for item in payload["top_components"]
    )
    print(
        "Startup summary: "
        f"requirements={float(payload['requirements_ms']):.1f}ms "
        f"services={float(payload['services_ms']):.1f}ms "
        f"total={float(payload['startup_ms']):.1f}ms"
        + (f" top=[{top}]" if top else "")
    )


def _float_ms(value: object) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0

def _requirements_for_restart_context(orchestrator,
    *,
    context: Any,
    mode: str,
    route: Route | None,
) -> RequirementsResult:
    rt: Any = orchestrator.runtime
    if route is None:
        return orchestrator.start_requirements_for_project(context, mode=mode, route=route)
    if not bool(route.flags.get("_restart_request")):
        return orchestrator.start_requirements_for_project(context, mode=mode, route=route)
    if orchestrator._restart_include_requirements(route):
        return orchestrator.start_requirements_for_project(context, mode=mode, route=route)

    previous = rt._try_load_existing_state(mode=mode, strict_mode_match=True)  # type: ignore[attr-defined]
    if previous is not None:
        existing = previous.requirements.get(context.name)
        if isinstance(existing, RequirementsResult):
            rt._emit(  # type: ignore[attr-defined]
                "requirements.restart.reuse",
                project=context.name,
                include_requirements=False,
            )
            return existing

    rt._emit(  # type: ignore[attr-defined]
        "requirements.restart.reuse_missing",
        project=context.name,
        include_requirements=False,
    )
    return orchestrator.start_requirements_for_project(context, mode=mode, route=route)

def start_requirements_for_project(orchestrator,
    context: Any,
    *,
    mode: str,
    route: Route | None = None,
) -> RequirementsResult:
    rt: Any = orchestrator.runtime
    port_allocator = orchestrator._port_allocator(rt)
    failures: list[str] = []
    timing_enabled = orchestrator._requirements_timing_enabled(route)
    requirements_started = time.monotonic()
    component_timings_ms: dict[str, float] = {}
    definitions = dependency_definitions()
    reserve_lock = threading.Lock()
    progress_state_lock = threading.Lock()

    def plan_for_dependency(dependency_id: str):  # noqa: ANN001
        definition = next(defn for defn in definitions if defn.id == dependency_id)
        return context.ports[definition.resources[0].legacy_port_key]

    setup_hook = rt._invoke_envctl_hook(context=context, hook_name="envctl_setup_infrastructure")  # type: ignore[attr-defined]
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
                "enabled": rt._requirement_enabled(definition.id, mode=mode, route=route),  # type: ignore[attr-defined]
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
            return rt._requirements_result_from_hook_payload(  # type: ignore[attr-defined]
                context=context,
                mode=mode,
                payload=payload,
            )

    def reserve_next(port: int) -> int:
        with reserve_lock:
            return port_allocator.reserve_next(port, owner=f"{context.name}:requirements")  # type: ignore[attr-defined]

    enabled_definitions = [
        definition
        for definition in definitions
        if bool(rt._requirement_enabled(definition.id, mode=mode, route=route))  # type: ignore[attr-defined]
    ]
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

    def run_component(component: str, plan: Any, *, strict: bool = False):  # noqa: ANN001
        component_started = time.monotonic()
        with progress_state_lock:
            pending_requirements.discard(component)
            active_requirements.add(component)
            emit_requirements_progress()
        enabled = bool(rt._requirement_enabled(component, mode=mode, route=route))  # type: ignore[attr-defined]
        try:
            if enabled:
                outcome = rt._start_requirement_component(  # type: ignore[attr-defined]
                    context,
                    component,
                    plan,
                    reserve_next,
                    strict=strict,
                    route=route,
                )
            else:
                outcome = rt._skipped_requirement(component, plan)  # type: ignore[attr-defined]
            duration_ms = round((time.monotonic() - component_started) * 1000.0, 2)
            component_timings_ms[component] = duration_ms
            rt._emit(  # type: ignore[attr-defined]
                "requirements.timing.component",
                project=context.name,
                requirement=component,
                duration_ms=duration_ms,
                enabled=enabled,
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
    raw_parallel = rt.env.get("ENVCTL_REQUIREMENTS_PARALLEL") or rt.config.raw.get("ENVCTL_REQUIREMENTS_PARALLEL")  # type: ignore[attr-defined]
    parallel_enabled = parse_bool(raw_parallel, True) and len(enabled_definitions) > 1
    raw_workers = rt.env.get("ENVCTL_REQUIREMENTS_PARALLEL_MAX") or rt.config.raw.get("ENVCTL_REQUIREMENTS_PARALLEL_MAX")  # type: ignore[attr-defined]
    worker_limit = max(parse_int(raw_workers, 4), 1)
    worker_count = min(worker_limit, len(enabled_definitions)) if parallel_enabled else 1
    rt._emit(  # type: ignore[attr-defined]
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

    outcomes: dict[str, object] = {}
    if parallel_enabled and worker_count > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {}
            for definition in definitions:
                strict = bool(definition.id == "n8n" and rt.config.strict_n8n_bootstrap)  # type: ignore[attr-defined]
                future = executor.submit(run_component, definition.id, plan_for_dependency(definition.id), strict=strict)
                future_map[future] = definition.id
            for future in concurrent.futures.as_completed(future_map):
                definition_id = future_map[future]
                outcomes[definition_id] = future.result()
    else:
        for definition in definitions:
            strict = bool(definition.id == "n8n" and rt.config.strict_n8n_bootstrap)  # type: ignore[attr-defined]
            outcomes[definition.id] = run_component(definition.id, plan_for_dependency(definition.id), strict=strict)

    for outcome in outcomes.values():
        if not outcome.success:
            failures.append(f"{outcome.service_name}:{outcome.failure_class}:{outcome.error}")

    health = "healthy" if not failures else "degraded"
    total_duration_ms = round((time.monotonic() - requirements_started) * 1000.0, 2)
    rt._emit(  # type: ignore[attr-defined]
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
    components = {}
    for definition in definitions:
        outcome = outcomes[definition.id]
        components[definition.id] = {
            "requested": outcome.requested_port,
            "final": outcome.final_port,
            "resources": {"requested": outcome.requested_port, "primary": outcome.final_port},
            "retries": outcome.retries,
            "success": outcome.success,
            "simulated": outcome.simulated,
            "enabled": rt._requirement_enabled(definition.id, mode=mode, route=route),  # type: ignore[attr-defined]
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

def _requirements_timing_enabled(orchestrator, route: Route | None) -> bool:
    rt = orchestrator.runtime
    raw_force = rt.env.get("ENVCTL_DEBUG_RESTORE_TIMING") or rt.config.raw.get("ENVCTL_DEBUG_RESTORE_TIMING")  # type: ignore[attr-defined]
    if bool(raw_force) and str(raw_force).strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if route is not None and (bool(route.flags.get("debug_ui")) or bool(route.flags.get("debug_ui_deep"))):
        return True
    raw_mode = (rt.env.get("ENVCTL_DEBUG_UI_MODE") or rt.config.raw.get("ENVCTL_DEBUG_UI_MODE") or "").strip().lower()  # type: ignore[attr-defined]
    return raw_mode in {"standard", "deep"}

def _docker_prewarm_enabled(orchestrator, route: Route | None) -> bool:
    _ = route
    rt = orchestrator.runtime
    raw = rt.env.get("ENVCTL_DOCKER_PREWARM") or rt.config.raw.get("ENVCTL_DOCKER_PREWARM")  # type: ignore[attr-defined]
    return parse_bool(raw, True)

def _docker_prewarm_timeout_seconds(orchestrator, route: Route | None) -> int:
    _ = route
    rt = orchestrator.runtime
    raw = rt.env.get("ENVCTL_DOCKER_PREWARM_TIMEOUT_SECONDS") or rt.config.raw.get("ENVCTL_DOCKER_PREWARM_TIMEOUT_SECONDS")  # type: ignore[attr-defined]
    value = parse_int(raw, 10)
    return max(value, 1)

def _prewarm_requires_startup_requirements(orchestrator, *, mode: str, route: Route | None) -> bool:
    rt: Any = orchestrator.runtime
    for definition in dependency_definitions():
        if bool(rt._requirement_enabled(definition.id, mode=mode, route=route)):  # type: ignore[attr-defined]
            return True
    return False

def _maybe_prewarm_docker(orchestrator, *, route: Route | None, mode: str) -> None:
    rt: Any = orchestrator.runtime
    if not orchestrator._docker_prewarm_enabled(route):
        rt._emit("requirements.docker_prewarm", used=False, reason="disabled")
        return
    if not orchestrator._prewarm_requires_startup_requirements(mode=mode, route=route):
        rt._emit("requirements.docker_prewarm", used=False, reason="no_enabled_requirements")
        return
    if not rt._command_exists("docker"):  # type: ignore[attr-defined]
        rt._emit("requirements.docker_prewarm", used=False, reason="docker_missing")
        return
    timeout_s = orchestrator._docker_prewarm_timeout_seconds(route)
    started = time.monotonic()
    result = rt.process_runner.run(["docker", "ps"], timeout=float(timeout_s))  # type: ignore[attr-defined]
    duration_ms = round((time.monotonic() - started) * 1000.0, 2)
    returncode = int(getattr(result, "returncode", 1))
    stderr = str(getattr(result, "stderr", "") or "")
    stdout = str(getattr(result, "stdout", "") or "")
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

def _startup_breakdown_enabled(orchestrator, route: Route | None) -> bool:
    rt = orchestrator.runtime
    raw = rt.env.get("ENVCTL_DEBUG_STARTUP_BREAKDOWN") or rt.config.raw.get("ENVCTL_DEBUG_STARTUP_BREAKDOWN")  # type: ignore[attr-defined]
    if parse_bool(raw, False):
        return True
    if route is not None and (bool(route.flags.get("debug_ui")) or bool(route.flags.get("debug_ui_deep"))):
        return True
    raw_mode = (rt.env.get("ENVCTL_DEBUG_UI_MODE") or rt.config.raw.get("ENVCTL_DEBUG_UI_MODE") or "").strip().lower()  # type: ignore[attr-defined]
    return raw_mode in {"deep"}

def _service_attach_parallel_enabled(orchestrator, *, route: Route | None, selected_service_types: set[str]) -> bool:
    if selected_service_types != {"backend", "frontend"}:
        return False
    if route is not None:
        route_value = route.flags.get("service_parallel")
        if isinstance(route_value, bool):
            return route_value
    rt = orchestrator.runtime
    raw = rt.env.get("ENVCTL_SERVICE_ATTACH_PARALLEL") or rt.config.raw.get("ENVCTL_SERVICE_ATTACH_PARALLEL")  # type: ignore[attr-defined]
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}

def start_project_services(orchestrator,
    context: Any,
    *,
    requirements: RequirementsResult,
    run_id: str,
    route: Route | None = None,
) -> dict[str, Any]:
    rt: Any = orchestrator.runtime
    port_allocator = orchestrator._port_allocator(rt)
    process_runtime = orchestrator._process_runtime(rt)
    effective_mode = str(route.mode if route is not None else "main").strip().lower() or "main"
    service_group = str(getattr(route, "flags", {}).get("_debug_service_group", "")).strip().lower() if route is not None else ""
    if service_group not in {"bootstrap", "launch_attach", "record_merge"}:
        service_group = ""
    attach_group = str(getattr(route, "flags", {}).get("_debug_attach_group", "")).strip().lower() if route is not None else ""
    if attach_group not in {"process_start", "listener_probe", "attach_merge"}:
        attach_group = ""
    listener_group = str(getattr(route, "flags", {}).get("_debug_listener_group", "")).strip().lower() if route is not None else ""
    if listener_group not in {"pid_wait", "port_fallback", "rebound_discovery"}:
        listener_group = ""
    pid_wait_group = str(getattr(route, "flags", {}).get("_debug_pid_wait_group", "")).strip().lower() if route is not None else ""
    if pid_wait_group not in {"signal_gate", "pid_port_lsof", "tree_port_scan"}:
        pid_wait_group = ""
    pid_wait_service = str(getattr(route, "flags", {}).get("_debug_pid_wait_service", "")).strip().lower() if route is not None else ""
    if pid_wait_service not in {"backend", "frontend", "both"}:
        pid_wait_service = ""
    backend_actual_group = str(getattr(route, "flags", {}).get("_debug_backend_actual_group", "")).strip().lower() if route is not None else ""
    if backend_actual_group not in {"request_setup", "detect_call", "resolve_actual"}:
        backend_actual_group = ""
    run_bootstrap = service_group in {"", "bootstrap"}
    run_launch_attach = service_group in {"", "launch_attach"}
    run_record_merge = service_group in {"", "record_merge"}
    if service_group:
        rt._emit(  # type: ignore[attr-defined]
            "startup.debug_service_group",
            project=context.name,
            group=service_group,
            run_bootstrap=run_bootstrap,
            run_launch_attach=run_launch_attach,
            run_record_merge=run_record_merge,
        )
    if attach_group:
        rt._emit(  # type: ignore[attr-defined]
            "startup.debug_attach_group",
            project=context.name,
            group=attach_group,
            run_process_start=attach_group == "process_start",
            run_listener_probe=attach_group == "listener_probe",
            run_attach_merge=attach_group == "attach_merge",
        )
    if listener_group:
        rt._emit(  # type: ignore[attr-defined]
            "startup.debug_listener_group",
            project=context.name,
            group=listener_group,
            run_pid_wait=listener_group == "pid_wait",
            run_port_fallback=listener_group == "port_fallback",
            run_rebound_discovery=listener_group == "rebound_discovery",
        )
    if pid_wait_group:
        rt._emit(  # type: ignore[attr-defined]
            "startup.debug_pid_wait_group",
            project=context.name,
            group=pid_wait_group,
            run_signal_gate=pid_wait_group == "signal_gate",
            run_pid_port_lsof=pid_wait_group == "pid_port_lsof",
            run_tree_port_scan=pid_wait_group == "tree_port_scan",
        )
    if pid_wait_service:
        rt._emit(  # type: ignore[attr-defined]
            "startup.debug_pid_wait_service",
            project=context.name,
            group=pid_wait_service,
            run_backend=pid_wait_service == "backend",
            run_frontend=pid_wait_service == "frontend",
            run_both=pid_wait_service == "both",
        )
    if backend_actual_group:
        rt._emit(  # type: ignore[attr-defined]
            "startup.debug_backend_actual_group",
            project=context.name,
            group=backend_actual_group,
            run_request_setup=backend_actual_group == "request_setup",
            run_detect_call=backend_actual_group == "detect_call",
            run_resolve_actual=backend_actual_group == "resolve_actual",
        )
    backend_plan = context.ports["backend"]
    frontend_plan = context.ports["frontend"]
    backend_cwd = context.root / str(getattr(rt.config, "backend_dir_name", "backend"))
    frontend_cwd = context.root / str(getattr(rt.config, "frontend_dir_name", "frontend"))
    if not backend_cwd.is_dir():
        backend_cwd = context.root
    if not frontend_cwd.is_dir():
        frontend_cwd = context.root

    services_hook = rt._invoke_envctl_hook(context=context, hook_name="envctl_define_services")  # type: ignore[attr-defined]
    if services_hook.found:
        if not services_hook.success:
            raise RuntimeError(f"envctl_define_services hook failed for {context.name}: {services_hook.error or 'failed'}")
        payload = services_hook.payload if isinstance(services_hook.payload, dict) else {}
        hook_records = rt._services_from_hook_payload(context=context, payload=payload)  # type: ignore[attr-defined]
        if hook_records:
            return hook_records
        if bool(payload.get("skip_default_services")):
            raise RuntimeError(
                f"envctl_define_services hook requested skip_default_services for {context.name} but returned no services"
            )

    run_logs_dir = rt._run_dir_path(run_id)  # type: ignore[attr-defined]
    safe_project_name = context.name.replace("/", "_").replace(" ", "_")
    backend_log_path = str(run_logs_dir / f"{safe_project_name}_backend.log")
    frontend_log_path = str(run_logs_dir / f"{safe_project_name}_frontend.log")
    project_env_base = rt._project_service_env(context, requirements=requirements, route=route)  # type: ignore[attr-defined]
    backend_env_file, backend_env_is_default = rt._resolve_backend_env_file(  # type: ignore[attr-defined]
        context=context,
        backend_cwd=backend_cwd,
    )
    frontend_env_file = rt._resolve_frontend_env_file(  # type: ignore[attr-defined]
        context=context,
        frontend_cwd=frontend_cwd,
    )
    backend_env_extra = rt._service_env_from_file(  # type: ignore[attr-defined]
        base_env=project_env_base,
        env_file=backend_env_file,
        include_app_env_file=True,
    )
    frontend_env_extra = rt._service_env_from_file(  # type: ignore[attr-defined]
        base_env=project_env_base,
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
        rt._emit(  # type: ignore[attr-defined]
            "service.attach.skipped",
            project=context.name,
            mode=effective_mode,
            reason="all_services_disabled",
        )
        return {}
    service_started = time.monotonic()
    prepare_backend_duration_ms = 0.0
    if run_bootstrap and "backend" in selected_service_types:
        prepare_backend_started = time.monotonic()
        rt._prepare_backend_runtime(  # type: ignore[attr-defined]
            context=context,
            backend_cwd=backend_cwd,
            backend_log_path=backend_log_path,
            project_env_base=project_env_base,
            route=route,
            backend_env_file=backend_env_file,
            backend_env_is_default=backend_env_is_default,
        )
        prepare_backend_duration_ms = round((time.monotonic() - prepare_backend_started) * 1000.0, 2)
        rt._emit(  # type: ignore[attr-defined]
            "service.timing.component",
            project=context.name,
            component="prepare_backend_runtime",
            duration_ms=prepare_backend_duration_ms,
        )
    prepare_frontend_duration_ms = 0.0
    if run_bootstrap and "frontend" in selected_service_types:
        prepare_frontend_started = time.monotonic()
        rt._prepare_frontend_runtime(  # type: ignore[attr-defined]
            context=context,
            frontend_cwd=frontend_cwd,
            frontend_log_path=frontend_log_path,
            project_env_base=project_env_base,
            frontend_env_file=frontend_env_file,
            backend_port=backend_plan.final,
            route=route,
        )
        prepare_frontend_duration_ms = round((time.monotonic() - prepare_frontend_started) * 1000.0, 2)
        rt._emit(  # type: ignore[attr-defined]
            "service.timing.component",
            project=context.name,
            component="prepare_frontend_runtime",
            duration_ms=prepare_frontend_duration_ms,
        )
    rebound_delta = parse_int(rt.env.get("ENVCTL_TEST_FRONTEND_REBOUND_DELTA"), 0)
    backend_command_source = None
    if "backend" in selected_service_types:
        backend_command_source = rt._service_command_source(  # type: ignore[attr-defined]
            service_name="backend",
            project_root=context.root,
            port=backend_plan.final,
        )
    frontend_command_source = None
    if "frontend" in selected_service_types:
        frontend_command_source = rt._service_command_source(  # type: ignore[attr-defined]
            service_name="frontend",
            project_root=context.root,
            port=(frontend_plan.final + rebound_delta if rebound_delta > 0 else frontend_plan.final),
        )

    def reserve_next(port: int) -> int:
        return port_allocator.reserve_next(port, owner=f"{context.name}:services")  # type: ignore[attr-defined]

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
        process = process_runtime.start_background(  # type: ignore[attr-defined]
            command,
            cwd=backend_cwd,
            env=rt._command_env(port=port, extra=backend_env_extra),  # type: ignore[attr-defined]
            stdout_path=backend_log_path,
            stderr_path=backend_log_path,
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
        process = process_runtime.start_background(  # type: ignore[attr-defined]
            command,
            cwd=frontend_cwd,
            env=rt._command_env(port=launch_port, extra=frontend_env_extra),  # type: ignore[attr-defined]
            stdout_path=frontend_log_path,
            stderr_path=frontend_log_path,
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

    def pid_wait_service_selected(service_name: str) -> bool:
        if listener_group != "pid_wait" or not pid_wait_service or pid_wait_service == "both":
            return True
        return pid_wait_service == service_name

    def detect_backend_actual(pid: int | None, requested: int) -> int:
        rt._emit("service.bind.requested", project=context.name, service="backend", requested_port=requested)  # type: ignore[attr-defined]
        detect_started = time.monotonic()
        if backend_actual_override > 0:
            actual = backend_actual_override
        elif not pid_wait_service_selected("backend"):
            actual = requested
            rt._emit(  # type: ignore[attr-defined]
                "startup.debug_pid_wait_service.synthetic_actual",
                project=context.name,
                service="backend",
                group=pid_wait_service,
                requested_port=requested,
            )
        else:
            if backend_actual_group == "request_setup":
                actual = requested
                rt._emit(  # type: ignore[attr-defined]
                    "startup.debug_backend_actual_group.synthetic_actual",
                    project=context.name,
                    service="backend",
                    group=backend_actual_group,
                    requested_port=requested,
                )
            else:
                if backend_actual_group == "resolve_actual":
                    detected = requested
                    rt._emit(  # type: ignore[attr-defined]
                        "startup.debug_backend_actual_group.synthetic_detected",
                        project=context.name,
                        service="backend",
                        group=backend_actual_group,
                        requested_port=requested,
                    )
                else:
                    detected = rt._detect_service_actual_port(  # type: ignore[attr-defined]
                        pid=pid,
                        requested_port=requested,
                        service_name="backend",
                        debug_listener_group=listener_group,
                        debug_pid_wait_group=pid_wait_group,
                    )
                if backend_actual_group == "detect_call":
                    actual = detected if detected is not None else requested
                    if detected is None:
                        rt._emit(  # type: ignore[attr-defined]
                            "startup.debug_backend_actual_group.synthetic_actual",
                            project=context.name,
                            service="backend",
                            group=backend_actual_group,
                            requested_port=requested,
                        )
                elif detected is not None:
                    actual = detected
                    if actual != requested:
                        rt._emit("port.rebound", project=context.name, service="backend", port=actual)  # type: ignore[attr-defined]
                elif listener_group:
                    actual = requested
                    rt._emit(  # type: ignore[attr-defined]
                        "startup.debug_listener_group.synthetic_actual",
                        project=context.name,
                        service="backend",
                        group=listener_group,
                        requested_port=requested,
                    )
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
            if not pid_wait_service_selected("frontend"):
                actual = probe_port
                rt._emit(  # type: ignore[attr-defined]
                    "startup.debug_pid_wait_service.synthetic_actual",
                    project=context.name,
                    service="frontend",
                    group=pid_wait_service,
                    requested_port=probe_port,
                )
                rt._emit("service.bind.actual", project=context.name, service="frontend", actual_port=actual)  # type: ignore[attr-defined]
                rt._emit(  # type: ignore[attr-defined]
                    "service.attach.phase",
                    project=context.name,
                    service="frontend",
                    phase="actual_port_detection",
                    duration_ms=round((time.monotonic() - detect_started) * 1000.0, 2),
                )
                return actual
            detected = rt._detect_service_actual_port(  # type: ignore[attr-defined]
                pid=pid,
                requested_port=probe_port,
                service_name="frontend",
                debug_listener_group=listener_group,
                debug_pid_wait_group=pid_wait_group,
            )
            if detected is None and not listener_group and probe_port != requested:
                detected = rt._detect_service_actual_port(  # type: ignore[attr-defined]
                    pid=pid,
                    requested_port=requested,
                    service_name="frontend",
                    debug_pid_wait_group=pid_wait_group,
                )
            if detected is not None:
                actual = detected
                if actual != requested:
                    rt._emit("port.rebound", project=context.name, service="frontend", port=actual)  # type: ignore[attr-defined]
            elif listener_group:
                actual = probe_port
                rt._emit(  # type: ignore[attr-defined]
                    "startup.debug_listener_group.synthetic_actual",
                    project=context.name,
                    service="frontend",
                    group=listener_group,
                    requested_port=probe_port,
                )
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

    attach_parallel = orchestrator._service_attach_parallel_enabled(
        route=route,
        selected_service_types=selected_service_types,
    )
    attach_duration_ms = 0.0
    records: dict[str, Any]
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

    if run_launch_attach and attach_group == "process_start":
        attach_started = time.monotonic()
        project_services: dict[str, Any] = {}
        if "backend" in selected_service_types:
            backend_started, backend_error, backend_pid = start_backend(backend_plan.final)
            if not backend_started:
                raise RuntimeError(backend_error or f"failed starting backend for {context.name}")
            project_services[f"{context.name} Backend"] = _running_service_record(
                service_name="backend",
                requested_port=backend_plan.final,
                actual_port=backend_plan.final,
                pid=backend_pid,
                cwd=backend_cwd,
                log_path=backend_log_path,
            )
        if "frontend" in selected_service_types:
            frontend_started, frontend_error, frontend_pid = start_frontend(frontend_plan.final)
            if not frontend_started:
                raise RuntimeError(frontend_error or f"failed starting frontend for {context.name}")
            project_services[f"{context.name} Frontend"] = _running_service_record(
                service_name="frontend",
                requested_port=frontend_plan.final,
                actual_port=frontend_plan.final,
                pid=frontend_pid,
                cwd=frontend_cwd,
                log_path=frontend_log_path,
            )
        attach_duration_ms = round((time.monotonic() - attach_started) * 1000.0, 2)
        rt._emit(  # type: ignore[attr-defined]
            "service.timing.component",
            project=context.name,
            component="start_project_with_attach",
            duration_ms=attach_duration_ms,
        )
        total_duration_ms = round((time.monotonic() - service_started) * 1000.0, 2)
        rt._emit(  # type: ignore[attr-defined]
            "service.timing.summary",
            project=context.name,
            prepare_backend_runtime=prepare_backend_duration_ms,
            prepare_frontend_runtime=prepare_frontend_duration_ms,
            start_project_with_attach=attach_duration_ms,
            total=total_duration_ms,
        )
        return project_services

    if run_launch_attach and attach_group == "listener_probe":
        attach_started = time.monotonic()
        project_services = {}
        if "backend" in selected_service_types:
            backend_started, backend_error, backend_pid = start_backend(backend_plan.final)
            if not backend_started:
                raise RuntimeError(backend_error or f"failed starting backend for {context.name}")
            backend_actual = detect_backend_actual(backend_pid, backend_plan.final)
            project_services[f"{context.name} Backend"] = _running_service_record(
                service_name="backend",
                requested_port=backend_plan.final,
                actual_port=backend_actual,
                pid=backend_pid,
                cwd=backend_cwd,
                log_path=backend_log_path,
            )
        if "frontend" in selected_service_types:
            frontend_started, frontend_error, frontend_pid = start_frontend(frontend_plan.final)
            if not frontend_started:
                raise RuntimeError(frontend_error or f"failed starting frontend for {context.name}")
            frontend_actual = detect_frontend_actual(frontend_pid, frontend_plan.final)
            project_services[f"{context.name} Frontend"] = _running_service_record(
                service_name="frontend",
                requested_port=frontend_plan.final,
                actual_port=frontend_actual,
                pid=frontend_pid,
                cwd=frontend_cwd,
                log_path=frontend_log_path,
            )
        attach_duration_ms = round((time.monotonic() - attach_started) * 1000.0, 2)
        rt._emit(  # type: ignore[attr-defined]
            "service.timing.component",
            project=context.name,
            component="start_project_with_attach",
            duration_ms=attach_duration_ms,
        )
        total_duration_ms = round((time.monotonic() - service_started) * 1000.0, 2)
        rt._emit(  # type: ignore[attr-defined]
            "service.timing.summary",
            project=context.name,
            prepare_backend_runtime=prepare_backend_duration_ms,
            prepare_frontend_runtime=prepare_frontend_duration_ms,
            start_project_with_attach=attach_duration_ms,
            total=total_duration_ms,
        )
        return project_services

    if run_launch_attach and attach_group == "attach_merge":
        project_services = _synthetic_running_service_records(
            rt,
            context=context,
            mode=effective_mode,
        )
        total_duration_ms = round((time.monotonic() - service_started) * 1000.0, 2)
        rt._emit(  # type: ignore[attr-defined]
            "service.timing.summary",
            project=context.name,
            prepare_backend_runtime=prepare_backend_duration_ms,
            prepare_frontend_runtime=prepare_frontend_duration_ms,
            start_project_with_attach=0.0,
            total=total_duration_ms,
        )
        return project_services

    if run_launch_attach:
        rt._emit(  # type: ignore[attr-defined]
            "service.attach.execution",
            project=context.name,
            mode="parallel" if attach_parallel else "sequential",
            selected_service_types=sorted(selected_service_types),
        )
        if orchestrator._requirements_timing_enabled(route) and not orchestrator._suppress_timing_output(route):
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
    elif run_record_merge:
        records = _synthetic_running_service_records(rt, context=context, mode=effective_mode)
    else:
        records = _synthetic_service_records(rt, context=context, mode=effective_mode)
    total_duration_ms = round((time.monotonic() - service_started) * 1000.0, 2)
    if run_launch_attach:
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
    if orchestrator._requirements_timing_enabled(route) and not orchestrator._suppress_timing_output(route):
        timing_parts: list[str] = []
        if run_bootstrap and "backend" in selected_service_types:
            timing_parts.append(f"prepare_backend_runtime={prepare_backend_duration_ms:.1f}ms")
        if run_bootstrap and "frontend" in selected_service_types:
            timing_parts.append(f"prepare_frontend_runtime={prepare_frontend_duration_ms:.1f}ms")
        if run_launch_attach:
            timing_parts.append(f"start_project_with_attach={attach_duration_ms:.1f}ms")
        timing_parts.append(f"total={total_duration_ms:.1f}ms")
        print(
            "Service timing for "
            f"{context.name}: {' '.join(timing_parts)}"
        )

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
        service_group=(service_group or "full"),
    )
    _ = backend_command_source, frontend_command_source
    return records
