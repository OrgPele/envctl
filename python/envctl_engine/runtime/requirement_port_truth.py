from __future__ import annotations

from pathlib import Path
from typing import Any

from envctl_engine.requirements.common_contracts import build_container_name
from envctl_engine.requirements.component_ports import component_primary_port
from envctl_engine.requirements.container_state_support import container_host_port
from envctl_engine.requirements.supabase import build_supabase_project_name


def requirement_component_port(component_data: dict[str, object]) -> object:
    return component_primary_port(component_data)


def reconcile_requirement_container_ports(
    runtime: Any,
    *,
    project: str | None,
    project_root: Path | None,
    component_name: str,
    component_data: dict[str, object],
) -> None:
    if not bool(component_data.get("enabled", False)):
        return
    if bool(component_data.get("simulated", False)):
        return
    if not bool(component_data.get("success", False)):
        return
    expected_container = str(component_data.get("container_name") or "").strip()
    if not expected_container and project and project_root is not None:
        expected_container = expected_requirement_container_name(
            component_name,
            project_root=project_root,
            project_name=project,
        )
    if not expected_container:
        return
    host_port = published_container_port(
        runtime,
        container_name=expected_container,
        container_port=container_port_for_component(component_name),
        project_root=project_root,
    )
    if isinstance(host_port, int) and host_port > 0:
        set_component_primary_port(component_data, host_port, resource_name=primary_resource_name(component_name))
    if str(component_name).strip().lower() != "supabase":
        return
    api_port = published_container_port(
        runtime,
        container_name=supabase_kong_container_name(
            db_container_name=expected_container,
            project=project,
            project_root=project_root,
        ),
        container_port=8000,
        project_root=project_root,
    )
    if isinstance(api_port, int) and api_port > 0:
        resources = component_resources(component_data)
        resources["api"] = api_port


def published_container_port(
    runtime: Any,
    *,
    container_name: str,
    container_port: int,
    project_root: Path | None,
) -> int | None:
    if not container_name or container_port <= 0:
        return None
    try:
        host_port, port_error = container_host_port(
            runtime.process_runner,
            container_name=container_name,
            container_port=container_port,
            cwd=project_root,
            env=None,
        )
    except Exception:
        return None
    if port_error is not None:
        return None
    return host_port if isinstance(host_port, int) and host_port > 0 else None


def component_resources(component_data: dict[str, object]) -> dict[str, int]:
    resources = component_data.get("resources")
    if isinstance(resources, dict):
        return resources
    component_data["resources"] = {}
    return component_data["resources"]  # type: ignore[return-value]


def set_component_primary_port(component_data: dict[str, object], host_port: int, *, resource_name: str) -> None:
    component_data["final"] = host_port
    resources = component_resources(component_data)
    resources["primary"] = host_port
    if resource_name:
        resources[resource_name] = host_port


def primary_resource_name(component_name: str) -> str:
    normalized = str(component_name).strip().lower()
    if normalized == "supabase":
        return "db"
    return "primary"


def supabase_kong_container_name(*, db_container_name: str, project: str | None, project_root: Path | None) -> str:
    if db_container_name.endswith("-supabase-db-1"):
        return db_container_name[: -len("-supabase-db-1")] + "-supabase-kong-1"
    if project and project_root is not None:
        return build_supabase_project_name(project_root=project_root, project_name=project) + "-supabase-kong-1"
    return ""


def container_port_for_component(component_name: str) -> int:
    normalized = str(component_name).strip().lower()
    if normalized in {"postgres", "supabase"}:
        return 5432
    if normalized == "redis":
        return 6379
    if normalized == "n8n":
        return 5678
    return 0


def expected_requirement_container_name(component_name: str, *, project_root: Path, project_name: str) -> str:
    normalized = str(component_name).strip().lower()
    if normalized == "postgres":
        return build_container_name(prefix="envctl-postgres", project_root=project_root, project_name=project_name)
    if normalized == "redis":
        return build_container_name(prefix="envctl-redis", project_root=project_root, project_name=project_name)
    if normalized == "n8n":
        return build_container_name(prefix="envctl-n8n", project_root=project_root, project_name=project_name)
    if normalized == "supabase":
        return build_supabase_project_name(project_root=project_root, project_name=project_name) + "-supabase-db-1"
    return ""
