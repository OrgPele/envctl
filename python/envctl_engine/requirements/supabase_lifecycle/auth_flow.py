from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from envctl_engine.requirements.common_contracts import ContainerStartResult
from envctl_engine.requirements.supabase_lifecycle.compose import _compose_run
from envctl_engine.requirements.supabase_lifecycle.config import (
    _auth_probe_timeout_seconds,
    _auth_recreate_on_probe_failure_enabled,
    _auth_recreate_probe_attempts,
    _auth_restart_on_probe_failure_enabled,
    _auth_restart_probe_attempts,
)
from envctl_engine.requirements.supabase_lifecycle.formatting import (
    _format_auth_service_state,
    _format_auth_service_states,
    _supabase_auth_failure_detail,
    _supabase_auth_health_url,
    _supabase_local_auth_health_url,
)
from envctl_engine.requirements.supabase_lifecycle.gateway import (
    _format_gateway_port_mismatch,
    _gateway_public_port_mismatch,
    _recreate_auth_gateway_services,
)
from envctl_engine.requirements.supabase_lifecycle.inspect import _inspect_auth_gateway_services
from envctl_engine.requirements.supabase_lifecycle.probe import (
    _auth_services_progressing,
    _probe_supabase_auth_health_with_attempts,
    _wait_for_auth_health_while_progressing,
)
from envctl_engine.requirements.supabase_lifecycle.types import _SupabaseStartupBudget
from envctl_engine.shared.protocols import ProcessRuntime


def complete_supabase_auth_startup(
    *,
    process_runner: ProcessRuntime,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    secondary_services: list[str],
    gateway_service: str | None,
    resolved_public_port: int,
    startup_budget: _SupabaseStartupBudget,
    stage_events: list[dict[str, object]],
    probe_attempts: list[dict[str, object]],
) -> ContainerStartResult:
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


__all__ = ("complete_supabase_auth_startup",)
