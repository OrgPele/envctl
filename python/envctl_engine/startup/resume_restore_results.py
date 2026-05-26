from __future__ import annotations

from collections.abc import Mapping

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

    error_message = str(result.get("error") or "").strip()
    if error_message:
        mark_restore_failure_requirements(state, project=project, error=error_message)
        errors.append(f"{project}: {error_message}")
        return

    remove_names_raw = result.get("remove_service_names")
    if isinstance(remove_names_raw, list):
        for service_name in remove_names_raw:
            if isinstance(service_name, str):
                state.services.pop(service_name, None)
    project_services_raw = result.get("project_services")
    if isinstance(project_services_raw, dict):
        for service_name, record in project_services_raw.items():
            if isinstance(service_name, str) and isinstance(record, ServiceRecord):
                state.services[service_name] = record
    requirements_result = result.get("requirements")
    if isinstance(requirements_result, RequirementsResult):
        state.requirements[project] = requirements_result


def mark_restore_failure_requirements(state: RunState, *, project: str, error: str) -> None:
    existing = state.requirements.get(project)
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
