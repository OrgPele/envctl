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

from envctl_engine.shared.protocols import ProcessRuntime

from .adapter_base import env_bool, env_float, env_int, port_mismatch_policy, timeout_error
from .common import (
    ContainerStartResult,
    RetryResult,
    build_container_name,
    container_exists,
    container_host_port,
    container_status,
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


@dataclass(slots=True)
class SupabaseServices:
    db: str
    auth: str | None
    gateway: str | None

    @property
    def secondary_services(self) -> list[str]:
        return [service for service in (self.auth, self.gateway) if isinstance(service, str) and service]

    @property
    def all_compose_services(self) -> list[str]:
        return [self.db, *self.secondary_services]


@dataclass(slots=True)
class SupabaseComposeContext:
    compose_root: Path
    compose_path: Path
    compose_project_name: str
    env: Mapping[str, str] | None
    resolved_public_port: int
    services: SupabaseServices


@dataclass(slots=True)
class SupabaseStartupOptions:
    db_probe_attempts: int
    db_probe_timeout_seconds: float
    auth_restart_probe_attempts: int
    auth_recreate_probe_attempts: int
    db_restart_on_probe_failure: bool
    db_recreate_on_probe_failure: bool
    auth_restart_on_probe_failure: bool
    auth_recreate_on_probe_failure: bool


@dataclass(slots=True)
class SupabaseStartupState:
    stage_events: list[dict[str, object]]
    probe_attempts: list[dict[str, object]]
    container_recreated: bool = False
    service_state_summaries: list[dict[str, object]] | None = None

    def record_stage(self, stage: str, *, reason: str | None = None, detail: object | None = None, **fields) -> None:
        event: dict[str, object] = {"stage": stage}
        if reason is not None:
            event["reason"] = reason
        if detail is not None:
            event["detail"] = detail
        event.update({key: value for key, value in fields.items() if value is not None})
        self.stage_events.append(event)

    def extend_probe_attempts(self, probe: "SupabaseAuthHealthProbeResult") -> None:
        self.probe_attempts.extend(probe.attempts)


@dataclass(slots=True)
class SupabasePhaseResult:
    ok: bool
    error: str | None = None
    failure_phase: str | None = None


@dataclass(slots=True)
class ComposeServiceState:
    service: str
    container_id: str | None = None
    status: str | None = None
    health: str | None = None
    exit_code: str | None = None
    state_error: str | None = None
    error: str | None = None
    published_ports: list[str] | None = None

    @property
    def exists(self) -> bool:
        return bool(self.container_id)

    @property
    def is_running(self) -> bool:
        return str(self.status or "").lower() == "running"

    @property
    def is_healthy(self) -> bool:
        if self.health is None:
            return self.is_running
        return str(self.health).lower() == "healthy"

    @property
    def is_created(self) -> bool:
        return str(self.status or "").lower() == "created"

    @property
    def is_terminal_failure(self) -> bool:
        status = str(self.status or "").lower()
        if status in {"exited", "dead", "removing"}:
            return True
        if self.exit_code not in (None, "", "0"):
            return status in {"exited", "dead"} or not self.is_running
        return False

    def to_summary(self) -> dict[str, object]:
        summary: dict[str, object] = {"service": self.service}
        if self.container_id:
            summary["container"] = self.container_id
        if self.status:
            summary["status"] = self.status
        if self.health:
            summary["health"] = self.health
        if self.exit_code not in (None, ""):
            summary["exit_code"] = str(self.exit_code)
        if self.state_error:
            summary["state_error"] = _sanitize_service_state_text(self.state_error)
        if self.error:
            summary["inspect_error"] = _sanitize_service_state_text(self.error)
        if self.published_ports:
            summary["published_ports"] = ",".join(self.published_ports)
        return summary


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
    context = _resolve_supabase_compose_context(
        process_runner=process_runner,
        project_root=project_root,
        project_name=project_name,
        db_port=db_port,
        public_port=public_port,
        runtime_root=runtime_root,
        env=env,
    )
    if _native_db_start_enabled(env):
        return _start_supabase_db_native(
            process_runner=process_runner,
            compose_root=context.compose_root,
            compose_project_name=context.compose_project_name,
            project_root=project_root,
            db_port=db_port,
            env=env,
        )
    if not context.compose_path.is_file():
        return ContainerStartResult(
            success=False,
            container_name=context.compose_project_name,
            error=f"missing supabase compose file: {context.compose_path}",
        )
    return _start_supabase_managed_compose_stack(
        process_runner=process_runner,
        context=context,
        db_port=db_port,
    )


def _start_supabase_managed_compose_stack(
    *,
    process_runner: ProcessRuntime,
    context: SupabaseComposeContext,
    db_port: int,
) -> ContainerStartResult:
    state = SupabaseStartupState(stage_events=[], probe_attempts=[])
    stage_events = state.stage_events
    probe_attempts = state.probe_attempts
    compose_root = context.compose_root
    compose_path = context.compose_path
    compose_project_name = context.compose_project_name
    env = context.env
    resolved_public_port = context.resolved_public_port
    db_service = context.services.db
    secondary_services = context.services.secondary_services

    db_handoff_recovered = False
    state.record_stage("supabase.db.up")
    up_db = _compose_run(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=["up", "-d", db_service],
    )
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
            return ContainerStartResult(
                success=False,
                container_name=compose_project_name,
                error=up_db,
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
                )
                if not db_ready:
                    return ContainerStartResult(
                        success=False,
                        container_name=compose_project_name,
                        error=f"probe timeout waiting for readiness on port {db_port} after recreate",
                        stage_events=stage_events,
                    )

            if not db_ready:
                return ContainerStartResult(
                    success=False,
                    container_name=compose_project_name,
                    error=f"probe timeout waiting for readiness on port {db_port} after restart",
                    stage_events=stage_events,
                )

        if not db_ready:
            suffix = " after retry" if db_probe_attempts > 1 else ""
            return ContainerStartResult(
                success=False,
                container_name=compose_project_name,
                error=f"probe timeout waiting for readiness on port {db_port}{suffix}",
                stage_events=stage_events,
            )

    if secondary_services:
        state.record_stage("supabase.secondary.up", detail=",".join(secondary_services))
        up_secondary = _compose_run(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            args=["up", "-d", *secondary_services],
        )
        if up_secondary is not None:
            if _is_compose_network_recovery_marker(up_secondary):
                _record_compose_network_recovery_stage(stage_events, up_secondary)
                up_secondary = None
        if up_secondary is not None:
            if not all(
                _compose_timeout_recovered(
                    process_runner=process_runner,
                    compose_root=compose_root,
                    compose_project_name=compose_project_name,
                    compose_path=compose_path,
                    env=env,
                    service_name=service_name,
                    probe_port=None,
                    error=up_secondary,
                )
                for service_name in secondary_services
            ):
                return ContainerStartResult(
                    success=False,
                    container_name=compose_project_name,
                    error=up_secondary,
                    stage_events=stage_events,
                )

    public_health_url = _supabase_auth_health_url(env, resolved_public_port)
    health_url = _supabase_local_auth_health_url(resolved_public_port)
    actions_attempted: list[str] = ["initial_probe"]
    state.record_stage("supabase.auth.probe", detail=health_url)
    auth_probe = _probe_supabase_auth_health_with_attempts(
        process_runner=process_runner,
        public_port=resolved_public_port,
        health_url=health_url,
        env=env,
        attempts=1,
        action="initial_probe",
    )
    state.extend_probe_attempts(auth_probe)

    state.service_state_summaries = []

    def record_auth_service_state(reason: str) -> None:
        state.service_state_summaries = _inspect_auth_gateway_services(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            service_names=secondary_services,
        )
        for service_state in state.service_state_summaries:
            state.record_stage("supabase.auth.inspect", reason=reason, detail=_format_auth_service_state(service_state))

    if not auth_probe.ready and secondary_services:
        record_auth_service_state("initial_probe_failed")

    if not auth_probe.ready and secondary_services and _auth_restart_on_probe_failure_enabled(env):
        actions_attempted.append("restart")
        state.record_stage("supabase.auth.restart", detail=",".join(secondary_services))
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
        state.extend_probe_attempts(auth_probe)
        if not auth_probe.ready:
            record_auth_service_state("restart_probe_failed")

    if not auth_probe.ready and secondary_services and _auth_recreate_on_probe_failure_enabled(env):
        actions_attempted.append("recreate")
        state.record_stage("supabase.auth.recreate", detail=",".join(secondary_services))
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
        state.container_recreated = True
        auth_probe = _probe_supabase_auth_health_with_attempts(
            process_runner=process_runner,
            public_port=resolved_public_port,
            health_url=health_url,
            env=env,
            attempts=_auth_recreate_probe_attempts(env),
            action="recreate",
        )
        state.extend_probe_attempts(auth_probe)
        if not auth_probe.ready:
            record_auth_service_state("recreate_probe_failed")

    if not auth_probe.ready:
        state.record_stage("supabase.auth.probe.final", reason="failed", detail=auth_probe.last_error)
        detail = _supabase_auth_failure_detail(
            probe=auth_probe,
            actions=actions_attempted,
            service_names=secondary_services,
            public_port=resolved_public_port,
            public_health_url=public_health_url,
            service_states=state.service_state_summaries,
        )
        return ContainerStartResult(
            success=False,
            container_name=compose_project_name,
            error=f"Supabase DB is healthy but Supabase Auth/Kong is not reachable at {health_url}: {detail}",
            stage_events=stage_events,
            probe_attempts=probe_attempts,
            probe_attempt_count=len(probe_attempts),
            container_recreated=state.container_recreated,
        )

    state.record_stage("supabase.auth.probe.final", reason="ready", detail=health_url)
    return ContainerStartResult(
        success=True,
        container_name=compose_project_name,
        stage_events=stage_events,
        probe_attempts=probe_attempts,
        probe_attempt_count=len(probe_attempts),
        container_recreated=state.container_recreated,
    )


def _start_supabase_db_native(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    project_root: Path,
    db_port: int,
    env: Mapping[str, str] | None,
) -> ContainerStartResult:
    container_name = f"{compose_project_name}-supabase-db-1"
    create_timeout_seconds = env_float(
        env,
        "ENVCTL_SUPABASE_DB_CREATE_TIMEOUT_SECONDS",
        25.0,
        minimum=5.0,
    )
    start_timeout_seconds = _native_db_start_timeout_seconds(env)
    listener_wait_timeout = _db_probe_timeout_seconds(env)
    volume_name = f"{compose_project_name}_supabase_db_data"
    image = (env or {}).get("SUPABASE_DB_IMAGE") or "supabase/postgres:15.1.0.147"

    existing, existing_error = container_exists(
        process_runner,
        container_name=container_name,
        cwd=project_root,
        env=env,
    )
    if existing_error:
        return ContainerStartResult(success=False, container_name=container_name, error=existing_error)

    if existing:
        mapped_port, port_error = container_host_port(
            process_runner,
            container_name=container_name,
            container_port=5432,
            cwd=project_root,
            env=env,
        )
        if port_error:
            return ContainerStartResult(success=False, container_name=container_name, error=port_error)
        status, status_error = container_status(
            process_runner,
            container_name=container_name,
            cwd=project_root,
            env=env,
        )
        if status_error:
            return ContainerStartResult(success=False, container_name=container_name, error=status_error)
        if mapped_port is None:
            if existing:
                remove_error = _force_remove_native_db_container(
                    process_runner=process_runner,
                    container_name=container_name,
                    cwd=project_root,
                    env=env,
                )
                if remove_error is not None:
                    return ContainerStartResult(success=False, container_name=container_name, error=remove_error)
                existing = False
        if mapped_port is not None and mapped_port != db_port:
            if port_mismatch_policy(env) == "adopt_existing":
                if status != "running":
                    start_result, start_error = run_docker(
                        process_runner,
                        ["start", container_name],
                        cwd=project_root,
                        env=env,
                        timeout=start_timeout_seconds,
                    )
                    recovered = False
                    recovery_error = None
                    start_timed_out = (start_result is None and timeout_error(start_error)) or (
                        start_result is not None and getattr(start_result, "returncode", 1) == 124
                    )
                    if start_timed_out:
                        recovered, recovery_error = _recover_native_db_start_timeout(
                            process_runner=process_runner,
                            container_name=container_name,
                            port=mapped_port,
                            cwd=project_root,
                            env=env,
                            listener_wait_timeout=listener_wait_timeout,
                        )
                    if (start_result is None or start_timed_out) and not recovered:
                        return ContainerStartResult(
                            success=False,
                            container_name=container_name,
                            error=_native_db_timeout_error_for_retry(
                                port=mapped_port,
                                start_error=start_error
                                or (
                                    run_result_error(start_result, "failed starting supabase db container")
                                    if start_result is not None
                                    else None
                                ),
                                recovery_error=recovery_error,
                            ),
                        )
                    if start_result is not None and getattr(start_result, "returncode", 1) != 0:
                        return ContainerStartResult(
                            success=False,
                            container_name=container_name,
                            error=run_result_error(start_result, "failed starting supabase db container"),
                        )
                if bool(process_runner.wait_for_port(mapped_port, timeout=listener_wait_timeout)):
                    return ContainerStartResult(
                        success=True,
                        container_name=container_name,
                        effective_port=mapped_port,
                        port_adopted=True,
                        container_reused=True,
                    )
                remove_error = _force_remove_native_db_container(
                    process_runner=process_runner,
                    container_name=container_name,
                    cwd=project_root,
                    env=env,
                )
                if remove_error is not None:
                    return ContainerStartResult(
                        success=False,
                        container_name=container_name,
                        error=f"probe timeout waiting for readiness on port {mapped_port}; {remove_error}",
                    )
                existing = False
            remove_error = _force_remove_native_db_container(
                process_runner=process_runner,
                container_name=container_name,
                cwd=project_root,
                env=env,
            )
            if remove_error is not None:
                return ContainerStartResult(success=False, container_name=container_name, error=remove_error)
            existing = False
        elif existing:
            if status != "running":
                start_result, start_error = run_docker(
                    process_runner,
                    ["start", container_name],
                    cwd=project_root,
                    env=env,
                    timeout=start_timeout_seconds,
                )
                recovered = False
                recovery_error = None
                start_timed_out = (start_result is None and timeout_error(start_error)) or (
                    start_result is not None and getattr(start_result, "returncode", 1) == 124
                )
                if start_timed_out:
                    recovered, recovery_error = _recover_native_db_start_timeout(
                        process_runner=process_runner,
                        container_name=container_name,
                        port=db_port,
                        cwd=project_root,
                        env=env,
                        listener_wait_timeout=listener_wait_timeout,
                    )
                if (start_result is None or start_timed_out) and not recovered:
                    return ContainerStartResult(
                        success=False,
                        container_name=container_name,
                        error=_native_db_timeout_error_for_retry(
                            port=db_port,
                            start_error=start_error
                            or (
                                run_result_error(start_result, "failed starting supabase db container")
                                if start_result is not None
                                else None
                            ),
                            recovery_error=recovery_error,
                        ),
                    )
                if start_result is not None and getattr(start_result, "returncode", 1) != 0:
                    return ContainerStartResult(
                        success=False,
                        container_name=container_name,
                        error=run_result_error(start_result, "failed starting supabase db container"),
                    )
            if bool(process_runner.wait_for_port(db_port, timeout=listener_wait_timeout)):
                return ContainerStartResult(
                    success=True,
                    container_name=container_name,
                    effective_port=db_port,
                    container_reused=True,
                )
            remove_error = _force_remove_native_db_container(
                process_runner=process_runner,
                container_name=container_name,
                cwd=project_root,
                env=env,
            )
            if remove_error is not None:
                return ContainerStartResult(
                    success=False,
                    container_name=container_name,
                    error=f"probe timeout waiting for readiness on port {db_port}; {remove_error}",
                )

    env_values = env or {}
    jwt_secret = env_values.get("SUPABASE_JWT_SECRET") or DEFAULT_SUPABASE_JWT_SECRET
    anon_key = env_values.get("SUPABASE_ANON_KEY") or default_supabase_anon_key(secret=jwt_secret)
    service_role_key = env_values.get("SUPABASE_SERVICE_ROLE_KEY") or default_supabase_service_role_key(
        secret=jwt_secret
    )
    create_command = [
        "create",
        "--name",
        container_name,
        "-e",
        f"POSTGRES_PASSWORD={env_values.get('SUPABASE_DB_PASSWORD', 'supabase-db-password')}",
        "-e",
        "POSTGRES_DB=postgres",
        "-e",
        "POSTGRES_USER=postgres",
        "-e",
        f"JWT_SECRET={jwt_secret}",
        "-e",
        f"ANON_KEY={anon_key}",
        "-e",
        f"SERVICE_ROLE_KEY={service_role_key}",
        "-p",
        f"{db_port}:5432",
        "-v",
        f"{volume_name}:/var/lib/postgresql/data",
        "-v",
        f"{compose_root / 'init' / '01-create-n8n-db.sql'}:/docker-entrypoint-initdb.d/01-create-n8n-db.sql:ro",
        "-v",
        (
            f"{compose_root / 'init' / '02-bootstrap-gotrue-auth.sql'}:"
            "/docker-entrypoint-initdb.d/02-bootstrap-gotrue-auth.sql:ro"
        ),
        image,
    ]
    create_result, create_error = run_docker(
        process_runner,
        create_command,
        cwd=project_root,
        env=env,
        timeout=create_timeout_seconds,
    )
    if create_result is None:
        recovered = timeout_error(create_error) and _recover_native_db_create_timeout(
            process_runner=process_runner,
            container_name=container_name,
            cwd=project_root,
            env=env,
        )
        if not recovered:
            return ContainerStartResult(success=False, container_name=container_name, error=create_error)
    elif getattr(create_result, "returncode", 1) != 0:
        return ContainerStartResult(
            success=False,
            container_name=container_name,
            error=run_result_error(create_result, "failed creating supabase db container"),
        )

    start_result, start_error = run_docker(
        process_runner,
        ["start", container_name],
        cwd=project_root,
        env=env,
        timeout=start_timeout_seconds,
    )
    recovered = False
    recovery_error = None
    start_timed_out = (start_result is None and timeout_error(start_error)) or (
        start_result is not None and getattr(start_result, "returncode", 1) == 124
    )
    if start_timed_out:
        recovered, recovery_error = _recover_native_db_start_timeout(
            process_runner=process_runner,
            container_name=container_name,
            port=db_port,
            cwd=project_root,
            env=env,
            listener_wait_timeout=listener_wait_timeout,
        )
    if (start_result is None or start_timed_out) and not recovered:
        return ContainerStartResult(
            success=False,
            container_name=container_name,
            error=_native_db_timeout_error_for_retry(
                port=db_port,
                start_error=start_error
                or (
                    run_result_error(start_result, "failed starting supabase db container")
                    if start_result is not None
                    else None
                ),
                recovery_error=recovery_error,
            ),
        )
    if start_result is not None and getattr(start_result, "returncode", 1) != 0:
        return ContainerStartResult(
            success=False,
            container_name=container_name,
            error=run_result_error(start_result, "failed starting supabase db container"),
        )
    if not bool(process_runner.wait_for_port(db_port, timeout=listener_wait_timeout)):
        return ContainerStartResult(
            success=False,
            container_name=container_name,
            error=f"probe timeout waiting for readiness on port {db_port}",
        )
    return ContainerStartResult(
        success=True,
        container_name=container_name,
        effective_port=db_port,
    )


def _recover_native_db_start_timeout(
    *,
    process_runner,
    container_name: str,
    port: int,
    cwd: Path,
    env: Mapping[str, str] | None,
    listener_wait_timeout: float,
) -> tuple[bool, str | None]:
    recovery_deadline = time.monotonic() + _native_db_start_recovery_timeout_seconds(env)
    published_port: int | None = None
    while time.monotonic() < recovery_deadline:
        status, status_error = container_status(
            process_runner,
            container_name=container_name,
            cwd=cwd,
            env=env,
        )
        if status_error is None and status == "running":
            published_port = _native_db_published_port(
                process_runner,
                container_name=container_name,
                cwd=cwd,
                env=env,
            )
            if published_port is not None and bool(
                process_runner.wait_for_port(published_port, timeout=min(listener_wait_timeout, 1.0))
            ):
                return True, None
        state_error = _native_db_state_error(
            process_runner,
            container_name=container_name,
            cwd=cwd,
            env=env,
        )
        if is_bind_conflict(state_error):
            return False, state_error
        sleeper = getattr(process_runner, "sleep", None)
        if callable(sleeper):
            sleeper(1.0)
        else:
            time.sleep(1.0)
    status, status_error = container_status(
        process_runner,
        container_name=container_name,
        cwd=cwd,
        env=env,
    )
    if status_error is None and status == "running":
        published_port = _native_db_published_port(
            process_runner,
            container_name=container_name,
            cwd=cwd,
            env=env,
        )
        if published_port is None:
            return False, f"published host port missing for port {port}"
        if bool(process_runner.wait_for_port(published_port, timeout=min(listener_wait_timeout, 1.0))):
            return True, None
        return False, f"probe timeout waiting for readiness on port {published_port}"
    state_error = _native_db_state_error(
        process_runner,
        container_name=container_name,
        cwd=cwd,
        env=env,
    )
    if is_bind_conflict(state_error):
        return False, state_error
    return False, None


def _recover_native_db_create_timeout(
    *,
    process_runner,
    container_name: str,
    cwd: Path,
    env: Mapping[str, str] | None,
) -> bool:
    for _ in range(5):
        exists, exists_error = container_exists(
            process_runner,
            container_name=container_name,
            cwd=cwd,
            env=env,
        )
        if exists_error is None and exists:
            return True
        sleeper = getattr(process_runner, "sleep", None)
        if callable(sleeper):
            sleeper(1.0)
        else:
            time.sleep(1.0)
    return False


def _native_db_start_timeout_seconds(env: Mapping[str, str] | None) -> float:
    parsed = env_float(env, "ENVCTL_SUPABASE_DB_START_TIMEOUT_SECONDS", 8.0, minimum=1.0)
    if parsed <= 0:
        return 8.0
    return parsed


def _native_db_start_recovery_timeout_seconds(env: Mapping[str, str] | None) -> float:
    parsed = env_float(env, "ENVCTL_SUPABASE_DB_START_RECOVERY_TIMEOUT_SECONDS", 18.0, minimum=1.0)
    if parsed <= 0:
        return 18.0
    return parsed


def _native_db_state_error(
    process_runner,
    *,
    container_name: str,
    cwd: Path,
    env: Mapping[str, str] | None,
) -> str | None:
    result, error = run_docker(
        process_runner,
        ["inspect", "-f", "{{.State.Error}}", container_name],
        cwd=cwd,
        env=env,
        timeout=10.0,
    )
    if result is None or getattr(result, "returncode", 1) != 0:
        return error
    value = str(getattr(result, "stdout", "") or "").strip()
    return value or None


def _native_db_published_port(
    process_runner,
    *,
    container_name: str,
    cwd: Path,
    env: Mapping[str, str] | None,
) -> int | None:
    result, error = run_docker(
        process_runner,
        ["inspect", "-f", "{{json .NetworkSettings.Ports}}", container_name],
        cwd=cwd,
        env=env,
        timeout=10.0,
    )
    if result is None or getattr(result, "returncode", 1) != 0:
        return None
    payload = str(getattr(result, "stdout", "") or "").strip()
    if not payload:
        return None
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    binding = decoded.get("5432/tcp")
    if not isinstance(binding, list) or not binding:
        return None
    first = binding[0]
    if not isinstance(first, dict):
        return None
    raw_port = str(first.get("HostPort", "")).strip()
    if not raw_port:
        return None
    try:
        return int(raw_port)
    except ValueError:
        return None


def _native_db_timeout_error_for_retry(
    *,
    port: int,
    start_error: str | None,
    recovery_error: str | None,
) -> str:
    if recovery_error:
        return recovery_error
    if timeout_error(start_error):
        return f"host port binding incomplete for port {port} after docker start timeout"
    return start_error or "failed starting supabase db container"


def _force_remove_native_db_container(
    *,
    process_runner,
    container_name: str,
    cwd: Path,
    env: Mapping[str, str] | None,
) -> str | None:
    rm_result, rm_error = run_docker(
        process_runner,
        ["rm", "-f", container_name],
        cwd=cwd,
        env=env,
        timeout=10.0,
    )
    if rm_result is None:
        return rm_error
    if getattr(rm_result, "returncode", 1) != 0:
        return run_result_error(rm_result, "failed removing supabase db container")
    return None


@dataclass(slots=True)
class SupabaseReliabilityContract:
    ok: bool
    fingerprint: str
    errors: list[str]
    compose_path: Path | None


def evaluate_supabase_reliability_contract(project_root: Path) -> SupabaseReliabilityContract:
    compose_root = project_root / "supabase"
    compose_path = compose_root / "docker-compose.yml"
    if not compose_path.is_file():
        return SupabaseReliabilityContract(
            ok=False,
            fingerprint="missing",
            errors=["missing supabase compose file: supabase/docker-compose.yml"],
            compose_path=compose_path,
        )

    try:
        compose_text = compose_path.read_text(encoding="utf-8")
    except OSError as exc:
        return SupabaseReliabilityContract(
            ok=False,
            fingerprint="unreadable",
            errors=[f"failed reading supabase compose file: {exc}"],
            compose_path=compose_path,
        )

    errors: list[str] = []

    if _has_static_network_name(compose_text):
        errors.append("supabase compose defines static network name; use project-scoped network names instead")

    if not _contains_search_path_contract(compose_text):
        errors.append("missing GOTRUE_DB_DATABASE_URL search_path contract (?search_path=auth,public)")
    if not _contains_auth_namespace_var(compose_text, "GOTRUE_DB_NAMESPACE"):
        errors.append("missing GOTRUE_DB_NAMESPACE=auth")
    if not _contains_auth_namespace_var(compose_text, "DB_NAMESPACE"):
        errors.append("missing DB_NAMESPACE=auth")

    if "02-bootstrap-gotrue-auth.sql" not in compose_text:
        errors.append("missing mount for 02-bootstrap-gotrue-auth.sql")
    if "01-create-n8n-db.sql" not in compose_text:
        errors.append("missing mount for 01-create-n8n-db.sql")
    if "kong.yml" not in compose_text:
        errors.append("missing mount for kong.yml")

    errors.extend(_unsafe_mount_path_errors(compose_text))

    fingerprint = _fingerprint_contract_inputs(compose_root, compose_text=compose_text)
    return SupabaseReliabilityContract(
        ok=not errors,
        fingerprint=fingerprint,
        errors=errors,
        compose_path=compose_path,
    )


def read_fingerprint(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("fingerprint")
    return str(value) if isinstance(value, str) and value.strip() else None


def write_fingerprint(path: Path, *, fingerprint: str, project_root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fingerprint": fingerprint,
        "project_root": str(project_root),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def evaluate_managed_supabase_reliability_contract() -> SupabaseReliabilityContract:
    compose_root = dependency_compose_asset_dir("supabase")
    compose_path = compose_root / "docker-compose.yml"
    if not compose_path.is_file():
        return SupabaseReliabilityContract(
            ok=False,
            fingerprint="missing",
            errors=[f"missing envctl managed supabase compose file: {compose_path}"],
            compose_path=compose_path,
        )
    try:
        compose_text = compose_path.read_text(encoding="utf-8")
    except OSError as exc:
        return SupabaseReliabilityContract(
            ok=False,
            fingerprint="unreadable",
            errors=[f"failed reading envctl managed supabase compose file: {exc}"],
            compose_path=compose_path,
        )
    errors: list[str] = []
    if _has_static_network_name(compose_text):
        errors.append("supabase compose defines static network name; use project-scoped network names instead")
    if not _contains_search_path_contract(compose_text):
        errors.append("missing GOTRUE_DB_DATABASE_URL search_path contract (?search_path=auth,public)")
    if not _contains_auth_namespace_var(compose_text, "GOTRUE_DB_NAMESPACE"):
        errors.append("missing GOTRUE_DB_NAMESPACE=auth")
    if not _contains_auth_namespace_var(compose_text, "DB_NAMESPACE"):
        errors.append("missing DB_NAMESPACE=auth")
    if "02-bootstrap-gotrue-auth.sql" not in compose_text:
        errors.append("missing mount for 02-bootstrap-gotrue-auth.sql")
    if "01-create-n8n-db.sql" not in compose_text:
        errors.append("missing mount for 01-create-n8n-db.sql")
    if "kong.yml" not in compose_text:
        errors.append("missing mount for kong.yml")
    errors.extend(_unsafe_mount_path_errors(compose_text))
    fingerprint = _fingerprint_contract_inputs(compose_root, compose_text=compose_text)
    return SupabaseReliabilityContract(
        ok=not errors,
        fingerprint=fingerprint,
        errors=errors,
        compose_path=compose_path,
    )


def _fingerprint_contract_inputs(compose_root: Path, *, compose_text: str) -> str:
    hasher = hashlib.sha256()
    hasher.update(compose_text.encode("utf-8"))
    for rel in (
        Path("kong.yml"),
        Path("init/01-create-n8n-db.sql"),
        Path("init/02-bootstrap-gotrue-auth.sql"),
    ):
        path = compose_root / rel
        hasher.update(str(rel).encode("utf-8"))
        if path.is_file():
            try:
                hasher.update(path.read_bytes())
            except OSError:
                hasher.update(b"<unreadable>")
        else:
            hasher.update(b"<missing>")
    return hasher.hexdigest()


def _compose_service_list(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
) -> set[str]:
    result, error = run_docker(
        process_runner,
        ["compose", "-p", compose_project_name, "-f", str(compose_path), "config", "--services"],
        cwd=compose_root,
        env=env,
        timeout=60.0,
    )
    if result is None or error is not None:
        return set()
    if getattr(result, "returncode", 1) != 0:
        return set()
    stdout = str(getattr(result, "stdout", "") or "")
    return {line.strip() for line in stdout.splitlines() if line.strip()}


def _resolve_service_name(available: set[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in available:
            return candidate
    return None


def _compose_run(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    args: list[str],
) -> str | None:
    if args[:2] == ["up", "-d"]:
        return _run_compose_up_with_recovery(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            args=args,
        )
    return _run_compose_command(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=args,
        timeout_seconds=180.0,
    )


def _run_compose_up_with_recovery(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    args: list[str],
) -> str | None:
    timeout_seconds = env_float(
        env,
        "ENVCTL_SUPABASE_COMPOSE_UP_TIMEOUT_SECONDS",
        120.0,
        minimum=5.0,
    )
    service_names = [value for value in args[2:] if value]
    probe_port = None
    if len(service_names) == 1 and service_names[0] in {"supabase-db", "db"}:
        probe_port = _compose_db_port(compose_root=compose_root)
    up_error = _run_compose_up_with_handoff(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=args,
        timeout_seconds=timeout_seconds,
        service_names=service_names,
        probe_port=probe_port,
    )
    return _recover_compose_up_error(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=args,
        timeout_seconds=timeout_seconds,
        service_names=service_names,
        probe_port=probe_port,
        up_error=up_error,
    )


def _run_compose_command(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    args: list[str],
    timeout_seconds: float,
) -> str | None:
    result, error = run_docker(
        process_runner,
        ["compose", "-p", compose_project_name, "-f", str(compose_path), *args],
        cwd=compose_root,
        env=env,
        timeout=timeout_seconds,
    )
    if result is None:
        return error
    if getattr(result, "returncode", 1) != 0:
        return _normalize_compose_error(
            run_result_error(result, f"docker compose {' '.join(args)} failed"),
            compose_project_name=compose_project_name,
        )
    return None


def _run_compose_up_with_handoff(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    args: list[str],
    timeout_seconds: float,
    service_names: list[str],
    probe_port: int | None,
) -> str | None:
    return _compose_up_handoff(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=args,
        timeout_seconds=timeout_seconds,
        service_names=service_names,
        probe_port=probe_port,
    )


def _recover_compose_up_error(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    args: list[str],
    timeout_seconds: float,
    service_names: list[str],
    probe_port: int | None,
    up_error: str | None,
) -> str | None:
    if up_error is not None and _is_docker_address_pool_exhaustion(up_error):
        cleaned_count, cleanup_error = _remove_empty_envctl_supabase_networks(
            process_runner=process_runner,
            compose_root=compose_root,
            env=env,
        )
        if cleaned_count > 0:
            retry_error = _run_compose_up_with_handoff(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
                args=args,
                timeout_seconds=timeout_seconds,
                service_names=service_names,
                probe_port=probe_port,
            )
            if retry_error is None:
                return None
            if cleanup_error:
                return (
                    f"{retry_error}; after removing {cleaned_count} empty envctl Supabase network(s): "
                    f"{cleanup_error}"
                )
            return retry_error
        if cleanup_error:
            return f"{up_error}; could not recover Docker address-pool exhaustion: {cleanup_error}"
        return f"{up_error}; no empty envctl Supabase networks were available for scoped cleanup"
    if up_error is not None and _is_docker_network_missing(up_error):
        recovered, recovery_detail = _recover_missing_supabase_network_for_project(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
        )
        retry_error = _run_compose_up_with_handoff(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            args=args,
            timeout_seconds=timeout_seconds,
            service_names=service_names,
            probe_port=probe_port,
        )
        if retry_error is None:
            return f"network_recovery={recovery_detail or 'retry_only'}"
        action_detail = recovery_detail or "scoped Supabase network recovery"
        if recovered:
            return (
                f"docker compose {' '.join(args)} failed after scoped Supabase network recovery for "
                f"{compose_project_name}: {retry_error}; recovery_actions={action_detail}"
            )
        return (
            f"docker compose {' '.join(args)} failed after attempted scoped Supabase network recovery for "
            f"{compose_project_name}: {retry_error}; recovery_error={action_detail}"
        )
    return up_error


def _compose_up_handoff(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    args: list[str],
    timeout_seconds: float,
    service_names: list[str],
    probe_port: int | None,
) -> str | None:
    command = ["docker", "compose", "-p", compose_project_name, "-f", str(compose_path), *args]
    process_factory = getattr(process_runner, "compose_up_process", None)
    if callable(process_factory):
        process = cast(
            subprocess.Popen[str],
            process_factory(
                command,
                cwd=str(compose_root),
                env=dict(env) if env is not None else None,
            ),
        )
    else:
        process = subprocess.Popen(
            command,
            cwd=str(compose_root),
            env=dict(env) if env is not None else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    deadline = time.monotonic() + timeout_seconds
    sleeper = getattr(process_runner, "sleep", time.sleep)
    while True:
        returncode = process.poll()
        if returncode is not None:
            stdout, stderr = process.communicate()
            result = subprocess.CompletedProcess(command, returncode, stdout or "", stderr or "")
            if returncode == 0:
                return None
            return _normalize_compose_error(
                run_result_error(result, f"docker compose {' '.join(args)} failed"),
                compose_project_name=compose_project_name,
            )

        if service_names and _compose_services_ready_for_handoff(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            service_names=service_names,
        ):
            if probe_port is None or bool(process_runner.wait_for_port(probe_port, timeout=0.5)):
                _terminate_compose_process(process)
                return None

        if time.monotonic() >= deadline:
            stdout, stderr = _terminate_compose_process(process)
            timed_out_error = f"Command timed out after {timeout_seconds:.1f}s: docker compose {' '.join(args)}"
            if (
                service_names
                and _compose_services_ready_for_handoff(
                    process_runner=process_runner,
                    compose_root=compose_root,
                    compose_project_name=compose_project_name,
                    compose_path=compose_path,
                    env=env,
                    service_names=service_names,
                )
                and (probe_port is None or bool(process_runner.wait_for_port(probe_port, timeout=0.5)))
            ):
                return None
            result = subprocess.CompletedProcess(command, 124, stdout, stderr or timed_out_error)
            return _normalize_compose_error(
                run_result_error(result, f"docker compose {' '.join(args)} failed"),
                compose_project_name=compose_project_name,
            )

        sleeper(0.25)


def _is_docker_address_pool_exhaustion(error: str | None) -> bool:
    return "all predefined address pools have been fully subnetted" in str(error or "").lower()


def _is_docker_network_missing(error: str | None) -> bool:
    normalized = " ".join(str(error or "").lower().split())
    if not normalized:
        return False
    if (
        "failed to set up container networking" in normalized
        and "network" in normalized
        and "not found" in normalized
    ):
        return True
    return bool(re.search(r"\bnetwork\s+[0-9a-f]{12,64}\s+not\s+found\b", normalized))


def _recover_missing_supabase_network_for_project(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
) -> tuple[bool, str | None]:
    down_result, down_error = run_docker(
        process_runner,
        ["compose", "-p", compose_project_name, "-f", str(compose_path), "down", "--remove-orphans"],
        cwd=compose_root,
        env=env,
        timeout=60.0,
    )
    if down_result is not None and getattr(down_result, "returncode", 1) == 0:
        return True, "compose_down_remove_orphans"

    down_detail = down_error
    if down_result is not None and getattr(down_result, "returncode", 1) != 0:
        down_detail = run_result_error(down_result, "docker compose down --remove-orphans failed")

    removed_count, cleanup_error = _remove_empty_supabase_networks_for_project(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        env=env,
    )
    if removed_count > 0:
        detail = f"current_project_empty_networks_removed={removed_count}"
        if cleanup_error:
            detail = f"{detail}; cleanup_error={cleanup_error}"
        return True, detail

    if cleanup_error:
        return False, f"compose_down_error={down_detail}; network_cleanup_error={cleanup_error}"
    if _global_empty_network_recovery_enabled(env):
        global_count, global_error = _remove_empty_envctl_supabase_networks(
            process_runner=process_runner,
            compose_root=compose_root,
            env=env,
        )
        if global_count > 0:
            detail = f"global_empty_networks_removed={global_count}"
            if global_error:
                detail = f"{detail}; cleanup_error={global_error}"
            return True, detail
        if global_error:
            return False, f"compose_down_error={down_detail}; global_cleanup_error={global_error}"
    return False, f"compose_down_error={down_detail or 'unknown'}; no current-project empty Supabase networks removed"


def _remove_empty_supabase_networks_for_project(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    env: Mapping[str, str] | None,
) -> tuple[int, str | None]:
    def include_network(network_name: str) -> bool:
        if not network_name.startswith(f"{compose_project_name}_"):
            return False
        suffix = network_name[len(compose_project_name) :]
        return suffix in {"_default", "_supabase-net"}

    return _remove_empty_docker_networks(
        process_runner=process_runner,
        compose_root=compose_root,
        env=env,
        include_network=include_network,
    )


def _global_empty_network_recovery_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_SUPABASE_NETWORK_RECOVERY_ALLOW_GLOBAL_EMPTY_CLEANUP", False)


def _remove_empty_envctl_supabase_networks(
    *,
    process_runner,
    compose_root: Path,
    env: Mapping[str, str] | None,
) -> tuple[int, str | None]:
    return _remove_empty_docker_networks(
        process_runner=process_runner,
        compose_root=compose_root,
        env=env,
        include_network=lambda network_name: network_name.startswith("envctl-supabase-"),
    )


def _remove_empty_docker_networks(
    *,
    process_runner,
    compose_root: Path,
    env: Mapping[str, str] | None,
    include_network,
) -> tuple[int, str | None]:
    result, run_error = run_docker(
        process_runner,
        ["network", "ls", "--format", "{{.Name}}"],
        cwd=compose_root,
        env=env,
        timeout=20.0,
    )
    if result is None:
        return 0, run_error or "docker network ls failed"
    if getattr(result, "returncode", 1) != 0:
        return 0, run_result_error(result, "docker network ls failed")

    names = [line.strip() for line in str(getattr(result, "stdout", "") or "").splitlines() if line.strip()]
    cleanup_errors: list[str] = []
    removed_count = 0
    for network_name in names:
        if not bool(include_network(network_name)):
            continue
        inspect_result, inspect_error = run_docker(
            process_runner,
            ["network", "inspect", "-f", "{{len .Containers}}", network_name],
            cwd=compose_root,
            env=env,
            timeout=20.0,
        )
        if inspect_result is None:
            cleanup_errors.append(inspect_error or f"failed inspecting Docker network {network_name}")
            continue
        if getattr(inspect_result, "returncode", 1) != 0:
            cleanup_errors.append(run_result_error(inspect_result, f"failed inspecting Docker network {network_name}"))
            continue
        try:
            container_count = int(str(getattr(inspect_result, "stdout", "") or "").strip() or "0")
        except ValueError:
            cleanup_errors.append(f"failed inspecting Docker network {network_name}: invalid container count")
            continue
        if container_count != 0:
            continue
        rm_result, rm_error = run_docker(
            process_runner,
            ["network", "rm", network_name],
            cwd=compose_root,
            env=env,
            timeout=20.0,
        )
        if rm_result is None:
            cleanup_errors.append(rm_error or f"failed removing empty Docker network {network_name}")
            continue
        if getattr(rm_result, "returncode", 1) != 0:
            cleanup_errors.append(run_result_error(rm_result, f"failed removing empty Docker network {network_name}"))
            continue
        removed_count += 1

    return removed_count, "; ".join(cleanup_errors) if cleanup_errors else None


def _compose_services_started(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_names: list[str],
) -> bool:
    return _compose_services_ready_for_handoff(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        service_names=service_names,
    )


def _compose_services_ready_for_handoff(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_names: list[str],
) -> bool:
    states = _compose_service_states(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        service_names=service_names,
    )
    return bool(states) and all(state.exists for state in states)


def _compose_service_states(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_names: list[str],
) -> list[ComposeServiceState]:
    return [
        _compose_service_state(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            service_name=service_name,
        )
        for service_name in service_names
    ]


def _compose_service_state(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_name: str,
) -> ComposeServiceState:
    json_state = _compose_service_state_from_json_ps(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        service_name=service_name,
    )
    if json_state is not None:
        return json_state
    return _compose_service_state_from_ps_q_inspect(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        service_name=service_name,
    )


def _compose_service_state_from_json_ps(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_name: str,
) -> ComposeServiceState | None:
    result, run_error = run_docker(
        process_runner,
        ["compose", "-p", compose_project_name, "-f", str(compose_path), "ps", "--format", "json", service_name],
        cwd=compose_root,
        env=env,
        timeout=10.0,
    )
    if result is None or run_error is not None or getattr(result, "returncode", 1) != 0:
        return None
    stdout = str(getattr(result, "stdout", "") or "").strip()
    if not stdout:
        return None
    rows = _parse_compose_ps_json(stdout)
    if rows is None:
        return None
    matching = [row for row in rows if str(row.get("Service") or row.get("Name") or service_name) == service_name]
    if not matching and len(rows) == 1:
        matching = rows
    if not matching:
        return ComposeServiceState(service=service_name, status="missing")
    return _compose_state_from_ps_row(service_name, matching[0])


def _parse_compose_ps_json(stdout: str) -> list[dict[str, object]] | None:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        rows: list[dict[str, object]] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                return None
            if isinstance(item, dict):
                rows.append(item)
            else:
                return None
        return rows
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        return [parsed]
    return None


def _compose_state_from_ps_row(service_name: str, row: Mapping[str, object]) -> ComposeServiceState:
    container_id = _first_string_value(row, "ID", "Id", "ContainerID", "Container", "Name")
    status = _first_string_value(row, "State", "Status")
    health = _first_string_value(row, "Health")
    exit_code = _first_string_value(row, "ExitCode", "Exit")
    return ComposeServiceState(
        service=service_name,
        container_id=container_id,
        status=status or ("running" if container_id else "missing"),
        health=health,
        exit_code=exit_code,
        published_ports=_compose_published_ports(row.get("Publishers")),
    )


def _first_string_value(row: Mapping[str, object], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _compose_published_ports(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    ports: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        published = item.get("PublishedPort")
        target = item.get("TargetPort")
        if published in (None, "") or target in (None, ""):
            continue
        host = str(item.get("URL") or item.get("HostIP") or "").strip()
        prefix = f"{host}:" if host else ""
        ports.append(f"{prefix}{published}->{target}")
    return ports or None


def _compose_service_state_from_ps_q_inspect(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_name: str,
) -> ComposeServiceState:
    result, run_error = run_docker(
        process_runner,
        ["compose", "-p", compose_project_name, "-f", str(compose_path), "ps", "-q", service_name],
        cwd=compose_root,
        env=env,
        timeout=10.0,
    )
    if result is None:
        return ComposeServiceState(
            service=service_name,
            status="missing",
            error=run_error or "docker compose ps failed",
        )
    if getattr(result, "returncode", 1) != 0:
        return ComposeServiceState(
            service=service_name,
            status="missing",
            error=run_result_error(result, "docker compose ps failed"),
        )
    container_id = str(getattr(result, "stdout", "") or "").strip().splitlines()[0:1]
    if not container_id:
        return ComposeServiceState(service=service_name, status="missing")
    state_result, state_error = run_docker(
        process_runner,
        ["inspect", "-f", "{{json .State}}", container_id[0]],
        cwd=compose_root,
        env=env,
        timeout=10.0,
    )
    if state_result is None:
        return ComposeServiceState(
            service=service_name,
            container_id=container_id[0],
            status="unknown",
            error=state_error or "docker inspect failed",
        )
    if getattr(state_result, "returncode", 1) != 0:
        return ComposeServiceState(
            service=service_name,
            container_id=container_id[0],
            status="unknown",
            error=run_result_error(state_result, "docker inspect failed"),
        )
    return _compose_state_from_inspect_state(
        service_name=service_name,
        container_id=container_id[0],
        state_text=str(getattr(state_result, "stdout", "") or "").strip(),
    )


def _compose_state_from_inspect_state(
    *,
    service_name: str,
    container_id: str,
    state_text: str,
) -> ComposeServiceState:
    try:
        state = json.loads(state_text) if state_text else {}
    except json.JSONDecodeError:
        state = {"Status": state_text}
    if not isinstance(state, dict):
        state = {}
    health = state.get("Health")
    health_status = str(health.get("Status")).strip() if isinstance(health, dict) and health.get("Status") else None
    status = str(state.get("Status")).strip() if state.get("Status") else "unknown"
    exit_code_value = state.get("ExitCode")
    exit_code = str(exit_code_value).strip() if exit_code_value not in (None, "") else None
    state_error = str(state.get("Error")).strip() if state.get("Error") else None
    return ComposeServiceState(
        service=service_name,
        container_id=container_id,
        status=status,
        health=health_status,
        exit_code=exit_code,
        state_error=state_error,
    )


def _terminate_compose_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    stdout = ""
    stderr = ""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        extra_stdout, extra_stderr = process.communicate(timeout=2.0)
        stdout = extra_stdout or ""
        stderr = extra_stderr or ""
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            extra_stdout, extra_stderr = process.communicate(timeout=2.0)
            stdout = extra_stdout or ""
            stderr = extra_stderr or ""
        except subprocess.TimeoutExpired:
            pass
    return stdout, stderr


def _compose_db_port(*, compose_root: Path) -> int | None:
    # Managed supabase DB startup is considered ready once the host DB port accepts connections.
    # Extract the rendered port from the materialized compose file name/location contract.
    env_path = compose_root / ".env"
    if not env_path.is_file():
        return None
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"^SUPABASE_DB_PORT=(\d+)$", text, re.MULTILINE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _compose_timeout_recovered(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_name: str,
    probe_port: int | None,
    error: str | None,
) -> bool:
    if not timeout_error(error):
        return False
    for _ in range(3):
        result, run_error = run_docker(
            process_runner,
            ["compose", "-p", compose_project_name, "-f", str(compose_path), "ps", "-q", service_name],
            cwd=compose_root,
            env=env,
            timeout=60.0,
        )
        if result is not None and run_error is None and getattr(result, "returncode", 1) == 0:
            if str(getattr(result, "stdout", "") or "").strip():
                return True
        elif probe_port and probe_port > 0 and bool(process_runner.wait_for_port(probe_port, timeout=5.0)):
            return True
    return False


def _probe_db_listener(
    *,
    process_runner,
    db_port: int,
    timeout_seconds: float,
    attempts: int,
) -> bool:
    for _ in range(max(1, attempts)):
        if bool(process_runner.wait_for_port(db_port, timeout=timeout_seconds)):
            return True
    return False


def _record_db_probe_stage(
    stage_events: list[dict[str, object]],
    *,
    db_port: int,
    attempts: int,
    action: str,
    ready: bool,
    timeout_seconds: float,
) -> None:
    stage_events.append(
        {
            "stage": "supabase.db.probe",
            "reason": "ready" if ready else "failed",
            "detail": (
                f"action={action} port={db_port} attempts={max(1, attempts)} "
                f"timeout_s={timeout_seconds:g}"
            ),
        }
    )


def _record_compose_network_recovery_stage(stage_events: list[dict[str, object]], error: str | None) -> None:
    if not _is_compose_network_recovery_marker(error):
        return
    detail = str(error).split("network_recovery=", 1)[1].strip()
    if not detail:
        return
    stage_events.append(
        {
            "stage": "supabase.compose.network_recovery",
            "reason": "recovered",
            "detail": detail,
        }
    )


def _is_compose_network_recovery_marker(error: str | None) -> bool:
    return bool(error and str(error).startswith("network_recovery="))


def _recreate_db_service(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    db_service: str,
) -> str | None:
    stop_error = _compose_run(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=["stop", db_service],
    )
    if stop_error is not None:
        return stop_error
    rm_error = _compose_run(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=["rm", "-f", db_service],
    )
    if rm_error is not None:
        return rm_error
    up_error = _compose_run(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=["up", "-d", db_service],
    )
    return up_error


def _inspect_auth_gateway_services(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_names: list[str],
) -> list[dict[str, object]]:
    return [
        _inspect_auth_gateway_service(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            service_name=service_name,
        )
        for service_name in service_names
    ]


def _inspect_auth_gateway_service(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_name: str,
) -> dict[str, object]:
    state = _compose_service_state(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        service_name=service_name,
    )
    return state.to_summary()


def _format_auth_service_state(service_state: Mapping[str, object]) -> str:
    service = str(service_state.get("service") or "unknown")
    parts = [service]
    container = str(service_state.get("container") or "").strip()
    if container:
        parts.append(f"container={container[:12]}")
    for key in ("status", "health", "exit_code", "state_error", "inspect_error"):
        value = str(service_state.get(key) or "").strip()
        if value:
            parts.append(f"{key}={_sanitize_service_state_text(value)}")
    return ":".join(parts[:1]) + (":" + " ".join(parts[1:]) if len(parts) > 1 else "")


def _format_auth_service_states(service_states: list[dict[str, object]]) -> str:
    return "|".join(_format_auth_service_state(service_state) for service_state in service_states)


def _sanitize_service_state_text(value: str) -> str:
    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]
    lines = [line for line in lines if not _is_python_traceback_noise(line)]
    text = " ".join(lines).strip()
    text = re.sub(
        r"\b[A-Z0-9_]*(?:KEY|SECRET|PASSWORD|TOKEN|AUTHORIZATION|APIKEY)[A-Z0-9_]*=[^\s;]+",
        "[redacted]",
        text,
        flags=re.IGNORECASE,
    )
    return (text or "unavailable")[:240]


def _recreate_auth_gateway_services(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_names: list[str],
) -> str | None:
    stop_error = _compose_run(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=["stop", *service_names],
    )
    if stop_error is not None:
        return stop_error
    rm_error = _compose_run(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=["rm", "-f", *service_names],
    )
    if rm_error is not None:
        return rm_error
    return _compose_run(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=["up", "-d", *service_names],
    )


def _normalize_compose_error(error: str, *, compose_project_name: str) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for raw in str(error).splitlines():
        line = raw.strip()
        if not line:
            continue
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    normalized = "\n".join(lines).strip()
    if not normalized:
        return normalized
    if _is_container_name_conflict(normalized):
        container_name = _extract_conflicting_container_name(normalized)
        detail = f"conflicting container={container_name}" if container_name else "conflicting container already exists"
        return (
            f"supabase compose namespace conflict for project {compose_project_name}: {detail}. "
            "This usually means the stack is not using a project-scoped compose namespace "
            "or a stale conflicting container still exists."
        )
    return normalized


def _is_container_name_conflict(error: str) -> bool:
    lowered = error.lower()
    return "container name" in lowered and "already in use" in lowered and "conflict" in lowered


def _extract_conflicting_container_name(error: str) -> str | None:
    match = re.search(r'container name\s+"?/?([^"\s]+)"?', error, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip() or None


def _resolve_supabase_compose_workspace(
    *,
    project_root: Path,
    project_name: str,
    db_port: int,
    public_port: int | None = None,
    runtime_root: Path | None,
    env: Mapping[str, str] | None,
) -> tuple[Path, Path]:
    if runtime_root is None:
        compose_root = project_root / "supabase"
        return compose_root, compose_root / "docker-compose.yml"

    materialized = materialize_dependency_compose(
        runtime_root=runtime_root,
        dependency_name="supabase",
        project_name=project_name,
        compose_project_name=build_supabase_project_name(
            project_root=project_root,
            project_name=project_name,
        ),
        env_values=supabase_managed_env(db_port=db_port, public_port=public_port, env=env),
    )
    return materialized.stack_root, materialized.compose_file


def _resolve_supabase_compose_context(
    *,
    process_runner,
    project_root: Path,
    project_name: str,
    db_port: int,
    public_port: int | None,
    runtime_root: Path | None,
    env: Mapping[str, str] | None,
) -> SupabaseComposeContext:
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
    available_services = _compose_service_list(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
    )
    services = SupabaseServices(
        db=_resolve_service_name(available_services, ("supabase-db", "db")) or "supabase-db",
        auth=_resolve_service_name(available_services, ("supabase-auth", "auth", "gotrue")),
        gateway=_resolve_service_name(available_services, ("supabase-kong", "kong", "gateway")),
    )
    return SupabaseComposeContext(
        compose_root=compose_root,
        compose_path=compose_path,
        compose_project_name=compose_project_name,
        env=env,
        resolved_public_port=resolved_public_port,
        services=services,
    )


def _contains_search_path_contract(compose_text: str) -> bool:
    pattern = re.compile(r"GOTRUE_DB_DATABASE_URL\s*[:=]\s*['\"]?[^'\"\n]*search_path=auth,public", re.IGNORECASE)
    return bool(pattern.search(compose_text))


def _contains_auth_namespace_var(compose_text: str, key: str) -> bool:
    pattern = re.compile(rf"{re.escape(key)}\s*[:=]\s*['\"]?auth(?:['\"]|\s|$)", re.IGNORECASE)
    return bool(pattern.search(compose_text))


def _has_static_network_name(compose_text: str) -> bool:
    lines = compose_text.splitlines()
    in_networks = False
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not in_networks:
            if stripped == "networks:":
                in_networks = True
            continue
        if line and not line.startswith((" ", "\t")):
            break
        if re.search(r"^\s*name\s*:\s*[^$].+", line):
            return True
    return False


def _unsafe_mount_path_errors(compose_text: str) -> list[str]:
    errors: list[str] = []
    for marker in ("kong.yml", "01-create-n8n-db.sql", "02-bootstrap-gotrue-auth.sql"):
        for line in compose_text.splitlines():
            if marker not in line:
                continue
            mount = _extract_mount_source(line)
            if mount is None:
                continue
            if mount.startswith("/"):
                errors.append(f"unsafe absolute mount for {marker}: {mount}")
    return errors


def _extract_mount_source(line: str) -> str | None:
    # Matches compose short syntax: - ./path/file:/container/path[:mode]
    match = re.search(r"^\s*-\s*([^:\s]+):", line)
    if not match:
        return None
    return match.group(1).strip()


def _supabase_auth_health_url(env: Mapping[str, str] | None, public_port: int) -> str:
    public_url = str((env or {}).get("SUPABASE_PUBLIC_URL") or f"http://localhost:{public_port}").rstrip("/")
    return f"{public_url}/auth/v1/health"


def _supabase_local_auth_health_url(public_port: int) -> str:
    return f"http://127.0.0.1:{public_port}/auth/v1/health"


@dataclass(slots=True)
class SupabaseAuthHealthProbeResult:
    ready: bool
    phase: str
    health_url: str
    attempts: list[dict[str, object]]
    last_error: str | None = None
    listener_ready: bool = False


def _probe_supabase_auth_health(
    *,
    process_runner,
    public_port: int,
    health_url: str,
    env: Mapping[str, str] | None,
) -> tuple[bool, str | None]:
    result = _probe_supabase_auth_health_with_attempts(
        process_runner=process_runner,
        public_port=public_port,
        health_url=health_url,
        env=env,
        attempts=1,
        action="probe",
    )
    return result.ready, result.last_error


def _probe_supabase_auth_health_with_attempts(
    *,
    process_runner,
    public_port: int,
    health_url: str,
    env: Mapping[str, str] | None,
    attempts: int,
    action: str,
) -> SupabaseAuthHealthProbeResult:
    last_result: SupabaseAuthHealthProbeResult | None = None
    all_attempts: list[dict[str, object]] = []
    for index in range(max(1, attempts)):
        result = _probe_supabase_auth_health_once(
            process_runner=process_runner,
            public_port=public_port,
            health_url=health_url,
            env=env,
            action=action,
            action_attempt=index + 1,
        )
        all_attempts.extend(result.attempts)
        if result.ready:
            result.attempts = all_attempts
            return result
        last_result = result
    if last_result is None:
        return SupabaseAuthHealthProbeResult(
            ready=False,
            phase="listener",
            health_url=health_url,
            attempts=all_attempts,
            last_error="Supabase Auth/Kong health probe did not run",
            listener_ready=False,
        )
    last_result.attempts = all_attempts
    return last_result


def _probe_supabase_auth_health_once(
    *,
    process_runner,
    public_port: int,
    health_url: str,
    env: Mapping[str, str] | None,
    action: str,
    action_attempt: int,
) -> SupabaseAuthHealthProbeResult:
    probe_attempts: list[dict[str, object]] = []
    timeout_seconds = _auth_probe_timeout_seconds(env)
    if public_port > 0 and not bool(process_runner.wait_for_port(public_port, timeout=timeout_seconds)):
        error = f"listener probe failed on port {public_port}"
        probe_attempts.append(
            {
                "phase": "listener",
                "action": action,
                "action_attempt": action_attempt,
                "port": public_port,
                "health_url": health_url,
                "ready": False,
                "error": error,
            }
        )
        return SupabaseAuthHealthProbeResult(
            ready=False,
            phase="listener",
            health_url=health_url,
            attempts=probe_attempts,
            last_error=error,
            listener_ready=False,
        )
    probe_attempts.append(
        {
            "phase": "listener",
            "action": action,
            "action_attempt": action_attempt,
            "port": public_port,
            "health_url": health_url,
            "ready": True,
        }
    )
    probe_code = (
        "import sys, urllib.error, urllib.request; "
        "url=sys.argv[1]; "
        "timeout=float(sys.argv[2]); "
        "req=urllib.request.Request(url, headers={'Accept':'application/json'}); "
        "\ntry:\n"
        "    resp=urllib.request.urlopen(req, timeout=timeout)\n"
        "except urllib.error.HTTPError as exc:\n"
        "    print(f'HTTPError: {exc.code} {exc.reason}', file=sys.stderr)\n"
        "    raise SystemExit(0 if 200 <= exc.code < 500 else 1)\n"
        "except Exception as exc:\n"
        "    print(f'HTTP health probe failed: {type(exc).__name__}: {exc}', file=sys.stderr)\n"
        "    raise SystemExit(1)\n"
        "raise SystemExit(0 if 200 <= resp.status < 500 else 1)"
    )
    deadline = time.monotonic() + timeout_seconds
    sleeper = getattr(process_runner, "sleep", time.sleep)
    last_error = "HTTP health probe failed"
    http_attempt = 0
    while True:
        http_attempt += 1
        remaining = max(0.1, deadline - time.monotonic())
        result = process_runner.run(
            [sys.executable, "-c", probe_code, health_url, str(min(timeout_seconds, remaining))],
            env=env,
            timeout=min(timeout_seconds, remaining) + 1.0,
        )
        if getattr(result, "returncode", 1) == 0:
            probe_attempts.append(
                {
                    "phase": "http",
                    "action": action,
                    "action_attempt": action_attempt,
                    "attempt": http_attempt,
                    "health_url": health_url,
                    "ready": True,
                    "returncode": 0,
                }
            )
            return SupabaseAuthHealthProbeResult(
                ready=True,
                phase="http",
                health_url=health_url,
                attempts=probe_attempts,
                listener_ready=True,
            )
        last_error = _condense_probe_error(str(
            getattr(result, "stderr", "") or getattr(result, "stdout", "") or "HTTP health probe failed"
        ).strip())
        probe_attempts.append(
            {
                "phase": "http",
                "action": action,
                "action_attempt": action_attempt,
                "attempt": http_attempt,
                "health_url": health_url,
                "ready": False,
                "returncode": int(getattr(result, "returncode", 1) or 1),
                "error": last_error,
            }
        )
        if time.monotonic() >= deadline:
            return SupabaseAuthHealthProbeResult(
                ready=False,
                phase="http",
                health_url=health_url,
                attempts=probe_attempts,
                last_error=last_error,
                listener_ready=True,
            )
        sleeper(min(0.25, max(0.0, deadline - time.monotonic())))


def _condense_probe_error(error: str) -> str:
    lines = [line.strip() for line in str(error or "").splitlines() if line.strip()]
    if not lines:
        return "HTTP health probe failed"
    for line in reversed(lines):
        if "urlopen error" in line.lower():
            match = re.search(r"urlopen error [^>]+", line, re.IGNORECASE)
            return match.group(0) if match else line
    for line in reversed(lines):
        lowered = line.lower()
        if _is_python_traceback_noise(line):
            continue
        if "connectionrefusederror" in lowered or "connection refused" in lowered:
            return line
        if "timed out" in lowered or "timeout" in lowered:
            return line
        if "httperror" in lowered or "http error" in lowered:
            return line
        if re.search(r"\b(?:status(?: code)?|http status|response status)[= :]+[45]\d\d\b", lowered):
            return line
    for line in reversed(lines):
        if not _is_python_traceback_noise(line):
            return line
    return "HTTP health probe failed"


def _is_python_traceback_noise(line: str) -> bool:
    text = str(line).strip()
    return bool(
        text == "Traceback (most recent call last):"
        or text.startswith("During handling of the above exception")
        or re.match(r'^File ".+", line \d+, in .+$', text)
    )


def _supabase_auth_failure_detail(
    *,
    probe: SupabaseAuthHealthProbeResult,
    actions: list[str],
    service_names: list[str],
    public_port: int,
    public_health_url: str,
    service_states: list[dict[str, object]] | None = None,
) -> str:
    parts = [
        f"phase={probe.phase}",
        f"services={','.join(service_names) if service_names else 'none'}",
        f"public_port={public_port}",
        f"probe_url={probe.health_url}",
        f"actions={','.join(actions)}",
        f"last_error={probe.last_error or 'unknown'}",
    ]
    if service_states:
        parts.append(f"service_state={_format_auth_service_states(service_states)}")
    if public_health_url != probe.health_url:
        parts.append(f"public_url={public_health_url}")
    return " ".join(parts)


def _auth_probe_timeout_seconds(env: Mapping[str, str] | None) -> float:
    parsed = env_float(env, "ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS", 5.0, minimum=0.5)
    return parsed if parsed > 0 else 5.0


def _auth_restart_probe_attempts(env: Mapping[str, str] | None) -> int:
    return env_int(env, "ENVCTL_SUPABASE_AUTH_RESTART_PROBE_ATTEMPTS", 2, minimum=1)


def _auth_recreate_probe_attempts(env: Mapping[str, str] | None) -> int:
    return env_int(env, "ENVCTL_SUPABASE_AUTH_RECREATE_PROBE_ATTEMPTS", 3, minimum=1)


def _auth_restart_on_probe_failure_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_SUPABASE_AUTH_RESTART_ON_PROBE_FAILURE", True)


def _auth_recreate_on_probe_failure_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_SUPABASE_AUTH_RECREATE_ON_PROBE_FAILURE", True)


def _db_probe_attempts(env: Mapping[str, str] | None) -> int:
    return env_int(env, "ENVCTL_SUPABASE_DB_PROBE_ATTEMPTS", 2, minimum=1)


def _db_probe_timeout_seconds(env: Mapping[str, str] | None) -> float:
    parsed = env_float(env, "ENVCTL_SUPABASE_DB_PROBE_TIMEOUT_SECONDS", 10.0)
    if parsed <= 0:
        return 30.0
    return parsed


def _db_restart_probe_attempts(env: Mapping[str, str] | None, *, default: int) -> int:
    return env_int(env, "ENVCTL_SUPABASE_DB_RESTART_PROBE_ATTEMPTS", default, minimum=1)


def _db_recreate_probe_attempts(env: Mapping[str, str] | None, *, default: int) -> int:
    return env_int(env, "ENVCTL_SUPABASE_DB_RECREATE_PROBE_ATTEMPTS", default, minimum=1)


def _db_restart_on_probe_failure_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_SUPABASE_DB_RESTART_ON_PROBE_FAILURE", True)


def _db_recreate_on_probe_failure_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_SUPABASE_DB_RECREATE_ON_PROBE_FAILURE", True)


def _native_db_start_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_SUPABASE_DB_START_NATIVE", False)


def build_supabase_project_name(*, project_root: Path, project_name: str) -> str:
    return build_container_name(
        prefix="envctl-supabase",
        project_root=project_root,
        project_name=project_name,
    )
