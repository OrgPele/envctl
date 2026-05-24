from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path

from envctl_engine.requirements.common import ContainerStartResult
from envctl_engine.requirements.supabase_lifecycle.compose import (
    _compose_run,
    _compose_service_list,
    _compose_timeout_recovered,
    _compose_up_timeout_seconds,
    _is_compose_port_publish_stall,
    _resolve_service_name,
)
from envctl_engine.requirements.supabase_lifecycle.auth_flow import complete_supabase_auth_startup
from envctl_engine.requirements.supabase_lifecycle.config import (
    _db_probe_attempts,
    _db_probe_timeout_seconds,
    _db_recreate_on_probe_failure_enabled,
    _db_recreate_probe_attempts,
    _db_restart_on_probe_failure_enabled,
    _db_restart_probe_attempts,
    _native_db_start_enabled,
)
from envctl_engine.requirements.supabase_lifecycle.formatting import (
    _supabase_compose_failure_detail,
    _supabase_db_failure_detail,
    _supabase_local_auth_health_url,
)
from envctl_engine.requirements.supabase_lifecycle.gateway import (
    _format_gateway_port_mismatch,
    _gateway_public_port_mismatch,
    _recreate_db_service,
    _remove_auth_gateway_services,
)
from envctl_engine.requirements.supabase_lifecycle.inspect import _inspect_auth_gateway_services
from envctl_engine.requirements.supabase_lifecycle.native_db import _start_supabase_db_native
from envctl_engine.requirements.supabase_lifecycle.probe import (
    _is_compose_network_recovery_marker,
    _probe_db_listener,
    _record_compose_network_recovery_stage,
    _record_db_probe_stage,
)
from envctl_engine.requirements.supabase_lifecycle.types import _SupabaseStartupBudget
from envctl_engine.requirements.supabase_lifecycle.workspace import (
    _resolve_supabase_compose_workspace,
    build_supabase_project_name,
)
from envctl_engine.shared.protocols import ProcessRuntime


