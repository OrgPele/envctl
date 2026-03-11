from __future__ import annotations

import concurrent.futures
import re
import threading
import time

from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.requirements.orchestrator import RequirementOutcome
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.runtime_context import resolve_port_allocator
from envctl_engine.shared.parsing import parse_bool, parse_int
from envctl_engine.startup.protocols import ProjectContextLike, StartupOrchestratorLike, StartupRuntime
from envctl_engine.state.models import RequirementsResult

_DOCKER_SOCKET_PATTERNS = (
    re.compile(r"unix://(?P<path>[^\s;]+docker\.sock)"),
    re.compile(r"dial unix (?P<path>[^\s:;]+docker\.sock)"),
)


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


def requirements_failure_message(project_name: str, requirements: RequirementsResult) -> str:
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


def requirements_for_restart_context(
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
    timing_enabled = requirements_timing_enabled(orchestrator, route)
    requirements_started = time.monotonic()
    component_timings_ms: dict[str, float] = {}
    definitions = dependency_definitions()
    reserve_lock = threading.Lock()
    progress_state_lock = threading.Lock()

    definition_ports = {
        definition.id: context.ports[definition.resources[0].legacy_port_key] for definition in definitions
    }

    def plan_for_dependency(dependency_id: str) -> object:
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


def requirements_timing_enabled(orchestrator: StartupOrchestratorLike, route: Route | None) -> bool:
    rt = orchestrator.runtime
    raw_force = rt.env.get("ENVCTL_DEBUG_RESTORE_TIMING") or rt.config.raw.get("ENVCTL_DEBUG_RESTORE_TIMING")
    if bool(raw_force) and str(raw_force).strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if route is not None and (bool(route.flags.get("debug_ui")) or bool(route.flags.get("debug_ui_deep"))):
        return True
    raw_mode = (rt.env.get("ENVCTL_DEBUG_UI_MODE") or rt.config.raw.get("ENVCTL_DEBUG_UI_MODE") or "").strip().lower()
    return raw_mode in {"standard", "deep"}


def docker_prewarm_enabled(orchestrator: StartupOrchestratorLike, route: Route | None) -> bool:
    _ = route
    rt = orchestrator.runtime
    raw = rt.env.get("ENVCTL_DOCKER_PREWARM") or rt.config.raw.get("ENVCTL_DOCKER_PREWARM")
    return parse_bool(raw, True)


def docker_prewarm_timeout_seconds(orchestrator: StartupOrchestratorLike, route: Route | None) -> int:
    _ = route
    rt = orchestrator.runtime
    raw = rt.env.get("ENVCTL_DOCKER_PREWARM_TIMEOUT_SECONDS") or rt.config.raw.get(
        "ENVCTL_DOCKER_PREWARM_TIMEOUT_SECONDS"
    )
    value = parse_int(raw, 10)
    return max(value, 1)


def prewarm_requires_startup_requirements(
    orchestrator: StartupOrchestratorLike, *, mode: str, route: Route | None
) -> bool:
    rt = orchestrator.runtime
    for definition in dependency_definitions():
        if bool(rt._requirement_enabled(definition.id, mode=mode, route=route)):
            return True
    return False


def maybe_prewarm_docker(orchestrator: StartupOrchestratorLike, *, route: Route | None, mode: str) -> None:
    rt = orchestrator.runtime
    if not docker_prewarm_enabled(orchestrator, route):
        rt._emit("requirements.docker_prewarm", used=False, reason="disabled")
        return
    if not prewarm_requires_startup_requirements(orchestrator, mode=mode, route=route):
        rt._emit("requirements.docker_prewarm", used=False, reason="no_enabled_requirements")
        return
    if not rt._command_exists("docker"):
        rt._emit("requirements.docker_prewarm", used=False, reason="docker_missing")
        return
    timeout_s = docker_prewarm_timeout_seconds(orchestrator, route)
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


def startup_breakdown_enabled(orchestrator: StartupOrchestratorLike, route: Route | None) -> bool:
    rt = orchestrator.runtime
    raw = rt.env.get("ENVCTL_DEBUG_STARTUP_BREAKDOWN") or rt.config.raw.get("ENVCTL_DEBUG_STARTUP_BREAKDOWN")
    if parse_bool(raw, False):
        return True
    if route is not None and (bool(route.flags.get("debug_ui")) or bool(route.flags.get("debug_ui_deep"))):
        return True
    raw_mode = (rt.env.get("ENVCTL_DEBUG_UI_MODE") or rt.config.raw.get("ENVCTL_DEBUG_UI_MODE") or "").strip().lower()
    return raw_mode in {"deep"}


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
