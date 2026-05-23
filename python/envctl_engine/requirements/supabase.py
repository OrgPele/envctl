from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import sys
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from collections.abc import Mapping

from envctl_engine.debug.debug_utils import file_lock
from envctl_engine.shared.protocols import ProcessRuntime

from .adapter_base import env_bool, env_float, env_int, port_mismatch_policy, timeout_error
from .common import (
    ContainerStartResult,
    RetryResult,
    build_container_name,
    container_exists,
    container_host_port,
    container_status,
    docker_port_publish_lock,
    ensure_docker_image_present,
    is_bind_conflict,
    run_docker,
    run_result_error,
    run_with_retry,
)
from ..shared.dependency_compose_assets import (
    DEFAULT_SUPABASE_JWT_SECRET,
    default_supabase_anon_key,
    default_supabase_service_role_key,
    dependency_compose_asset_dir,
    materialize_dependency_compose,
    supabase_managed_env,
)


def start_supabase_with_retry(
    start,
    reserve_next,
    port: int,
    max_retries: int = 3,  # noqa: ANN001
) -> RetryResult:
    return run_with_retry(initial_port=port, start=start, reserve_next=reserve_next, max_retries=max_retries)


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

    public_health_url = _supabase_auth_health_url(env, resolved_public_port)
    health_url = _supabase_local_auth_health_url(resolved_public_port)
    actions_attempted: list[str] = ["initial_probe"]
    container_recreated = False
    if gateway_service:
        gateway_port_mismatch = _gateway_public_port_mismatch(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            gateway_service=gateway_service,
            expected_port=resolved_public_port,
        )
        if gateway_port_mismatch is not None:
            stage_events.append(
                {
                    "stage": "supabase.gateway.port_mismatch",
                    "reason": "recreate",
                    "detail": _format_gateway_port_mismatch(gateway_port_mismatch, expected_port=resolved_public_port),
                    "startup_budget_s": startup_budget.timeout_seconds,
                    "elapsed_ms": startup_budget.elapsed_ms(),
                }
            )
            recreate_error = _recreate_auth_gateway_services(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
                service_names=secondary_services,
            )
            if recreate_error is not None:
                detail = recreate_error.strip()
                return ContainerStartResult(
                    success=False,
                    container_name=compose_project_name,
                    error=(
                        f"failed recreating Supabase Auth/Kong after gateway port mismatch: {detail}"
                        if detail
                        else "failed recreating Supabase Auth/Kong after gateway port mismatch"
                    ),
                    stage_events=stage_events,
                    probe_attempts=probe_attempts,
                    probe_attempt_count=len(probe_attempts),
                )
            container_recreated = True
            gateway_port_mismatch = _gateway_public_port_mismatch(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
                gateway_service=gateway_service,
                expected_port=resolved_public_port,
            )
            if gateway_port_mismatch is not None:
                return ContainerStartResult(
                    success=False,
                    container_name=compose_project_name,
                    error=(
                        "Supabase gateway published port mismatch after recreate: "
                        + _format_gateway_port_mismatch(gateway_port_mismatch, expected_port=resolved_public_port)
                    ),
                    stage_events=stage_events,
                    probe_attempts=probe_attempts,
                    probe_attempt_count=len(probe_attempts),
                    container_recreated=container_recreated,
                )
    stage_events.append(
        {
            "stage": "supabase.auth.probe",
            "detail": health_url,
            "startup_budget_s": startup_budget.timeout_seconds,
            "elapsed_ms": startup_budget.elapsed_ms(),
        }
    )
    auth_probe = _probe_supabase_auth_health_with_attempts(
        process_runner=process_runner,
        public_port=resolved_public_port,
        health_url=health_url,
        env=env,
        attempts=1,
        action="initial_probe",
    )
    probe_attempts.extend(auth_probe.attempts)

    service_state_summaries: list[dict[str, object]] = []

    def record_auth_service_state(reason: str) -> None:
        nonlocal service_state_summaries
        service_state_summaries = _inspect_auth_gateway_services(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            service_names=secondary_services,
        )
        for service_state in service_state_summaries:
            stage_events.append(
                {
                    "stage": "supabase.auth.inspect",
                    "reason": reason,
                    "detail": _format_auth_service_state(service_state),
                }
            )

    if not auth_probe.ready and secondary_services:
        record_auth_service_state("initial_probe_failed")
        if _auth_services_progressing(service_state_summaries) and startup_budget.remaining_seconds() > 0:
            stage_events.append(
                {
                    "stage": "supabase.auth.wait_progress",
                    "reason": "progressing",
                    "detail": _format_auth_service_states(service_state_summaries),
                    "startup_budget_s": startup_budget.timeout_seconds,
                    "elapsed_ms": startup_budget.elapsed_ms(),
                }
            )
            auth_probe = _wait_for_auth_health_while_progressing(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
                secondary_services=secondary_services,
                public_port=resolved_public_port,
                health_url=health_url,
                startup_budget=startup_budget,
                stage_events=stage_events,
            )
            probe_attempts.extend(auth_probe.attempts)
            if not auth_probe.ready:
                record_auth_service_state("progress_wait_failed")

    if not auth_probe.ready and secondary_services and _auth_restart_on_probe_failure_enabled(env):
        actions_attempted.append("restart")
        stage_events.append({"stage": "supabase.auth.restart", "detail": ",".join(secondary_services)})
        restart_error = _compose_run(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            args=["restart", *secondary_services],
        )
        if restart_error is not None:
            detail = restart_error.strip()
            return ContainerStartResult(
                success=False,
                container_name=compose_project_name,
                error=(
                    f"failed restarting supabase auth/kong services: {detail}"
                    if detail
                    else "failed restarting supabase auth/kong services"
                ),
                stage_events=stage_events,
                probe_attempts=probe_attempts,
                probe_attempt_count=len(probe_attempts),
            )
        auth_probe = _probe_supabase_auth_health_with_attempts(
            process_runner=process_runner,
            public_port=resolved_public_port,
            health_url=health_url,
            env=env,
            attempts=_auth_restart_probe_attempts(env),
            action="restart",
        )
        probe_attempts.extend(auth_probe.attempts)
        if not auth_probe.ready:
            record_auth_service_state("restart_probe_failed")

    if not auth_probe.ready and secondary_services and _auth_recreate_on_probe_failure_enabled(env):
        actions_attempted.append("recreate")
        stage_events.append({"stage": "supabase.auth.recreate", "detail": ",".join(secondary_services)})
        recreate_error = _recreate_auth_gateway_services(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            service_names=secondary_services,
        )
        if recreate_error is not None:
            detail = recreate_error.strip()
            return ContainerStartResult(
                success=False,
                container_name=compose_project_name,
                error=(
                    f"failed recreating supabase auth/kong services: {detail}"
                    if detail
                    else "failed recreating supabase auth/kong services"
                ),
                stage_events=stage_events,
                probe_attempts=probe_attempts,
                probe_attempt_count=len(probe_attempts),
            )
        container_recreated = True
        auth_probe = _probe_supabase_auth_health_with_attempts(
            process_runner=process_runner,
            public_port=resolved_public_port,
            health_url=health_url,
            env=env,
            attempts=_auth_recreate_probe_attempts(env),
            action="recreate",
        )
        probe_attempts.extend(auth_probe.attempts)
        if not auth_probe.ready:
            record_auth_service_state("recreate_probe_failed")

    if not auth_probe.ready:
        stage_events.append(
            {
                "stage": "supabase.auth.probe.final",
                "reason": "failed",
                "detail": auth_probe.last_error,
                "startup_budget_s": startup_budget.timeout_seconds,
                "elapsed_ms": startup_budget.elapsed_ms(),
            }
        )
        detail = _supabase_auth_failure_detail(
            probe=auth_probe,
            actions=actions_attempted,
            service_names=secondary_services,
            public_port=resolved_public_port,
            public_health_url=public_health_url,
            service_states=service_state_summaries,
            startup_budget=startup_budget,
            auth_probe_timeout_seconds=_auth_probe_timeout_seconds(env),
            probe_attempt_count=len(probe_attempts),
        )
        return ContainerStartResult(
            success=False,
            container_name=compose_project_name,
            error=f"Supabase DB is healthy but Supabase Auth/Kong is not reachable at {health_url}: {detail}",
            stage_events=stage_events,
            probe_attempts=probe_attempts,
            probe_attempt_count=len(probe_attempts),
            container_recreated=container_recreated,
        )

    stage_events.append(
        {
            "stage": "supabase.auth.probe.final",
            "reason": "ready",
            "detail": health_url,
            "startup_budget_s": startup_budget.timeout_seconds,
            "elapsed_ms": startup_budget.elapsed_ms(),
        }
    )
    return ContainerStartResult(
        success=True,
        container_name=compose_project_name,
        stage_events=stage_events,
        probe_attempts=probe_attempts,
        probe_attempt_count=len(probe_attempts),
        container_recreated=container_recreated,
    )


