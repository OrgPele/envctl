from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from envctl_engine.requirements.common_contracts import ContainerStartResult
from envctl_engine.requirements.supabase_lifecycle.compose import (
    _compose_run,
    _compose_timeout_recovered,
    _compose_up_timeout_seconds,
    _is_compose_port_publish_stall,
)
from envctl_engine.requirements.supabase_lifecycle.formatting import (
    _supabase_compose_failure_detail,
    _supabase_local_auth_health_url,
)
from envctl_engine.requirements.supabase_lifecycle.inspect import _inspect_auth_gateway_services
from envctl_engine.requirements.supabase_lifecycle.probe import (
    _is_compose_network_recovery_marker,
    _record_compose_network_recovery_stage,
)
from envctl_engine.requirements.supabase_lifecycle.types import _SupabaseStartupBudget
from envctl_engine.shared.protocols import ProcessRuntime


def start_supabase_compose_graph(
    *,
    process_runner: ProcessRuntime,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    db_service: str,
    graph_services: list[str],
    secondary_services: list[str],
    db_port: int,
    resolved_public_port: int,
    startup_budget: _SupabaseStartupBudget,
    stage_events: list[dict[str, object]],
) -> tuple[ContainerStartResult | None, bool]:
    compose_up_timeout = _compose_up_timeout_seconds(env, service_names=graph_services)
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
    if up_db is None:
        return None, False

    if _is_compose_network_recovery_marker(up_db):
        _record_compose_network_recovery_stage(stage_events, up_db)
        return None, True

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
    if db_handoff_recovered:
        return None, True

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
    return (
        ContainerStartResult(
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
        ),
        False,
    )


__all__ = ("start_supabase_compose_graph",)
