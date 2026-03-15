from __future__ import annotations

import concurrent.futures
import os
from dataclasses import dataclass
from pathlib import Path
import time

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.runtime_context import resolve_port_allocator
from envctl_engine.shared.parsing import parse_bool, parse_int
from envctl_engine.startup.protocols import ProjectContextLike, StartupOrchestratorLike
from envctl_engine.startup.requirements_execution import requirements_timing_enabled
from envctl_engine.state.models import RequirementsResult, ServiceRecord


@dataclass(slots=True)
class PreparedServiceLaunch:
    service_name: str
    cwd: Path
    log_path: str
    requested_port: int
    env: dict[str, str]
    command_source: str | None


@dataclass(slots=True)
class LaunchedServiceRuntime:
    service_name: str
    requested_port: int
    actual_port: int
    pid: int | None
    log_path: str


def service_attach_parallel_enabled(
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


def service_prep_parallel_enabled(
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


def backend_listener_expected_for_mode(config: object, mode: str) -> bool:
    helper = getattr(config, "backend_expects_listener_for_mode", None)
    if callable(helper):
        return bool(helper(mode))
    normalized = str(mode).strip().lower()
    if normalized == "trees":
        return bool(getattr(config, "trees_backend_expect_listener", True))
    return bool(getattr(config, "main_backend_expect_listener", True))


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
    backend_log_path = str(run_logs_dir / f"{safe_project_name}_backend.txt")
    frontend_log_path = str(run_logs_dir / f"{safe_project_name}_frontend.txt")
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
    backend_listener_expected = backend_listener_expected_for_mode(rt.config, effective_mode)
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
    attach_parallel = service_attach_parallel_enabled(
        orchestrator,
        route=route,
        selected_service_types=selected_service_types,
    )
    prep_parallel = service_prep_parallel_enabled(
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

    prepared_launches: dict[str, PreparedServiceLaunch] = {}
    command_env_builder = getattr(rt, "_command_env", None)
    if not callable(command_env_builder):
        command_env_builder = lambda *, port, extra=None: dict(extra or {})
    if "backend" in selected_service_types:
        prepared_launches["backend"] = PreparedServiceLaunch(
            service_name="backend",
            cwd=backend_cwd,
            log_path=backend_log_path,
            requested_port=backend_plan.final,
            env=command_env_builder(port=backend_plan.final, extra=backend_env_extra),
            command_source=backend_command_source,
        )
    if "frontend" in selected_service_types:
        launch_port = frontend_plan.final + rebound_delta if rebound_delta > 0 else frontend_plan.final
        prepared_launches["frontend"] = PreparedServiceLaunch(
            service_name="frontend",
            cwd=frontend_cwd,
            log_path=frontend_log_path,
            requested_port=frontend_plan.final,
            env=command_env_builder(port=launch_port, extra=frontend_env_extra),
            command_source=frontend_command_source,
        )

    def reserve_next(port: int) -> int:
        return port_allocator.reserve_next(port, owner=f"{context.name}:services")

    def start_process(
        command: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        log_path: Path | str,
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
        remaining = rt._conflict_remaining.get("backend", 0)
        if remaining > 0:
            rt._conflict_remaining["backend"] = remaining - 1
            rt._emit("service.start", project=context.name, service="backend", port=port, retry=True)
            return False, "bind: address already in use", None
        command_resolve_started = time.monotonic()
        command, _resolved_source = rt._service_start_command_resolved(
            service_name="backend",
            project_root=context.root,
            port=port,
        )
        rt._emit(
            "service.attach.phase",
            project=context.name,
            service="backend",
            phase="command_resolution",
            duration_ms=round((time.monotonic() - command_resolve_started) * 1000.0, 2),
        )
        launch_started = time.monotonic()
        process = start_process(
            command,
            cwd=str(prepared_launches["backend"].cwd),
            env=command_env_builder(port=port, extra=backend_env_extra),
            log_path=prepared_launches["backend"].log_path,
        )
        rt._emit(
            "service.attach.phase",
            project=context.name,
            service="backend",
            phase="process_launch",
            duration_ms=round((time.monotonic() - launch_started) * 1000.0, 2),
        )
        rt._emit("service.start", project=context.name, service="backend", port=port, retry=False)
        return True, None, getattr(process, "pid", os.getpid())

    def start_frontend(port: int) -> tuple[bool, str | None, int | None]:
        remaining = rt._conflict_remaining.get("frontend", 0)
        if remaining > 0:
            rt._conflict_remaining["frontend"] = remaining - 1
            rt._emit("service.start", project=context.name, service="frontend", port=port, retry=True)
            return False, "bind: address already in use", None
        launch_port = port + rebound_delta if rebound_delta > 0 else port
        if rebound_delta > 0:
            launch_port = port_allocator.reserve_next(
                launch_port,
                owner=f"{context.name}:services:frontend-launch",
            )
        command_resolve_started = time.monotonic()
        command, _resolved_source = rt._service_start_command_resolved(
            service_name="frontend",
            project_root=context.root,
            port=launch_port,
        )
        rt._emit(
            "service.attach.phase",
            project=context.name,
            service="frontend",
            phase="command_resolution",
            duration_ms=round((time.monotonic() - command_resolve_started) * 1000.0, 2),
        )
        launch_started = time.monotonic()
        process = start_process(
            command,
            cwd=str(prepared_launches["frontend"].cwd),
            env=command_env_builder(port=launch_port, extra=frontend_env_extra),
            log_path=prepared_launches["frontend"].log_path,
        )
        rt._emit(
            "service.attach.phase",
            project=context.name,
            service="frontend",
            phase="process_launch",
            duration_ms=round((time.monotonic() - launch_started) * 1000.0, 2),
        )
        rt._emit("service.start", project=context.name, service="frontend", port=port, retry=False)
        return True, None, getattr(process, "pid", os.getpid() + 1)

    backend_actual_override = parse_int(rt.env.get("ENVCTL_TEST_BACKEND_ACTUAL_PORT"), 0)
    frontend_actual_override = parse_int(rt.env.get("ENVCTL_TEST_FRONTEND_ACTUAL_PORT"), 0)

    def detect_backend_actual(pid: int | None, requested: int) -> int | None:
        if not backend_listener_expected:
            rt._emit(
                "service.bind.skipped",
                project=context.name,
                service="backend",
                reason="listener_not_expected",
            )
            return None
        rt._emit("service.bind.requested", project=context.name, service="backend", requested_port=requested)
        detect_started = time.monotonic()
        if backend_actual_override > 0:
            actual = backend_actual_override
        else:
            detected = rt._detect_service_actual_port(
                pid=pid,
                requested_port=requested,
                service_name="backend",
            )
            if detected is not None:
                actual = detected
                if actual != requested:
                    rt._emit("port.rebound", project=context.name, service="backend", port=actual)
            elif rt._listener_truth_enforced():
                detail = rt._service_listener_failure_detail(log_path=backend_log_path, pid=pid)
                error_suffix = f" ({detail})" if detail else ""
                rt._emit(
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
                rt._emit(
                    "service.failure",
                    project=context.name,
                    service="backend",
                    failure_class="listener_unverified",
                    requested_port=requested,
                )
                actual = requested
        rt._emit("service.bind.actual", project=context.name, service="backend", actual_port=actual)
        rt._emit(
            "service.attach.phase",
            project=context.name,
            service="backend",
            phase="actual_port_detection",
            duration_ms=round((time.monotonic() - detect_started) * 1000.0, 2),
        )
        return actual

    def detect_frontend_actual(pid: int | None, requested: int) -> int | None:
        rt._emit("service.bind.requested", project=context.name, service="frontend", requested_port=requested)
        detect_started = time.monotonic()
        if frontend_actual_override > 0:
            actual = frontend_actual_override
        else:
            probe_port = requested + rebound_delta if rebound_delta > 0 else requested
            detected = rt._detect_service_actual_port(
                pid=pid,
                requested_port=probe_port,
                service_name="frontend",
            )
            if detected is None and probe_port != requested:
                detected = rt._detect_service_actual_port(
                    pid=pid,
                    requested_port=requested,
                    service_name="frontend",
                )
            if detected is not None:
                actual = detected
                if actual != requested:
                    rt._emit("port.rebound", project=context.name, service="frontend", port=actual)
            elif rt._listener_truth_enforced():
                detail = rt._service_listener_failure_detail(log_path=frontend_log_path, pid=pid)
                error_suffix = f" ({detail})" if detail else ""
                rt._emit(
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
                rt._emit(
                    "service.failure",
                    project=context.name,
                    service="frontend",
                    failure_class="listener_unverified",
                    requested_port=requested,
                )
                actual = probe_port
        rt._emit("service.bind.actual", project=context.name, service="frontend", actual_port=actual)
        rt._emit(
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
        rt._emit(
            "service.retry",
            project=context.name,
            service=service_type,
            failed_port=failed_port,
            retry_port=retry_port,
            attempt=attempt,
            error=(error or "").strip() or None,
        )

    rt._emit(
        "service.attach.execution",
        project=context.name,
        mode="parallel" if attach_parallel else "sequential",
        selected_service_types=sorted(selected_service_types),
    )
    if requirements_timing_enabled(orchestrator, route) and not orchestrator._suppress_timing_output(route):
        print(
            "Service attach execution for "
            f"{context.name}: "
            f"{'parallel' if attach_parallel else 'sequential'} "
            f"(services={','.join(sorted(selected_service_types))})"
        )

    attach_started = time.monotonic()
    if selected_service_types == {"backend", "frontend"}:
        records = rt.services.start_project_with_attach(
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
            backend_listener_expected=backend_listener_expected,
            frontend_listener_expected=True,
            on_retry=on_service_retry,
            parallel_start=attach_parallel,
        )
    else:
        records: dict[str, ServiceRecord] = {}
        if "backend" in selected_service_types:
            backend = rt.services.start_service_with_retry(
                project=context.name,
                service_type="backend",
                cwd=str(backend_cwd),
                requested_port=backend_plan.final,
                start=start_backend,
                reserve_next=reserve_next,
                detect_actual=detect_backend_actual,
                listener_expected=backend_listener_expected,
                on_retry=on_service_retry,
            )
            records[backend.name] = backend
        if "frontend" in selected_service_types:
            frontend = rt.services.start_service_with_retry(
                project=context.name,
                service_type="frontend",
                cwd=str(frontend_cwd),
                requested_port=frontend_plan.final,
                start=start_frontend,
                reserve_next=reserve_next,
                detect_actual=detect_frontend_actual,
                listener_expected=True,
                on_retry=on_service_retry,
            )
            records[frontend.name] = frontend

    attach_duration_ms = round((time.monotonic() - attach_started) * 1000.0, 2)
    total_duration_ms = round((time.monotonic() - service_started) * 1000.0, 2)
    rt._emit(
        "service.timing.component",
        project=context.name,
        component="start_project_with_attach",
        duration_ms=attach_duration_ms,
    )
    rt._emit(
        "service.timing.summary",
        project=context.name,
        duration_ms=total_duration_ms,
        components={
            "prepare_backend_runtime": prepare_backend_duration_ms,
            "prepare_frontend_runtime": prepare_frontend_duration_ms,
            "start_project_with_attach": attach_duration_ms,
        },
    )
    if requirements_timing_enabled(orchestrator, route) and not orchestrator._suppress_timing_output(route):
        timing_parts: list[str] = []
        if "backend" in selected_service_types:
            timing_parts.append(f"prepare_backend_runtime={prepare_backend_duration_ms:.1f}ms")
        if "frontend" in selected_service_types:
            timing_parts.append(f"prepare_frontend_runtime={prepare_frontend_duration_ms:.1f}ms")
        timing_parts.append(f"start_project_with_attach={attach_duration_ms:.1f}ms")
        timing_parts.append(f"total={total_duration_ms:.1f}ms")
        print(f"Service timing for {context.name}: {' '.join(timing_parts)}")

    launched_runtimes: list[LaunchedServiceRuntime] = []
    backend_record = records.get(f"{context.name} Backend")
    frontend_record = records.get(f"{context.name} Frontend")
    if backend_record is not None:
        backend_record.log_path = backend_log_path
        backend_plan.final = backend_record.actual_port or backend_plan.final
        launched_runtimes.append(
            LaunchedServiceRuntime(
                service_name="backend",
                requested_port=backend_record.requested_port or backend_plan.final,
                actual_port=backend_record.actual_port or backend_plan.final,
                pid=backend_record.pid,
                log_path=backend_log_path,
            )
        )
    if frontend_record is not None:
        frontend_record.log_path = frontend_log_path
        frontend_plan.final = frontend_record.actual_port or frontend_plan.final
        launched_runtimes.append(
            LaunchedServiceRuntime(
                service_name="frontend",
                requested_port=frontend_record.requested_port or frontend_plan.final,
                actual_port=frontend_record.actual_port or frontend_plan.final,
                pid=frontend_record.pid,
                log_path=frontend_log_path,
            )
        )

    rt._emit(
        "service.attach",
        project=context.name,
        backend_port=backend_plan.final if "backend" in selected_service_types else None,
        frontend_port=frontend_plan.final if "frontend" in selected_service_types else None,
        service_group="full",
    )
    _ = backend_command_source, frontend_command_source, launched_runtimes
    return records