# Re-export network recovery symbols for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.network_recovery import (
    _recover_missing_supabase_network_for_project,
    _remove_empty_docker_networks,
)

# Re-export config symbols for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.config import (
    _auth_probe_timeout_seconds,
    _auth_restart_probe_attempts,
    _auth_recreate_probe_attempts,
    _auth_restart_on_probe_failure_enabled,
    _auth_recreate_on_probe_failure_enabled,
    _db_probe_attempts,
    _db_probe_timeout_seconds,
    _db_restart_probe_attempts,
    _db_recreate_probe_attempts,
    _db_restart_on_probe_failure_enabled,
    _db_recreate_on_probe_failure_enabled,
    _native_db_start_enabled,
)

# Re-export native DB symbols for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.native_db import (
    _start_supabase_db_native,
    _recover_native_db_start_timeout,
    _recover_native_db_create_timeout,
    _native_db_start_timeout_seconds,
    _native_db_start_recovery_timeout_seconds,
    _native_db_state_error,
    _native_db_published_port,
    _native_db_timeout_error_for_retry,
    _force_remove_native_db_container,
)

# Re-export formatting helpers for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.formatting import (
    _format_auth_service_state,
    _format_auth_service_states,
    _sanitize_service_state_text,
    _is_python_traceback_noise,
    _supabase_auth_failure_detail,
    _supabase_compose_failure_detail,
    _supabase_db_failure_detail,
    _supabase_auth_health_url,
    _supabase_local_auth_health_url,
)

