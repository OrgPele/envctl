from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path

from envctl_engine.requirements.common import ContainerStartResult
from envctl_engine.requirements.supabase_lifecycle.compose import (
    _compose_service_list,
    _resolve_service_name,
)
from envctl_engine.requirements.supabase_lifecycle.auth_flow import complete_supabase_auth_startup
from envctl_engine.requirements.supabase_lifecycle.config import (
    _native_db_start_enabled,
)
from envctl_engine.requirements.supabase_lifecycle.db_flow import ensure_supabase_db_ready
from envctl_engine.requirements.supabase_lifecycle.gateway import (
    _format_gateway_port_mismatch,
    _gateway_public_port_mismatch,
    _remove_auth_gateway_services,
)
from envctl_engine.requirements.supabase_lifecycle.graph_flow import start_supabase_compose_graph
from envctl_engine.requirements.supabase_lifecycle.native_db import _start_supabase_db_native
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

    graph_failure, db_handoff_recovered = start_supabase_compose_graph(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        db_service=db_service,
        graph_services=graph_services,
        secondary_services=secondary_services,
        db_port=db_port,
        resolved_public_port=resolved_public_port,
        startup_budget=startup_budget,
        stage_events=stage_events,
    )
    if graph_failure is not None:
        return graph_failure

    db_ready_failure = ensure_supabase_db_ready(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        db_service=db_service,
        graph_services=graph_services,
        db_port=db_port,
        db_handoff_recovered=db_handoff_recovered,
        startup_budget=startup_budget,
        stage_events=stage_events,
    )
    if db_ready_failure is not None:
        return db_ready_failure

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
