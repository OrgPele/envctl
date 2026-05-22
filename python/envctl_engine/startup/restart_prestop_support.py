from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.services import service_project_name, service_slug_from_record
from envctl_engine.startup.startup_selection_support import (
    _restart_selected_services,
    restart_include_requirements,
    restart_target_projects,
    restart_target_projects_for_selected_services,
)


@dataclass(frozen=True, slots=True)
class RestartPrestopPreservation:
    preserved_services: dict[str, object]
    preserved_requirements: dict[str, object]
    requirements_to_release: dict[str, object]


@dataclass(frozen=True, slots=True)
class RestartPrestopState:
    restart_lookup_mode: str
    state: object | None
    fallback_route: Route | None


@dataclass(frozen=True, slots=True)
class RestartPrestopSelection:
    selected_services: set[str]
    target_projects: set[str]
    include_requirements: bool


@dataclass(frozen=True, slots=True)
class RestartOrphanListenerScan:
    ports_by_type: dict[str, set[int]]
    selected_by_cwd: dict[str, set[str]]


@dataclass(frozen=True, slots=True)
class RestartOrphanListenerMatch:
    pid: int
    port: int


def restart_fallback_start_route(route: Route, *, restart_lookup_mode: str) -> Route:
    return Route(
        command="start",
        mode=restart_lookup_mode,
        raw_args=route.raw_args,
        passthrough_args=route.passthrough_args,
        projects=route.projects,
        flags={**route.flags, "_restart_request": True},
    )


def restart_prestop_state(*, route: Route, runtime: Any) -> RestartPrestopState:
    restart_lookup_mode = runtime._effective_start_mode(route)
    resumed = runtime._try_load_existing_state(mode=restart_lookup_mode)
    if resumed is not None and resumed.mode != restart_lookup_mode:
        runtime._emit(
            "restart.state_mode_mismatch",
            requested_mode=restart_lookup_mode,
            loaded_mode=resumed.mode,
            run_id=resumed.run_id,
        )
        resumed = None
    fallback_route = None
    if resumed is None:
        fallback_route = restart_fallback_start_route(route, restart_lookup_mode=restart_lookup_mode)
    return RestartPrestopState(
        restart_lookup_mode=restart_lookup_mode,
        state=resumed,
        fallback_route=fallback_route,
    )


def restart_start_route(
    route: Route,
    *,
    restart_lookup_mode: str,
    selected_services: set[str],
    target_projects: set[str],
    include_requirements: bool,
) -> Route:
    return Route(
        command="start",
        mode=restart_lookup_mode,
        raw_args=route.raw_args,
        passthrough_args=route.passthrough_args,
        projects=route.projects,
        flags={
            **route.flags,
            "_restart_request": True,
            "_restart_selected_services": sorted(selected_services),
            "_restart_target_projects": sorted(target_projects),
            "_restart_include_requirements": include_requirements,
        },
    )


def restart_prestop_selection(*, state: Any, route: Route, runtime: Any) -> RestartPrestopSelection:
    selected_services = _restart_selected_services(state=state, route=route)
    target_projects = restart_target_projects(state=state, route=route, runtime=runtime)
    include_requirements = restart_include_requirements(route)
    if include_requirements and not target_projects:
        target_projects = restart_target_projects_for_selected_services(
            selected_services=selected_services,
            state=state,
            runtime=runtime,
        )
    return RestartPrestopSelection(
        selected_services=selected_services,
        target_projects=target_projects,
        include_requirements=include_requirements,
    )