def start_supabase_stack(
    *,
    process_runner: ProcessRuntime,
    project_root: Path,
    project_name: str,
    db_port: int,
    public_port: int | None = None,
    runtime_root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> ContainerStartResult:
    startup_budget = _SupabaseStartupBudget.start(env, clock=getattr(process_runner, "monotonic", time.monotonic))
    stage_events: list[dict[str, object]] = []
    probe_attempts: list[dict[str, object]] = []
    compose_project_name = build_supabase_project_name(
        project_root=project_root,
        project_name=project_name,
    )
    resolved_public_port = int(
        public_port or (env or {}).get("SUPABASE_PUBLIC_PORT") or (env or {}).get("SUPABASE_API_PORT") or 54321
    )
    compose_root, compose_path = _resolve_supabase_compose_workspace(
        project_root=project_root,
        project_name=project_name,
        db_port=db_port,
        public_port=resolved_public_port,
        runtime_root=runtime_root,
        env=env,
    )
    if _native_db_start_enabled(env):
        return _start_supabase_db_native(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            project_root=project_root,
            db_port=db_port,
            env=env,
        )
    if not compose_path.is_file():
        return ContainerStartResult(
            success=False,
            container_name=compose_project_name,
            error=f"missing supabase compose file: {compose_path}",
        )

    available_services = _compose_service_list(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
    )
    db_service = _resolve_service_name(available_services, ("supabase-db", "db")) or "supabase-db"
    auth_service = _resolve_service_name(available_services, ("supabase-auth", "auth", "gotrue"))
    gateway_service = _resolve_service_name(available_services, ("supabase-kong", "kong", "gateway"))
    secondary_services = [
        service for service in (auth_service, gateway_service) if isinstance(service, str) and service
    ]
    graph_services = [db_service, *secondary_services]
    compose_up_timeout = _compose_up_timeout_seconds(env, service_names=graph_services)

    db_handoff_recovered = False
    if gateway_service and secondary_services:
        gateway_port_mismatch = _gateway_public_port_mismatch(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            gateway_service=gateway_service,
            expected_port=resolved_public_port,
            include_created=True,
        )
        if gateway_port_mismatch is not None:
            stage_events.append(
                {
                    "stage": "supabase.gateway.port_mismatch.preflight",
                    "reason": "remove_stale",
                    "detail": _format_gateway_port_mismatch(gateway_port_mismatch, expected_port=resolved_public_port),
                    "startup_budget_s": startup_budget.timeout_seconds,
                    "elapsed_ms": startup_budget.elapsed_ms(),
                }
            )
            remove_error = _remove_auth_gateway_services(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
                service_names=secondary_services,
            )
            if remove_error is not None:
                detail = remove_error.strip()
                return ContainerStartResult(
                    success=False,
                    container_name=compose_project_name,
                    error=(
                        f"failed removing stale Supabase Auth/Kong before startup: {detail}"
                        if detail
                        else "failed removing stale Supabase Auth/Kong before startup"
                    ),
                    stage_events=stage_events,
                )

    graph_event = {
        "stage": "supabase.graph.up" if secondary_services else "supabase.db.up",
        "detail": ",".join(graph_services),
        "timeout_s": compose_up_timeout,
        "startup_budget_s": startup_budget.timeout_seconds,
    }
    stage_events.append(graph_event)
    up_db = _compose_run(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=["up", "-d", *graph_services],
    )
    graph_event["elapsed_ms"] = startup_budget.elapsed_ms()
    if up_db is not None:
        if _is_compose_network_recovery_marker(up_db):
            _record_compose_network_recovery_stage(stage_events, up_db)
            db_handoff_recovered = True
        else:
            db_handoff_recovered = _compose_timeout_recovered(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
                service_name=db_service,
                probe_port=db_port,
                error=up_db,
            )
        if not db_handoff_recovered:
            service_states = []
            if not _is_compose_port_publish_stall(up_db):
                service_states = _inspect_auth_gateway_services(
                    process_runner=process_runner,
                    compose_root=compose_root,
                    compose_project_name=compose_project_name,
                    compose_path=compose_path,
                    env=env,
                    service_names=graph_services,
                )
            return ContainerStartResult(
                success=False,
                container_name=compose_project_name,
                error=_supabase_compose_failure_detail(
                    phase="compose_graph" if secondary_services else "compose_db",
                    error=up_db,
                    services=graph_services,
                    service_states=service_states,
                    compose_timeout_seconds=compose_up_timeout,
                    startup_budget=startup_budget,
                    public_port=resolved_public_port,
                    health_url=_supabase_local_auth_health_url(resolved_public_port),
                ),
                stage_events=stage_events,
            )

    if db_port > 0:
        db_probe_attempts = _db_probe_attempts(env)
        db_probe_timeout = _db_probe_timeout_seconds(env)
        db_ready = False
        db_initial_attempts_used = 0
        for attempt in range(db_probe_attempts):
            db_initial_attempts_used = attempt + 1
            if bool(process_runner.wait_for_port(db_port, timeout=db_probe_timeout)):
                db_ready = True
                break
            if attempt < db_probe_attempts - 1 and not db_handoff_recovered:
                retry_up_db = _compose_run(
                    process_runner=process_runner,
                    compose_root=compose_root,
                    compose_project_name=compose_project_name,
                    compose_path=compose_path,
                    env=env,
                    args=["up", "-d", db_service],
                )
                if retry_up_db is not None:
                    if _is_compose_network_recovery_marker(retry_up_db):
                        _record_compose_network_recovery_stage(stage_events, retry_up_db)
                        db_handoff_recovered = True
                    else:
                        db_handoff_recovered = _compose_timeout_recovered(
                            process_runner=process_runner,
                            compose_root=compose_root,
                            compose_project_name=compose_project_name,
                            compose_path=compose_path,
                            env=env,
                            service_name=db_service,
                            probe_port=db_port,
                            error=retry_up_db,
                        )
                    if not db_handoff_recovered:
                        return ContainerStartResult(
                            success=False,
                            container_name=compose_project_name,
                            error=f"{retry_up_db} (retry db bring-up failed)",
                            stage_events=stage_events,
                        )

        _record_db_probe_stage(
            stage_events,
            db_port=db_port,
            attempts=db_initial_attempts_used,
            action="initial",
            ready=db_ready,
            timeout_seconds=db_probe_timeout,
            startup_budget=startup_budget,
        )

        if not db_ready and _db_restart_on_probe_failure_enabled(env):
            restart_error = _compose_run(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
                args=["restart", db_service],
            )
            if restart_error is not None:
                return ContainerStartResult(
                    success=False,
                    container_name=compose_project_name,
                    error=(
                        f"failed restarting supabase db service: {restart_error}"
                        if restart_error.strip()
                        else "failed restarting supabase db service"
                    ),
                    stage_events=stage_events,
                )
            restart_probe_attempts = _db_restart_probe_attempts(env, default=db_probe_attempts)
            db_ready = _probe_db_listener(
                process_runner=process_runner,
                db_port=db_port,
                timeout_seconds=db_probe_timeout,
                attempts=restart_probe_attempts,
            )
            _record_db_probe_stage(
                stage_events,
                db_port=db_port,
                attempts=restart_probe_attempts,
                action="restart",
                ready=db_ready,
                timeout_seconds=db_probe_timeout,
                startup_budget=startup_budget,
            )

            if not db_ready and _db_recreate_on_probe_failure_enabled(env):
                recreate_error = _recreate_db_service(
                    process_runner=process_runner,
                    compose_root=compose_root,
                    compose_project_name=compose_project_name,
                    compose_path=compose_path,
                    env=env,
                    db_service=db_service,
                )
                if recreate_error is not None:
                    return ContainerStartResult(
                        success=False,
                        container_name=compose_project_name,
                        error=(
                            f"failed recreating supabase db service: {recreate_error}"
                            if recreate_error.strip()
                            else "failed recreating supabase db service"
                        ),
                        stage_events=stage_events,
                    )
                recreate_probe_attempts = _db_recreate_probe_attempts(env, default=restart_probe_attempts)
                db_ready = _probe_db_listener(
                    process_runner=process_runner,
                    db_port=db_port,
                    timeout_seconds=db_probe_timeout,
                    attempts=recreate_probe_attempts,
                )
                _record_db_probe_stage(
                    stage_events,
                    db_port=db_port,
                    attempts=recreate_probe_attempts,
                    action="recreate",
                    ready=db_ready,
                    timeout_seconds=db_probe_timeout,
                    startup_budget=startup_budget,
                )
                if not db_ready:
                    service_states = _inspect_auth_gateway_services(
                        process_runner=process_runner,
                        compose_root=compose_root,
                        compose_project_name=compose_project_name,
                        compose_path=compose_path,
                        env=env,
                        service_names=graph_services,
                    )
                    return ContainerStartResult(
                        success=False,
                        container_name=compose_project_name,
                        error=_supabase_db_failure_detail(
                            db_port=db_port,
                            timeout_seconds=db_probe_timeout,
                            attempts=recreate_probe_attempts,
                            startup_budget=startup_budget,
                            service_states=service_states,
                            last_error=f"probe timeout waiting for readiness on port {db_port} after recreate",
                        ),
                        stage_events=stage_events,
                    )

            if not db_ready:
                service_states = _inspect_auth_gateway_services(
                    process_runner=process_runner,
                    compose_root=compose_root,
                    compose_project_name=compose_project_name,
                    compose_path=compose_path,
                    env=env,
                    service_names=graph_services,
                )
                return ContainerStartResult(
                    success=False,
                    container_name=compose_project_name,
                    error=_supabase_db_failure_detail(
                        db_port=db_port,
                        timeout_seconds=db_probe_timeout,
                        attempts=restart_probe_attempts,
                        startup_budget=startup_budget,
                        service_states=service_states,
                        last_error=f"probe timeout waiting for readiness on port {db_port} after restart",
                    ),
                    stage_events=stage_events,
                )

        if not db_ready:
            suffix = " after retry" if db_probe_attempts > 1 else ""
            service_states = _inspect_auth_gateway_services(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
                service_names=graph_services,
            )
            last_error = f"probe timeout waiting for readiness on port {db_port}{suffix}"
            return ContainerStartResult(
                success=False,
                container_name=compose_project_name,
                error=_supabase_db_failure_detail(
                    db_port=db_port,
                    timeout_seconds=db_probe_timeout,
                    attempts=db_initial_attempts_used,
                    startup_budget=startup_budget,
                    service_states=service_states,
                    last_error=last_error,
                ),
                stage_events=stage_events,
            )

    return complete_supabase_auth_startup(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        secondary_services=secondary_services,
        gateway_service=gateway_service,
        resolved_public_port=resolved_public_port,
        startup_budget=startup_budget,
        stage_events=stage_events,
        probe_attempts=probe_attempts,
    )
