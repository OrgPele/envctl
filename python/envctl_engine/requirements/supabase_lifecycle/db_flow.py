from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from envctl_engine.requirements.common_contracts import ContainerStartResult
from envctl_engine.requirements.supabase_lifecycle.compose import _compose_run, _compose_timeout_recovered
from envctl_engine.requirements.supabase_lifecycle.config import (
    _db_probe_attempts,
    _db_probe_timeout_seconds,
    _db_recreate_on_probe_failure_enabled,
    _db_recreate_probe_attempts,
    _db_restart_on_probe_failure_enabled,
    _db_restart_probe_attempts,
)
from envctl_engine.requirements.supabase_lifecycle.formatting import _supabase_db_failure_detail
from envctl_engine.requirements.supabase_lifecycle.gateway import _recreate_db_service
from envctl_engine.requirements.supabase_lifecycle.inspect import _inspect_auth_gateway_services
from envctl_engine.requirements.supabase_lifecycle.probe import (
    _is_compose_network_recovery_marker,
    _probe_db_listener,
    _record_compose_network_recovery_stage,
    _record_db_probe_stage,
)
from envctl_engine.requirements.supabase_lifecycle.types import _SupabaseStartupBudget
from envctl_engine.shared.protocols import ProcessRuntime


def ensure_supabase_db_ready(
    *,
    process_runner: ProcessRuntime,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    db_service: str,
    graph_services: list[str],
    db_port: int,
    db_handoff_recovered: bool,
    startup_budget: _SupabaseStartupBudget,
    stage_events: list[dict[str, object]],
) -> ContainerStartResult | None:
    if db_port <= 0:
        return None

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

    return None


__all__ = ("ensure_supabase_db_ready",)