def handle_restart_prestop(
    *,
    runtime: Any,
    session: Any,
    suppress_progress_output: Callable[[Route], bool],
    terminate_restart_orphan_listeners: Callable[..., None],
    spinner_factory: Callable[..., Any],
    use_spinner_policy_fn: Callable[[Any], Any],
    resolve_spinner_policy_fn: Callable[[dict[str, str]], Any],
    emit_spinner_policy_fn: Callable[..., None],
) -> int | None:
    route = session.effective_route
    if route.command != "restart":
        return None
    prestop_state = restart_prestop_state(route=route, runtime=runtime)
    restart_lookup_mode = prestop_state.restart_lookup_mode
    resumed = prestop_state.state
    if prestop_state.fallback_route is not None:
        session.effective_route = prestop_state.fallback_route
        session.runtime_mode = restart_lookup_mode
        return None
    session.restart_state = resumed

    selection = restart_prestop_selection(state=resumed, route=route, runtime=runtime)
    selected_services = selection.selected_services
    target_projects = selection.target_projects
    include_requirements = selection.include_requirements
    runtime._emit(
        "restart.selection",
        include_requirements=include_requirements,
        target_projects=sorted(target_projects),
        selected_services=sorted(selected_services),
    )
    prestop_policy = resolve_spinner_policy_fn(dict(runtime.env))
    use_prestop_spinner = prestop_policy.enabled and not suppress_progress_output(route)
    emit_spinner_policy_fn(
        runtime._emit,
        prestop_policy,
        context={"component": "startup_orchestrator", "op_id": "restart.prestop"},
    )
    with (
        use_spinner_policy_fn(prestop_policy),
        spinner_factory("Restarting services...", enabled=use_prestop_spinner) as prestop_spinner,
    ):
        if use_prestop_spinner:
            runtime._emit(
                "ui.spinner.lifecycle",
                component="startup_orchestrator",
                op_id="restart.prestop",
                state="start",
                message="Restarting services...",
            )
        try:
            runtime._terminate_services_from_state(
                resumed,
                selected_services=selected_services,
                aggressive=False,
                verify_ownership=True,
            )
            terminate_restart_orphan_listeners(
                state=resumed,
                selected_services=selected_services,
                aggressive=True,
            )
            preservation = restart_prestop_preservation(
                resumed,
                selected_services=selected_services,
                include_requirements=include_requirements,
                target_projects=target_projects,
            )
            for requirements in preservation.requirements_to_release.values():
                runtime._release_requirement_ports(requirements)
            session.preserved_requirements = dict(preservation.preserved_requirements)
            session.preserved_services = dict(preservation.preserved_services)
            if use_prestop_spinner:
                prestop_spinner.succeed("Restart pre-stop complete")
                runtime._emit(
                    "ui.spinner.lifecycle",
                    component="startup_orchestrator",
                    op_id="restart.prestop",
                    state="success",
                    message="Restart pre-stop complete",
                )
        except Exception:
            if use_prestop_spinner:
                prestop_spinner.fail("Restart pre-stop failed")
                runtime._emit(
                    "ui.spinner.lifecycle",
                    component="startup_orchestrator",
                    op_id="restart.prestop",
                    state="fail",
                    message="Restart pre-stop failed",
                )
            raise
        finally:
            if use_prestop_spinner:
                runtime._emit(
                    "ui.spinner.lifecycle",
                    component="startup_orchestrator",
                    op_id="restart.prestop",
                    state="stop",
                )
    session.effective_route = restart_start_route(
        route,
        restart_lookup_mode=restart_lookup_mode,
        selected_services=selected_services,
        target_projects=target_projects,
        include_requirements=include_requirements,
    )
    session.runtime_mode = restart_lookup_mode
    return None


def restart_prestop_preservation(
    state: Any,
    *,
    selected_services: set[str],
    include_requirements: bool,
    target_projects: set[str],
) -> RestartPrestopPreservation:
    requirements_to_release: dict[str, object] = {}
    preserved_requirements: dict[str, object] = {}
    for project_name, requirements in getattr(state, "requirements", {}).items():
        if include_requirements and (not target_projects or project_name in target_projects):
            requirements_to_release[project_name] = requirements
        else:
            preserved_requirements[project_name] = requirements
    preserved_services = {
        name: service for name, service in getattr(state, "services", {}).items() if name not in selected_services
    }
    return RestartPrestopPreservation(
        preserved_services=preserved_services,
        preserved_requirements=preserved_requirements,
        requirements_to_release=requirements_to_release,
    )


def restart_port_assignments(
    state: Any,
    *,
    selected_services: set[str],
    project_name_from_service: Callable[[str], str],
) -> dict[str, dict[str, int]]:
    by_project: dict[str, dict[str, int]] = {}
    for service_name, service in getattr(state, "services", {}).items():
        if service_name not in selected_services:
            continue
        project_name = service_project_name(service) or project_name_from_service(service_name)
        service_type = service_slug_from_record(service)
        if not project_name or not service_type:
            continue
        port = getattr(service, "actual_port", None)
        if not isinstance(port, int) or port <= 0:
            port = getattr(service, "requested_port", None)
        if isinstance(port, int) and port > 0:
            by_project.setdefault(project_name.lower(), {})[service_type] = port
    return by_project


