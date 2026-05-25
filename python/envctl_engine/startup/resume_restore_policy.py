from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.runtime_context import resolve_port_allocator, resolve_state_repository
from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.shared.parsing import parse_bool
from envctl_engine.shared.protocols import PortAllocator, StateRepository
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord


def _restore_parallel_config(
    orchestrator,
    *,
    route: Route | None,
    mode: str,
    project_count: int,
) -> tuple[bool, int]:
    rt = orchestrator.runtime
    if route is None:
        route = Route(
            command="resume",
            mode=mode,
            raw_args=[],
            passthrough_args=[],
            projects=[],
            flags={},
        )
    source_command = str(route.flags.get("_resume_source_command") or route.command).strip().lower()
    if (
        source_command == "plan"
        and route.flags.get("parallel_trees") is None
        and not bool(route.flags.get("sequential"))
    ):
        route = Route(
            command=route.command,
            mode=route.mode,
            raw_args=route.raw_args,
            passthrough_args=route.passthrough_args,
            projects=route.projects,
            flags={
                **route.flags,
                "parallel_trees": True,
            },
        )
    return rt._tree_parallel_startup_config(mode=mode, route=route, project_count=project_count)  # type: ignore[attr-defined]


def _restore_timing_enabled(orchestrator, route: Route | None) -> bool:
    rt = orchestrator.runtime
    raw_force = rt.env.get("ENVCTL_DEBUG_RESTORE_TIMING") or rt.config.raw.get("ENVCTL_DEBUG_RESTORE_TIMING")  # type: ignore[attr-defined]
    if parse_bool(raw_force, False):
        return True
    if route is not None:
        if bool(route.flags.get("debug_ui")) or bool(route.flags.get("debug_ui_deep")):
            return True
    raw_mode = (rt.env.get("ENVCTL_DEBUG_UI_MODE") or rt.config.raw.get("ENVCTL_DEBUG_UI_MODE") or "").strip().lower()  # type: ignore[attr-defined]
    return raw_mode in {"standard", "deep"}


def _requirements_reuse_decision(
    orchestrator,
    rt: Any,
    *,
    project: str,
    requirements: RequirementsResult | None,
    project_root: Path | None = None,
) -> tuple[bool, str]:
    _ = orchestrator
    if requirements is None:
        return False, "bootstrap_cache_miss"
    if not rt._requirements_ready(requirements):  # type: ignore[attr-defined]
        return False, "dependency_endpoint_changed"
    reconcile = getattr(rt, "_reconcile_project_requirement_truth", None)
    if callable(reconcile):
        try:
            issues = reconcile(project, requirements, project_root=project_root)
        except Exception:
            return False, "dependency_endpoint_changed"
        return (not bool(issues), "service_stale_only" if not issues else "dependency_endpoint_changed")
    return True, "service_stale_only"


def _configured_restore_service_types(rt: Any, *, mode: str, context: object) -> set[str]:
    ports = getattr(context, "ports", {})
    port_service_types = (
        {str(name).strip().lower() for name in ports if str(name).strip()} if isinstance(ports, dict) else set()
    )
    configured: set[str] = set()
    service_enabled_for_mode = getattr(rt, "_service_enabled_for_mode", None)
    for service_name in ("backend", "frontend"):
        enabled = service_name in port_service_types
        if callable(service_enabled_for_mode):
            try:
                enabled = bool(service_enabled_for_mode(mode, service_name))
            except TypeError:
                enabled = service_name in port_service_types
        if enabled:
            configured.add(service_name)

    config = getattr(rt, "config", None)
    for service in getattr(config, "additional_services", ()) or ():
        name = str(getattr(service, "name", "") or "").strip().lower()
        if not name:
            continue
        enabled_for_project = getattr(service, "enabled_for_project_root", None)
        if callable(enabled_for_project):
            if bool(enabled_for_project(mode, getattr(context, "root", None))):
                configured.add(name)
            continue
        enabled_for_mode = getattr(service, "enabled_for_mode", None)
        if callable(enabled_for_mode) and bool(enabled_for_mode(mode)):
            configured.add(name)
            continue
        if name in port_service_types:
            configured.add(name)
    if not configured:
        configured.update(port_service_types)
    return configured


def _service_types_for_names(
    *,
    project: str,
    service_names: list[str],
    services: Mapping[str, ServiceRecord],
) -> set[str]:
    service_types: set[str] = set()
    project_prefix = project.strip().lower()
    for service_name in service_names:
        record = services.get(service_name)
        raw_type = str(getattr(record, "type", "") or "").strip().lower() if record is not None else ""
        if raw_type:
            service_types.add(raw_type)
            continue
        normalized_name = str(service_name).strip()
        suffix = normalized_name
        if project_prefix and normalized_name.lower().startswith(project_prefix):
            suffix = normalized_name[len(project) :].strip()
        if suffix:
            service_types.add("-".join(suffix.lower().split()))
    return {value for value in service_types if value}


