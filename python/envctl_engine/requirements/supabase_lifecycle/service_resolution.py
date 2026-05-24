from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from envctl_engine.requirements.supabase_lifecycle.compose import (
    _compose_service_list,
    _resolve_service_name,
)
from envctl_engine.shared.protocols import ProcessRuntime


@dataclass(frozen=True)
class SupabaseStartupServices:
    db_service: str
    auth_service: str | None
    gateway_service: str | None
    secondary_services: list[str]
    graph_services: list[str]


def resolve_supabase_startup_services(
    *,
    process_runner: ProcessRuntime,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
) -> SupabaseStartupServices:
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
    return SupabaseStartupServices(
        db_service=db_service,
        auth_service=auth_service,
        gateway_service=gateway_service,
        secondary_services=secondary_services,
        graph_services=[db_service, *secondary_services],
    )