def apply_restart_port_assignments(
    contexts: Iterable[Any],
    assignments: dict[str, dict[str, int]],
    *,
    set_plan_port: Callable[[Any, int], None],
) -> None:
    for context in contexts:
        ports = assignments.get(str(getattr(context, "name", "")).strip().lower())
        if not ports:
            continue
        context_ports = getattr(context, "ports", {})
        for service_type, port in ports.items():
            plan = context_ports.get(service_type)
            if plan is None:
                continue
            set_plan_port(plan, port)
            plan.source = "restart"


def apply_restart_ports_to_contexts(
    state: Any | None,
    *,
    route: Route,
    contexts: Iterable[Any],
    project_name_from_service: Callable[[str], str],
    set_plan_port: Callable[[Any, int], None],
) -> None:
    if state is None:
        return
    selected_services_raw = route.flags.get("_restart_selected_services")
    selected_services = set(selected_services_raw) if isinstance(selected_services_raw, list) else set()
    if not selected_services:
        return
    by_project = restart_port_assignments(
        state,
        selected_services=selected_services,
        project_name_from_service=project_name_from_service,
    )
    apply_restart_port_assignments(contexts, by_project, set_plan_port=set_plan_port)


def restart_orphan_listener_scan(
    state: Any,
    *,
    selected_services: set[str],
    backend_port_base: int,
    frontend_port_base: int,
    port_spacing: int,
) -> RestartOrphanListenerScan:
    span = max(int(port_spacing or 20), 1)
    ports_by_type: dict[str, set[int]] = {
        "backend": set(range(int(backend_port_base), int(backend_port_base) + span)),
        "frontend": set(range(int(frontend_port_base), int(frontend_port_base) + span)),
    }
    selected_by_cwd: dict[str, set[str]] = {}
    for service_name, service in getattr(state, "services", {}).items():
        if service_name not in selected_services:
            continue
        service_type = str(getattr(service, "type", "") or "").strip().lower()
        cwd = str(getattr(service, "cwd", "") or "").strip()
        if service_type not in ports_by_type or not cwd:
            continue
        selected_by_cwd.setdefault(cwd, set()).add(service_type)
        for attr_name in ("actual_port", "requested_port"):
            port = getattr(service, attr_name, None)
            if isinstance(port, int) and port > 0:
                ports_by_type[service_type].update(range(max(1, port - span), port + span + 1))
    return RestartOrphanListenerScan(
        ports_by_type=ports_by_type,
        selected_by_cwd=selected_by_cwd,
    )


def restart_matching_orphan_listeners(
    scan: RestartOrphanListenerScan,
    *,
    listener_pids_for_port: Callable[[int], Iterable[int]],
    process_cwd: Callable[[int], str | None],
) -> list[RestartOrphanListenerMatch]:
    matches: list[RestartOrphanListenerMatch] = []
    seen_pids: set[int] = set()
    for cwd, service_types in scan.selected_by_cwd.items():
        for service_type in service_types:
            for port in sorted(scan.ports_by_type.get(service_type, set())):
                for pid in listener_pids_for_port(port):
                    if pid in seen_pids or pid <= 0:
                        continue
                    if process_cwd(pid) != cwd:
                        continue
                    seen_pids.add(pid)
                    matches.append(RestartOrphanListenerMatch(pid=pid, port=port))
    return matches


def terminate_restart_orphan_listeners(
    *,
    state: Any,
    selected_services: set[str],
    aggressive: bool,
    backend_port_base: int,
    frontend_port_base: int,
    port_spacing: int,
    listener_pids_for_port: Callable[[int], Iterable[int]] | None,
    process_cwd: Callable[[int], str | None],
    terminate_pid: Callable[..., bool] | None,
    release_port: Callable[[int], None],
) -> None:
    scan = restart_orphan_listener_scan(
        state,
        selected_services=selected_services,
        backend_port_base=backend_port_base,
        frontend_port_base=frontend_port_base,
        port_spacing=port_spacing,
    )
    if not scan.selected_by_cwd:
        return
    if not callable(listener_pids_for_port) or not callable(terminate_pid):
        return
    matches = restart_matching_orphan_listeners(
        scan,
        listener_pids_for_port=listener_pids_for_port,
        process_cwd=process_cwd,
    )
    for match in matches:
        if terminate_pid(match.pid, term_timeout=0.5 if aggressive else 2.0, kill_timeout=1.0):
            release_port(match.port)