# Re-export inspect helpers for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.inspect import (
    _inspect_auth_gateway_services,
    _inspect_auth_gateway_service,
    _inspect_compose_service_from_container_name,
    _compose_container_name,
    _populate_service_summary_from_state,
    _inspect_compose_service_from_ps_json,
    _parse_compose_ps_status,
)

# Re-export types for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.types import (
    _SupabaseStartupBudget,
    SupabaseAuthHealthProbeResult,
)

# Re-export compose lifecycle symbols for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.compose import (
    _compose_service_list,
    _resolve_service_name,
    _compose_run,
    _compose_args_mutate_port_bindings,
    _compose_run_locked,
    _compose_project_lock_path,
    _compose_lock_timeout_seconds,
    _compose_up_timeout_seconds,
    _compose_up_handoff,
    _compose_port_publish_stall_seconds,
    _compose_unpublished_port_detail,
    _compose_stalled_port_detail,
    _published_container_port_for_service,
    _expected_host_port_for_service,
    _is_gateway_service_name,
    _is_compose_port_publish_stall,
    _compose_services_started,
    _compose_handoff_ready,
    _compose_service_state_ready,
    _terminate_compose_process,
    _compose_db_port,
    _compose_public_port,
    _compose_timeout_recovered,
)

# Re-export gateway symbols for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.gateway import (
    _recreate_db_service,
    _gateway_public_port_mismatch,
    _container_host_config_port,
    _format_gateway_port_mismatch,
    _recreate_auth_gateway_services,
    _remove_auth_gateway_services,
)

# Re-export workspace symbols for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.workspace import (
    _normalize_compose_error,
    _is_container_name_conflict,
    _extract_conflicting_container_name,
    _resolve_supabase_compose_workspace,
    build_supabase_project_name,
)

# Re-export probe symbols for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.probe import (
    _compose_service_state_failed,
    _auth_services_progressing,
    _wait_for_auth_health_while_progressing,
    _env_with_float_override,
    _probe_db_listener,
    _record_db_probe_stage,
    _record_compose_network_recovery_stage,
    _is_compose_network_recovery_marker,
    _probe_supabase_auth_health,
    _probe_supabase_auth_health_with_attempts,
    _probe_supabase_auth_health_once,
    _condense_probe_error,
)

# Re-export reliability contract symbols for backwards compatibility
from envctl_engine.requirements.supabase_lifecycle.reliability_contract import (
    SupabaseReliabilityContract,
    evaluate_supabase_reliability_contract,
    evaluate_managed_supabase_reliability_contract,
    read_fingerprint,
    write_fingerprint,
)
