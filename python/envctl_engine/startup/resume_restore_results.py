from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from envctl_engine.startup.resume_restore_policy import (
    _requirements_for_project,
    _store_requirements_for_project,
)
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord


def apply_restore_result(
    state: RunState,
    *,
    project: str,
    result: dict[str, object],
    errors: list[str],
    timing_enabled: bool,
    timing_lines: list[str],
    project_totals_ms: dict[str, float],
) -> None:
    project_total = float(result.get("total_ms", 0.0))
    project_totals_ms[project] = project_total
    steps = result.get("steps")
    step_map = steps if isinstance(steps, dict) else {}
    if timing_enabled:
        timing_lines.append(format_project_timing_line(project, step_map, project_total))

    remove_names_raw = result.get("remove_service_names")
    if isinstance(remove_names_raw, list):
        for service_name in remove_names_raw:
            if isinstance(service_name, str):
                existing = state.services.get(service_name)
                existing_project = str(getattr(existing, "project", "") or "").strip()
                if existing_project and existing_project.casefold() != project.casefold():
                    continue
                state.services.pop(service_name, None)
    project_services_raw = result.get("project_services")
    if isinstance(project_services_raw, dict):
        _store_project_services(state, project=project, services=project_services_raw)
    requirements_result = result.get("requirements")
    if isinstance(requirements_result, RequirementsResult):
        _store_requirements_for_project(
            state,
            project=project,
            requirements=requirements_result,
        )
    raw_unterminated = result.get("unterminated_services")
    if isinstance(raw_unterminated, dict):
        stored_names = _store_unterminated_services(state, raw_unterminated)
        if stored_names:
            existing_failed = state.metadata.get("termination_failed_services")
            failed_names = (
                [name for name in existing_failed if isinstance(name, str)]
                if isinstance(existing_failed, list)
                else []
            )
            state.metadata["termination_failed_services"] = sorted(set(failed_names).union(stored_names))

    error_message = str(result.get("error") or "").strip()
    if error_message:
        mark_restore_failure_requirements(state, project=project, error=error_message)
        errors.append(f"{project}: {error_message}")


def _store_unterminated_services(state: RunState, services: dict[object, object]) -> list[str]:
    occupied = set(state.services)
    stored_names: list[str] = []
    for raw_name, service in services.items():
        if not isinstance(service, ServiceRecord):
            continue
        name = str(raw_name).strip() or service.name
        stored_name = name
        if stored_name in occupied:
            stored_name = _unique_resume_collision_name(name, service, occupied)
        occupied.add(stored_name)
        state.services[stored_name] = replace(
            service,
            name=stored_name,
            status="termination_failed",
            degraded=True,
        )
        stored_names.append(stored_name)
    return stored_names


def _store_project_services(state: RunState, *, project: str, services: dict[object, object]) -> None:
    occupied = set(state.services)
    for raw_name, service in services.items():
        if not isinstance(service, ServiceRecord):
            continue
        name = str(raw_name).strip() or service.name
        stored_service = service if str(service.project or "").strip() else replace(service, project=project)
        stored_name = name
        if stored_name in occupied:
            stored_name = _unique_resume_collision_name(name, stored_service, occupied)
            stored_service = replace(stored_service, name=stored_name)
        elif stored_service.name != stored_name:
            stored_service = replace(stored_service, name=stored_name)
        occupied.add(stored_name)
        state.services[stored_name] = stored_service


def _unique_resume_collision_name(name: str, service: ServiceRecord, occupied: set[str]) -> str:
    pid = service.pid
    suffix = f"Resume Collision {pid}" if isinstance(pid, int) and pid > 0 else "Resume Collision"
    base = f"{name} {suffix}"
    candidate = base
    index = 2
    while candidate in occupied:
        candidate = f"{base} {index}"
        index += 1
    return candidate


def mark_restore_failure_requirements(state: RunState, *, project: str, error: str) -> None:
    existing = _requirements_for_project(state, project)
    if not isinstance(existing, RequirementsResult):
        return
    existing.health = "degraded"
    existing.failures = [str(error).strip() or "resume restore failed"]
    for component in existing.components.values():
        if not isinstance(component, dict):
            continue
        if bool(component.get("enabled", False)):
            component["runtime_status"] = "unreachable"


def format_project_timing_line(project: str, steps: Mapping[str, float], total_ms: float) -> str:
    ordered_steps = (
        "resolve_context",
        "stop_stale_services",
        "release_requirement_ports",
        "reserve_ports",
        "start_requirements",
        "start_services",
        "exception",
    )
    parts: list[str] = [f"{project}"]
    for step in ordered_steps:
        duration = steps.get(step)
        if duration is None:
            continue
        parts.append(f"{step}={duration:.1f}ms")
    parts.append(f"total={total_ms:.1f}ms")
    return "  - " + " ".join(parts)
