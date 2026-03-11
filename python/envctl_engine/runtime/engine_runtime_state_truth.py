from __future__ import annotations

import hashlib
import json
import concurrent.futures
from pathlib import Path
from typing import Any

from envctl_engine.requirements.common import build_container_name, container_exists, container_host_port
from envctl_engine.requirements.supabase import build_supabase_project_name
from envctl_engine.state.models import RequirementsResult, RunState
from envctl_engine.state import state_to_dict
from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.ui.debug_anomaly_rules import detect_state_mismatch_anomaly


def state_fingerprint(state: RunState) -> str:
    payload = json.dumps(state_to_dict(state), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def requirement_component_port(component_data: dict[str, object]) -> object:
    return component_data.get("final") or component_data.get("requested")


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
    if not bool(component_data.get("success", False)):
        if requirements.failures:
            return "unhealthy"
        return "starting"
    port = requirement_component_port(component_data)
    if component_name == "supabase" and (not isinstance(port, int) or port <= 0):
        return "healthy"
    if not isinstance(port, int) or port <= 0:
        return "unreachable"
    if _requirement_owner_mismatch(
        runtime,
        project=project,
        project_root=project_root,
        component_name=component_name,
        component_data=component_data,
        port=port,
    ):
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


def _requirement_owner_mismatch(
    runtime: Any,
    *,
    project: str | None,
    project_root: Path | None,
    component_name: str,
    component_data: dict[str, object],
    port: int,
) -> bool:
    expected_container = str(component_data.get("container_name") or "").strip()
    if not expected_container and project and project_root is not None:
        expected_container = _expected_container_name(component_name, project_root=project_root, project_name=project)
    if not expected_container:
        return False
    try:
        exists, error = container_exists(
            runtime.process_runner,
            container_name=expected_container,
            cwd=project_root,
            env=None,
        )
    except Exception:
        return False
    if error is not None or not exists:
        return True
    try:
        host_port, port_error = container_host_port(
            runtime.process_runner,
            container_name=expected_container,
            container_port=_container_port_for_component(component_name),
            cwd=project_root,
            env=None,
        )
    except Exception:
        return False
    if port_error is not None:
        return True
    return not isinstance(host_port, int) or host_port <= 0 or host_port != port


def _container_port_for_component(component_name: str) -> int:
    normalized = str(component_name).strip().lower()
    if normalized in {"postgres", "supabase"}:
        return 5432
    if normalized == "redis":
        return 6379
    if normalized == "n8n":
        return 5678
    return 0


def _expected_container_name(component_name: str, *, project_root: Path, project_name: str) -> str:
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


def reconcile_project_requirement_truth(
    runtime: Any,
    project: str,
    requirements: RequirementsResult,
    *,
    project_root: Path | None = None,
) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    for definition in dependency_definitions():
        component_name = definition.id
        component_data = requirements.component(component_name)
        runtime_status = requirement_runtime_status(
            runtime,
            project=project,
            project_root=project_root,
            component_name=component_name,
            component_data=component_data,
            requirements=requirements,
        )
        component_data["runtime_status"] = runtime_status
        if runtime_status in {"healthy", "disabled"}:
            continue
        port = requirement_component_port(component_data)
        issues.append(
            {
                "project": project,
                "component": component_name,
                "status": runtime_status,
                "port": port if isinstance(port, int) and port > 0 else None,
            }
        )
    return issues


def reconcile_requirements_truth(runtime: Any, state: RunState) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    items = list(state.requirements.items())
    if not items:
        return issues
    worker_count = min(8, len(items))
    if worker_count <= 1:
        for project, requirements in items:
            issues.extend(
                reconcile_project_requirement_truth(
                    runtime,
                    project,
                    requirements,
                    project_root=_project_root_for_state(state, project),
                )
            )
        return issues
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(
                reconcile_project_requirement_truth,
                runtime,
                project,
                requirements,
                project_root=_project_root_for_state(state, project),
            )
            for project, requirements in items
        ]
        for future in concurrent.futures.as_completed(futures):
            issues.extend(future.result())
    return issues


def _project_root_for_state(state: RunState, project: str) -> Path | None:
    metadata_roots = state.metadata.get("project_roots")
    if not isinstance(metadata_roots, dict):
        return None
    root_value = metadata_roots.get(project)
    if not isinstance(root_value, str) or not root_value.strip():
        return None
    return Path(root_value).expanduser()


def requirement_truth_issues(runtime: Any, state: RunState) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    for project, requirements in state.requirements.items():
        for definition in dependency_definitions():
            component_name = definition.id
            component_data = requirements.component(component_name)
            status = str(component_data.get("runtime_status", "")).strip().lower()
            if not status:
                return reconcile_requirements_truth(runtime, state)
            if status in {"healthy", "disabled"}:
                continue
            port = requirement_component_port(component_data)
            issues.append(
                {
                    "project": project,
                    "component": component_name,
                    "status": status,
                    "port": port if isinstance(port, int) and port > 0 else None,
                }
            )
    return issues


def reconcile_state_truth(runtime: Any, state: RunState) -> list[str]:
    before = state_fingerprint(state)
    runtime._emit("state.fingerprint.before_reconcile", run_id=state.run_id, state_fingerprint_before=before)
    failing_services: list[str] = []
    services = list(state.services.values())
    worker_count = min(8, len(services))
    if worker_count <= 1:
        requirements_future: concurrent.futures.Future[list[dict[str, object]]] | None = None
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            requirements_future = executor.submit(reconcile_requirements_truth, runtime, state)
            for service in services:
                status = runtime._service_truth_status(service)
                service.status = status
                if status not in {"running", "healthy"}:
                    failing_services.append(service.name)
            if requirements_future is not None:
                requirements_future.result()
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(9, worker_count + 1)) as executor:
            requirements_future = executor.submit(reconcile_requirements_truth, runtime, state)
            future_map = {executor.submit(runtime._service_truth_status, service): service for service in services}
            for future in concurrent.futures.as_completed(future_map):
                service = future_map[future]
                status = future.result()
                service.status = status
                if status not in {"running", "healthy"}:
                    failing_services.append(service.name)
            requirements_future.result()
    after = state_fingerprint(state)
    runtime._emit(
        "state.fingerprint.after_reconcile",
        run_id=state.run_id,
        state_fingerprint_before=before,
        state_fingerprint_after=after,
    )
    anomaly = detect_state_mismatch_anomaly(
        state_fingerprint_before=before,
        state_fingerprint_after=after,
        lifecycle_event_seen=bool(failing_services),
    )
    if anomaly is not None:
        runtime._emit(anomaly["event"], **anomaly)
        if runtime._debug_recorder is not None:
            try:
                runtime._debug_recorder.append_anomaly(dict(anomaly))
            except Exception:
                pass
    return failing_services
