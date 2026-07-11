from __future__ import annotations

import concurrent.futures
import time
from pathlib import Path
from typing import cast

from envctl_engine.runtime.command_resolution import CommandExists, suggest_service_start_command
from envctl_engine.runtime.docker_service_runtime import (
    docker_service_container_command_source,
    docker_service_mode_enabled,
)
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.runtime_context import resolve_process_runtime
from envctl_engine.startup.startup_selection_support import _restart_service_types_for_project
from envctl_engine.runtime.runtime_context import resolve_port_allocator
from envctl_engine.shared.parsing import parse_int
from envctl_engine.startup.service_attach_execution import ServiceAttachRunner
from envctl_engine.startup.service_execution_policy import (
    _project_backend_cors_origin,
    additional_service_enabled_for_context,
    apply_service_env_overlays,
    backend_listener_expected_for_mode,
    coerce_env_mapping,
    ordered_service_layers as ordered_service_layers,
    resolve_command_env_builder,
    resolve_project_service_env,
    resolve_service_env_overlay_builder,
    service_attach_parallel_enabled,
    service_prep_parallel_enabled,
)
from envctl_engine.startup.service_execution_environment import (
    configured_service_types_for_mode,
    make_service_dependency_emitter,
    make_service_retry_emitter,
    project_env_for_service as _project_env_for_service,
    project_service_log_path,
    project_service_log_paths,
    resolve_service_workdirs,
)
from envctl_engine.startup.service_execution_records import (
    LaunchedServiceRuntime as LaunchedServiceRuntime,
    PreparedServiceLaunch as PreparedServiceLaunch,
    finalize_launched_service_records,
)
from envctl_engine.startup.service_launch_diagnostics import record_runtime_launch_diagnostics
from envctl_engine.startup.protocols import ProjectContextLike, StartupOrchestratorLike
from envctl_engine.startup.public_urls import browser_backend_url, resolve_public_host
from envctl_engine.startup.requirements_execution import requirements_timing_enabled
from envctl_engine.state.models import RequirementsResult, ServiceRecord


NO_LOCAL_APP_SYSTEM_WARNING = (
    "No local app system is configured for this repo/worktree; envctl is continuing "
    "with the implementation session only. --entire-system was honored, but there was "
    "nothing configured to start."
)


def _mode_service_key(mode: str, service_name: str, suffix: str) -> str:
    return f"{mode.upper()}_{service_name.upper()}_{suffix}"


def _has_explicit_local_system_signal(
    config: object,
    *,
    env: dict[str, str] | object,
    mode: str,
    service_names: set[str],
) -> bool:
    explicit_keys = {str(key).strip().upper() for key in getattr(config, "explicit_keys", ())}
    if isinstance(env, dict):
        explicit_keys.update(str(key).strip().upper() for key in env)
    local_system_keys = {
        "ENVCTL_BACKEND_START_CMD",
        "ENVCTL_FRONTEND_START_CMD",
        "ENVCTL_ADDITIONAL_SERVICES",
        "BACKEND_DIR",
        "FRONTEND_DIR",
        f"{mode.upper()}_STARTUP_ENABLE",
    }
    for service_name in service_names:
        local_system_keys.add(_mode_service_key(mode, service_name, "ENABLE"))
    if explicit_keys.intersection(local_system_keys):
        return True
    if bool(getattr(config, "backend_dependency_env_section_present", False)):
        return True
    if bool(getattr(config, "frontend_dependency_env_section_present", False)):
        return True
    for service_name in service_names:
        if bool(getattr(config, f"{mode}_{service_name}_dependency_env_section_present", False)):
            return True
    service_sections = getattr(config, "service_dependency_env_section_present", None)
    if isinstance(service_sections, dict):
        for service_name in service_names:
            if bool(service_sections.get(service_name)):
                return True
    mode_service_sections = getattr(config, "mode_service_dependency_env_section_present", None)
    if isinstance(mode_service_sections, dict):
        for service_name in service_names:
            if bool(mode_service_sections.get((mode, service_name))):
                return True
    return False


def _selected_defaults_have_autodetectable_app(
    rt: object,
    *,
    project_root: Path,
    selected_service_types: set[str],
) -> bool:
    command_exists_candidate = getattr(rt, "_command_exists", None)
    command_exists: CommandExists
    if callable(command_exists_candidate):
        command_exists = cast(CommandExists, command_exists_candidate)
    else:
        def command_missing(_: str) -> bool:
            return False

        command_exists = command_missing

    for service_name in selected_service_types:
        if service_name not in {"backend", "frontend"}:
            continue
        if (
            suggest_service_start_command(
                service_name=service_name,
                project_root=project_root,
                command_exists=command_exists,
            )
            is not None
        ):
            return True
    return False