def _route_for_partial_service_restore(route: Route, *, selected_service_types: set[str]) -> Route:
    if not selected_service_types:
        return route
    return Route(
        command=route.command,
        mode=route.mode,
        raw_args=route.raw_args,
        passthrough_args=route.passthrough_args,
        projects=route.projects,
        flags={
            **route.flags,
            "_restart_request": True,
            "restart_service_types": sorted(selected_service_types),
        },
    )


def _resume_terminate_aggressive(orchestrator, rt: Any) -> bool:
    _ = orchestrator
    raw = rt.env.get("ENVCTL_RESUME_AGGRESSIVE_TERMINATE") or rt.config.raw.get("ENVCTL_RESUME_AGGRESSIVE_TERMINATE")  # type: ignore[attr-defined]
    return parse_bool(raw, True)


def _reserve_application_service_ports(
    orchestrator,
    rt: Any,
    context: object,
    port_allocator: PortAllocator,
    *,
    selected_service_types: set[str] | None = None,
) -> None:
    _ = orchestrator
    context_name = str(getattr(context, "name", ""))
    ports = getattr(context, "ports", {})
    if not isinstance(ports, dict):
        return
    service_names = sorted(selected_service_types or set(ports))
    for service_name in service_names:
        plan = ports.get(service_name)
        if plan is None:
            continue
        assigned = getattr(plan, "assigned", None)
        final = getattr(plan, "final", None)
        if not isinstance(assigned, int) or assigned <= 0:
            continue
        owner = f"{context_name}:{service_name}"
        reserved = port_allocator.reserve_next(assigned, owner=owner)
        if reserved != final:
            port_allocator.update_final_port(plan, reserved, source="retry")
            rt._emit("port.rebound", project=context_name, service=service_name, port=reserved)  # type: ignore[attr-defined]
        else:
            plan.assigned = reserved
            plan.final = reserved
        rt._emit("port.reserved", project=context_name, service=service_name, port=reserved)  # type: ignore[attr-defined]


def context_for_project(orchestrator, state: RunState, project: str) -> object | None:
    rt = orchestrator.runtime
    discovered = rt._discover_projects(mode=state.mode)  # type: ignore[attr-defined]
    for context in discovered:
        if context.name.lower() == project.lower():
            orchestrator.apply_ports_to_context(context, state)
            return context

    root = orchestrator.project_root(state, project)
    if root is None:
        return None
    contexts = rt._contexts_from_raw_projects([(project, root)])  # type: ignore[attr-defined]
    if not contexts:
        return None
    context = contexts[0]
    orchestrator.apply_ports_to_context(context, state)
    return context


def project_root(orchestrator, state: RunState, project: str) -> Path | None:
    rt = orchestrator.runtime
    metadata_roots = state.metadata.get("project_roots")
    if isinstance(metadata_roots, Mapping):
        root_value = metadata_roots.get(project)
        if isinstance(root_value, str) and root_value.strip():
            candidate = Path(root_value).expanduser()
            if not candidate.is_absolute():
                candidate = (rt.config.base_dir / candidate).resolve()  # type: ignore[attr-defined]
            if candidate.is_dir():
                return candidate

    if project == "Main":
        return rt.config.base_dir  # type: ignore[attr-defined]

    for service_name, service in state.services.items():
        if rt._project_name_from_service(service_name).lower() != project.lower():  # type: ignore[attr-defined]
            continue
        cwd_raw = getattr(service, "cwd", None)
        if not isinstance(cwd_raw, str) or not cwd_raw.strip():
            continue
        candidate = Path(cwd_raw).expanduser()
        if not candidate.is_absolute():
            candidate = (rt.config.base_dir / candidate).resolve()  # type: ignore[attr-defined]
        if candidate.name in {"backend", "frontend"}:
            candidate = candidate.parent
        if candidate.is_dir():
            return candidate

    return None


def apply_ports_to_context(orchestrator, context: object, state: RunState) -> None:
    rt = orchestrator.runtime
    project = str(getattr(context, "name", ""))
    context_ports = getattr(context, "ports", {})
    if not isinstance(context_ports, dict):
        return

    requirements = state.requirements.get(project)
    if requirements is not None:
        for definition in dependency_definitions():
            plan = context_ports.get(definition.resources[0].legacy_port_key)
            if plan is None:
                continue
            rt._set_plan_port_from_component(plan, requirements.component(definition.id))  # type: ignore[attr-defined]

    for service_name, service in state.services.items():
        if rt._project_name_from_service(service_name).lower() != project.lower():  # type: ignore[attr-defined]
            continue
        service_type = (getattr(service, "type", "") or "").strip().lower()
        port = getattr(service, "actual_port", None)
        if not isinstance(port, int) or port <= 0:
            port = getattr(service, "requested_port", None)
        if not isinstance(port, int) or port <= 0:
            continue
        if service_type == "backend":
            rt._set_plan_port(context_ports["backend"], port)  # type: ignore[attr-defined]
        elif service_type == "frontend":
            rt._set_plan_port(context_ports["frontend"], port)  # type: ignore[attr-defined]


def _state_repository(runtime: object) -> StateRepository:
    return resolve_state_repository(runtime)


def _port_allocator(runtime: object) -> PortAllocator:
    return resolve_port_allocator(runtime)
