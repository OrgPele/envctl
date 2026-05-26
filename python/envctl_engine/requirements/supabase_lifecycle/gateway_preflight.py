from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from envctl_engine.requirements.common_contracts import ContainerStartResult
from envctl_engine.requirements.supabase_lifecycle.gateway import (
    _format_gateway_port_mismatch,
    _gateway_public_port_mismatch,
    _remove_auth_gateway_services,
)
from envctl_engine.requirements.supabase_lifecycle.types import _SupabaseStartupBudget
from envctl_engine.shared.protocols import ProcessRuntime


def prepare_supabase_gateway_preflight(
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
) -> ContainerStartResult | None:
    if not gateway_service or not secondary_services:
        return None

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
    if gateway_port_mismatch is None:
        return None

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
    if remove_error is None:
        return None

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