def _no_local_app_system_configured(
    rt: object,
    *,
    mode: str,
    project_root: Path,
    selected_service_types: set[str],
    configured_additional_services: tuple[object, ...],
) -> bool:
    if not selected_service_types:
        return False
    if not selected_service_types <= {"backend", "frontend"}:
        return False
    if configured_additional_services:
        return False
    if _has_explicit_local_system_signal(
        getattr(rt, "config"),
        env=getattr(rt, "env", {}),
        mode=mode,
        service_names=selected_service_types,
    ):
        return False
    return not _selected_defaults_have_autodetectable_app(
        rt,
        project_root=project_root,
        selected_service_types=selected_service_types,
    )


def start_project_services_impl(
    orchestrator: StartupOrchestratorLike,
    context: ProjectContextLike,
    *,
    requirements: RequirementsResult,
    run_id: str,
    route: Route | None = None,
) -> dict[str, ServiceRecord]:
    rt = orchestrator.runtime
    port_allocator = resolve_port_allocator(rt)
    process_runtime = resolve_process_runtime(rt)
    effective_mode = str(route.mode if route is not None else "main").strip().lower() or "main"
    backend_plan = context.ports["backend"]
    frontend_plan = context.ports["frontend"]
    backend_cwd, frontend_cwd = resolve_service_workdirs(config=rt.config, project_root=context.root)

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

    log_paths = project_service_log_paths(runtime=rt, run_id=run_id, project_name=context.name)
    run_logs_dir = log_paths.run_logs_dir
    backend_log_path = log_paths.backend_log_path
    frontend_log_path = log_paths.frontend_log_path
    project_env_internal = resolve_project_service_env(rt, context, requirements=requirements, route=route)

    def project_env_for_service(service_name: str) -> dict[str, str]:
        return _project_env_for_service(
            rt,
            context,
            requirements=requirements,
            route=route,
            service_name=service_name,
        )

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
    backend_env_extra = coerce_env_mapping(
        rt._service_env_from_file(
            base_env=backend_project_env_base,
            env_file=backend_env_file,
            include_app_env_file=True,
            env_file_authoritative=not backend_env_is_default,
        ),
        source="backend service env file",
    )
    frontend_env_extra = coerce_env_mapping(
        rt._service_env_from_file(
            base_env=frontend_project_env_base,
            env_file=frontend_env_file,
            include_app_env_file=False,
        ),
        source="frontend service env file",
    )
    backend_url = browser_backend_url(host=resolve_public_host(env=rt.env, config=rt.config), port=backend_plan.final)
    frontend_env_extra["VITE_BACKEND_URL"] = backend_url
    frontend_env_extra["VITE_API_URL"] = f"{backend_url}/api/v1"
    _project_backend_cors_origin(
        rt,
        project=context.name,
        backend_env=backend_env_extra,
        frontend_port=frontend_plan.final,
    )
    overlay_builder = resolve_service_env_overlay_builder(rt)
    apply_service_env_overlays(
        overlay_builder=overlay_builder,
        service_name="backend",
        target_env=backend_env_extra,
        base_env={**project_env_internal, **backend_env_extra},
    )
    apply_service_env_overlays(
        overlay_builder=overlay_builder,
        service_name="frontend",
        target_env=frontend_env_extra,
        base_env={**project_env_internal, **frontend_env_extra},
    )
    configured_service_types = configured_service_types_for_mode(rt, effective_mode, context.root)
    configured_additional_services = tuple(
        service
        for service in getattr(rt.config, "additional_services", ())
        if additional_service_enabled_for_context(service, mode=effective_mode, project_root=context.root)
    )

    if route is not None:
        route.flags.setdefault(
            "emit_service_dependency",
            make_service_dependency_emitter(orchestrator=orchestrator, runtime=rt, route=route),
        )
    backend_listener_expected = backend_listener_expected_for_mode(rt.config, effective_mode)
    selected_service_types = _restart_service_types_for_project(
        route=route,
        project_name=context.name,
        default_service_types=configured_service_types,
        additional_services=configured_additional_services,
    )
    if not selected_service_types:
        rt._emit(
            "service.attach.skipped",
            project=context.name,
            mode=effective_mode,
            reason="all_services_disabled",
        )
        return {}
    use_docker_services = bool(route is not None and route.flags.get("docker")) or docker_service_mode_enabled(rt)
    if (
        route is not None
        and route.command == "plan"
        and not use_docker_services
        and _no_local_app_system_configured(
            rt,
            mode=effective_mode,
            project_root=context.root,
            selected_service_types=selected_service_types,
            configured_additional_services=configured_additional_services,
        )
    ):
        rt._emit(
            "service.attach.skipped",
            project=context.name,
            mode=effective_mode,
            reason="no_system_configured",
            requested_scope=str(route.flags.get("runtime_scope")) if route is not None else None,
            selected_service_types=sorted(selected_service_types),
        )
        record_warning = getattr(rt, "_record_project_startup_warning", None)
        if callable(record_warning):
            record_warning(context.name, NO_LOCAL_APP_SYSTEM_WARNING)
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
        if use_docker_services:
            rt._emit("service.prepare.skipped", project=context.name, service="backend", reason="docker_image")
        else:
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
        if use_docker_services:
            rt._emit("service.prepare.skipped", project=context.name, service="frontend", reason="docker_image")
        else:
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
        backend_command_source = docker_service_container_command_source(
            rt,
            "backend",
            docker_mode=use_docker_services,
        )
        if backend_command_source is None:
            backend_command_source = rt._service_command_source(
                service_name="backend",
                project_root=context.root,
                port=backend_plan.final,
            )
    frontend_command_source = None
    if "frontend" in selected_service_types:
        frontend_command_source = docker_service_container_command_source(
            rt,
            "frontend",
            docker_mode=use_docker_services,
        )
        if frontend_command_source is None:
            frontend_command_source = rt._service_command_source(
                service_name="frontend",
                project_root=context.root,
                port=(frontend_plan.final + rebound_delta if rebound_delta > 0 else frontend_plan.final),
            )

    prepared_launches: dict[str, PreparedServiceLaunch] = {}
    command_env_builder = resolve_command_env_builder(rt)
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
    record_runtime_launch_diagnostics(
        route=route,
        runtime=rt,
        project_name=context.name,
        frontend_port=frontend_plan.final,
        backend_env=backend_env_extra,
        prepared_launches=prepared_launches,
        backend_command_source=backend_command_source,
        frontend_command_source=frontend_command_source,
    )
    additional_services = [
        service for service in configured_additional_services if service.name in selected_service_types
    ]
    for service in sorted(additional_services, key=lambda item: (item.start_order, item.name)):
        plan = context.ports.get(service.name)
        if plan is None and service.expect_listener:
            raise RuntimeError(f"No port plan available for additional service {service.name!r}")
        requested_port = int(getattr(plan, "final", 0) or 0) if plan is not None else 0
        service_cwd = (context.root / service.dir_name).resolve()
        if not service_cwd.is_relative_to(context.root.resolve()):
            raise RuntimeError(
                f"Configured service {service.name!r} directory escapes project root: {service.dir_name}"
            )
        if str(service.dir_name).strip() and not service_cwd.is_dir():
            raise RuntimeError(f"Configured service {service.name!r} directory does not exist: {service_cwd}")
        service_env_base = project_env_for_service(service.name)
        service_env_extra = dict(service_env_base)
        service_env_extra["ENVCTL_SERVICE_NAME"] = service.name
        service_env_extra["ENVCTL_SERVICE_TYPE"] = service.name
        service_env_extra["ENVCTL_PROJECT_NAME"] = context.name
        apply_service_env_overlays(
            overlay_builder=overlay_builder,
            service_name=service.name,
            target_env=service_env_extra,
            base_env=service_env_extra,
        )
        launch_port = requested_port if service.expect_listener else 0
        prepared_launches[service.name] = PreparedServiceLaunch(
            service_name=service.name,
            cwd=service_cwd,
            log_path=project_service_log_path(
                run_logs_dir=run_logs_dir,
                project_name=context.name,
                service_name=service.name,
            ),
            requested_port=launch_port,
            env=command_env_builder(port=launch_port, extra=service_env_extra),
            command_source="configured",
            listener_expected=service.expect_listener,
        )

    on_service_retry = make_service_retry_emitter(runtime=rt, project_name=context.name)

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
    records = ServiceAttachRunner(
        runtime=rt,
        process_runtime=process_runtime,
        port_allocator=port_allocator,
        project_name=context.name,
        project_root=context.root,
        backend_plan=backend_plan,
        frontend_plan=frontend_plan,
        backend_cwd=backend_cwd,
        frontend_cwd=frontend_cwd,
        backend_log_path=backend_log_path,
        frontend_log_path=frontend_log_path,
        backend_env_extra=backend_env_extra,
        frontend_env_extra=frontend_env_extra,
        command_env_builder=command_env_builder,
        prepared_launches=prepared_launches,
        selected_service_types=selected_service_types,
        additional_services=tuple(additional_services),
        backend_listener_expected=backend_listener_expected,
        rebound_delta=rebound_delta,
        docker_mode=use_docker_services,
        refresh_cache=bool(route is not None and route.flags.get("refresh_cache")),
    ).start(attach_parallel=attach_parallel, on_service_retry=on_service_retry)

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

    launched_runtimes = finalize_launched_service_records(
        context=context,
        records=records,
        backend_plan=backend_plan,
        frontend_plan=frontend_plan,
        additional_services=additional_services,
        prepared_launches=prepared_launches,
        backend_log_path=backend_log_path,
        frontend_log_path=frontend_log_path,
        project_env_for_service=project_env_for_service,
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
