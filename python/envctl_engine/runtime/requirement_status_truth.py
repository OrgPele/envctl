from __future__ import annotations

from pathlib import Path
from typing import Any

from envctl_engine.requirements.container_state_support import container_exists, container_host_port
from envctl_engine.state.models import RequirementsResult
from envctl_engine.runtime.requirement_port_truth import (
    component_resources,
    container_port_for_component,
    expected_requirement_container_name,
    requirement_component_port,
)


def requirement_runtime_status(
    runtime: Any,
    *,
    project: str | None = None,
    project_root: Path | None = None,
    component_name: str,
    component_data: dict[str, object],
    requirements: RequirementsResult,
) -> str:
    if not bool(component_data.get("enabled", False)):
        return "disabled"
    if bool(component_data.get("simulated", False)):
        return "simulated"
    if bool(component_data.get("external")):
        external_status = str(component_data.get("runtime_status") or "").strip().lower()
        if external_status in {"healthy", "unreachable", "external_unavailable"}:
            return external_status
        return "healthy" if bool(component_data.get("success", False)) else "unreachable"
    if not bool(component_data.get("success", False)):
        if requirements.failures:
            return "unhealthy"
        return "starting"
    port = requirement_component_port(component_data)
    if component_name == "supabase" and (not isinstance(port, int) or port <= 0):
        return "healthy"
    if not isinstance(port, int) or port <= 0:
        return "unreachable"
    if requirement_owner_mismatch(
        runtime,
        project=project,
        project_root=project_root,
        component_name=component_name,
        component_data=component_data,
        port=port,
    ):
        return "unreachable"
    port = requirement_component_port(component_data)
    if not isinstance(port, int) or port <= 0:
        return "unreachable"
    if not runtime._listener_truth_enforced():
        return "healthy"
    try:
        healthy = bool(runtime.process_runner.wait_for_port(port, timeout=runtime._service_truth_timeout()))
    except Exception:  # noqa: BLE001
        healthy = False
    if healthy:
        return "healthy"
    return "unreachable"


def requirement_owner_mismatch(
    runtime: Any,
    *,
    project: str | None,
    project_root: Path | None,
    component_name: str,
    component_data: dict[str, object],
    port: int,
) -> bool:
    expected_container = str(component_data.get("container_name") or "").strip()
    fallback_container = ""
    if not expected_container and project and project_root is not None:
        expected_container = expected_requirement_container_name(
            component_name,
            project_root=project_root,
            project_name=project,
        )
    elif expected_container and project and project_root is not None:
        fallback_container = expected_requirement_container_name(
            component_name,
            project_root=project_root,
            project_name=project,
        )
    if not expected_container:
        return False
    container_port = container_port_for_component(component_name)
    try:
        exists, error = container_exists(
            runtime.process_runner,
            container_name=expected_container,
            cwd=project_root,
            env=None,
        )
    except Exception:
        return False
    if (error is not None or not exists) and adopt_requirement_container(
        runtime,
        component_name=component_name,
        component_data=component_data,
        container_name=fallback_container,
        container_port=container_port,
        cwd=project_root,
    ):
        return False
    if error is not None or not exists:
        return True
    try:
        host_port, port_error = container_host_port(
            runtime.process_runner,
            container_name=expected_container,
            container_port=container_port,
            cwd=project_root,
            env=None,
        )
    except Exception:
        return False
    stale_host_port = port_error is not None or not isinstance(host_port, int) or host_port <= 0 or host_port != port
    if stale_host_port and adopt_requirement_container(
        runtime,
        component_name=component_name,
        component_data=component_data,
        container_name=fallback_container,
        container_port=container_port,
        cwd=project_root,
    ):
        return False
    if port_error is not None:
        return True
    return not isinstance(host_port, int) or host_port <= 0 or host_port != port


def adopt_requirement_container(
    runtime: Any,
    *,
    component_name: str,
    component_data: dict[str, object],
    container_name: str,
    container_port: int,
    cwd: Path | None,
) -> bool:
    container_name = str(container_name or "").strip()
    if not container_name or container_name == str(component_data.get("container_name") or "").strip():
        return False
    try:
        exists, error = container_exists(runtime.process_runner, container_name=container_name, cwd=cwd, env=None)
    except Exception:
        return False
    if error is not None or not exists:
        return False
    try:
        host_port, port_error = container_host_port(
            runtime.process_runner,
            container_name=container_name,
            container_port=container_port,
            cwd=cwd,
            env=None,
        )
    except Exception:
        return False
    if port_error is not None or not isinstance(host_port, int) or host_port <= 0:
        return False
    component_data["container_name"] = container_name
    component_data["final"] = host_port
    resources = component_resources(component_data)
    resources["primary"] = host_port
    resource_key = "db" if str(component_name).strip().lower() == "supabase" else "primary"
    resources[resource_key] = host_port
    return True
