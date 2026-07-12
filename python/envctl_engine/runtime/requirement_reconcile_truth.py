from __future__ import annotations

import concurrent.futures
from pathlib import Path
from typing import Any

from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.runtime.requirement_port_truth import (
    reconcile_requirement_container_ports,
    requirement_component_port,
)
from envctl_engine.runtime.requirement_status_truth import requirement_runtime_status
from envctl_engine.runtime.state_fingerprint_support import state_fingerprint
from envctl_engine.state.models import RequirementsResult, RunState
from envctl_engine.ui.debug_anomaly_rules import detect_state_mismatch_anomaly


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
        reconcile_requirement_container_ports(
            runtime,
            project=project,
            project_root=project_root,
            component_name=component_name,
            component_data=component_data,
        )
        runtime_status = requirement_runtime_status(
            runtime,
            project=project,
            project_root=project_root,
            component_name=component_name,
            component_data=component_data,
            requirements=requirements,
        )
        component_data["runtime_status"] = runtime_status
        if runtime_status in {"healthy", "disabled", "external"}:
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
    items = requirement_truth_work_items(state)
    if not items:
        return issues
    worker_count = min(8, len(items))
    if worker_count <= 1:
        for truth_project, truth_root, requirements in items:
            issues.extend(
                reconcile_project_requirement_truth(
                    runtime,
                    truth_project,
                    requirements,
                    project_root=truth_root,
                )
            )
        return issues
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(
                reconcile_project_requirement_truth,
                runtime,
                truth_project,
                requirements,
                project_root=truth_root,
            )
            for truth_project, truth_root, requirements in items
        ]
        for future in concurrent.futures.as_completed(futures):
            issues.extend(future.result())
    return issues


def project_root_for_state(state: RunState, project: str) -> Path | None:
    metadata_roots = state.metadata.get("project_roots")
    if not isinstance(metadata_roots, dict):
        return None
    root_value = metadata_roots.get(project)
    if not isinstance(root_value, str) or not root_value.strip():
        return None
    return Path(root_value).expanduser()


def requirement_truth_work_items(state: RunState) -> list[tuple[str, Path | None, RequirementsResult]]:
    items: list[tuple[str, Path | None, RequirementsResult]] = []
    seen: set[tuple[str, str, int]] = set()
    for state_key, requirements in state.requirements.items():
        truth_project, truth_root = requirement_truth_identity(state, state_key, requirements)
        root_key = str(truth_root) if truth_root is not None else ""
        item_key = (truth_project, root_key, id(requirements))
        if item_key in seen:
            continue
        seen.add(item_key)
        items.append((truth_project, truth_root, requirements))
    return items


def requirement_truth_identity(
    state: RunState,
    state_key: str,
    requirements: RequirementsResult,
) -> tuple[str, Path | None]:
    requirement_project = str(getattr(requirements, "project", "") or "").strip()
    truth_project = requirement_project or state_key
    shared_scope = str(state.metadata.get("dashboard_dependency_scope", "")).strip().lower() == "shared"
    shared_project = str(state.metadata.get("dashboard_shared_dependency_project", "") or "").strip()
    if shared_scope and requirement_project:
        truth_project = requirement_project
    elif shared_scope and shared_project:
        truth_project = shared_project
    truth_root = project_root_for_state(state, truth_project)
    if truth_root is None and truth_project != state_key:
        truth_root = project_root_for_state(state, state_key)
    return truth_project, truth_root


def requirement_truth_issues(runtime: Any, state: RunState) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    for storage_key, requirements in state.requirements.items():
        project = str(getattr(requirements, "project", "") or storage_key).strip()
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
    failing_services = reconcile_services_and_requirements(runtime, state)
    after = state_fingerprint(state)
    runtime._emit(
        "state.fingerprint.after_reconcile",
        run_id=state.run_id,
        state_fingerprint_before=before,
        state_fingerprint_after=after,
    )
    emit_reconcile_anomaly(runtime, before=before, after=after, failing_services=failing_services)
    return failing_services


def reconcile_services_and_requirements(runtime: Any, state: RunState) -> list[str]:
    failing_services: list[str] = []
    services = list(state.services.values())
    worker_count = min(8, len(services))
    if worker_count <= 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            requirements_future = executor.submit(reconcile_requirements_truth, runtime, state)
            for service in services:
                status = runtime._service_truth_status(service)
                service.status = status
                if status not in {"running", "healthy"}:
                    failing_services.append(service.name)
            requirements_future.result()
        return failing_services
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
    return failing_services


def emit_reconcile_anomaly(runtime: Any, *, before: str, after: str, failing_services: list[str]) -> None:
    anomaly = detect_state_mismatch_anomaly(
        state_fingerprint_before=before,
        state_fingerprint_after=after,
        lifecycle_event_seen=bool(failing_services),
    )
    if anomaly is None:
        return
    runtime._emit(anomaly["event"], **anomaly)
    if runtime._debug_recorder is None:
        return
    try:
        runtime._debug_recorder.append_anomaly(dict(anomaly))
    except Exception:
        pass
