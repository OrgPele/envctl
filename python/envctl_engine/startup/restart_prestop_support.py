from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.docker_service_runtime import state_uses_docker_services
from envctl_engine.runtime.lifecycle_requirement_ports import release_port_reservation
from envctl_engine.runtime.lifecycle_service_termination import failed_listener_pids, unconfirmed_service_names
from envctl_engine.state.lookup import call_state_loader
from envctl_engine.runtime.runtime_context import resolve_port_allocator, resolve_process_runtime
from envctl_engine.shared.process_cwd import process_cwd
from envctl_engine.shared.services import (
    service_project_name,
    service_slug_from_record,
)
from envctl_engine.startup.startup_selection_support import (
    _configured_service_projects_for_selector,
    _observed_service_types_for_selector,
    restart_include_requirements,
    restart_selected_services_for_type_map,
    restart_service_types_by_project,
    state_project_names,
    restart_target_projects,
    restart_target_projects_for_selected_services,
)
from envctl_engine.startup.session import metadata_with_state_sources


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
    service_types_by_project: dict[str, set[str]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RestartOrphanListenerScan:
    ports_by_type: dict[str, set[int]]
    selected_by_cwd: dict[str, set[str]]
    owners_by_cwd_type: dict[tuple[str, str], tuple[str, ...]] = field(default_factory=dict)
    port_lock_sessions_by_cwd_type: dict[tuple[str, str], tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RestartOrphanListenerMatch:
    pid: int
    port: int
    owner_candidates: tuple[str, ...] = ()
    port_lock_sessions: tuple[str, ...] = ()


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
    resumed = call_state_loader(
        runtime._try_load_existing_state,
        mode=restart_lookup_mode,
        project_names=route.projects or None,
    )
    if resumed is not None and resumed.mode != restart_lookup_mode:
        runtime._emit(
            "restart.state_mode_mismatch",
            requested_mode=restart_lookup_mode,
            loaded_mode=resumed.mode,
            run_id=resumed.run_id,
        )
        resumed = None
    if resumed is not None and state_uses_docker_services(resumed):
        route.flags["docker"] = True
        runtime.env["DOCKER_MODE"] = "true"
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
    service_types_by_project: dict[str, set[str]] | None = None,
) -> Route:
    type_map = (
        {
            project: sorted(service_types)
            for project, service_types in sorted(service_types_by_project.items(), key=lambda item: item[0].casefold())
        }
        if service_types_by_project is not None
        else None
    )
    return Route(
        command="start",
        mode=restart_lookup_mode,
        raw_args=route.raw_args,
        passthrough_args=route.passthrough_args,
        projects=sorted(target_projects, key=str.casefold) if target_projects else route.projects,
        flags={
            **route.flags,
            "_restart_request": True,
            "_restart_selected_services": sorted(selected_services),
            "_restart_target_projects": sorted(target_projects),
            "_restart_include_requirements": include_requirements,
            **({"_restart_service_types_by_project": type_map} if type_map is not None else {}),
        },
    )


def restart_prestop_selection(*, state: Any, route: Route, runtime: Any) -> RestartPrestopSelection:
    target_projects = restart_target_projects(state=state, route=route, runtime=runtime)
    include_requirements = restart_include_requirements(route)
    if include_requirements and not target_projects and not isinstance(route.flags.get("services"), list):
        target_projects = restart_target_projects_for_selected_services(
            selected_services=set(),
            state=state,
            runtime=runtime,
        )
    service_types_by_project = restart_service_types_by_project(
        state=state,
        route=route,
        runtime=runtime,
        target_projects=target_projects,
    )
    selected_services = restart_selected_services_for_type_map(
        state=state,
        runtime=runtime,
        service_types_by_project=service_types_by_project,
    )
    return RestartPrestopSelection(
        selected_services=selected_services,
        target_projects=target_projects,
        include_requirements=include_requirements,
        service_types_by_project=service_types_by_project,
    )


def handle_restart_prestop(
    *,
    runtime: Any,
    session: Any,
    suppress_progress_output: Callable[[Route], bool],
    terminate_restart_orphan_listeners: Callable[..., set[int]],
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
    previous_preserve_flag = bool(getattr(session, "preserve_existing_state_on_failure", False))
    source_services = {
        **dict(getattr(resumed, "services", {})),
        **dict(session.preserved_services),
    }
    source_requirements = {
        **dict(getattr(resumed, "requirements", {})),
        **dict(session.preserved_requirements),
    }
    source_metadata = metadata_with_state_sources(
        {**dict(getattr(resumed, "metadata", {})), **dict(session.base_metadata)},
        resumed,
    )
    session.preserved_services = source_services
    session.preserved_requirements = source_requirements
    session.base_metadata = source_metadata
    session.preserve_existing_state_on_failure = True

    selection = restart_prestop_selection(state=resumed, route=route, runtime=runtime)
    selected_services = selection.selected_services
    target_projects = selection.target_projects
    include_requirements = selection.include_requirements
    _validate_restart_selection(
        state=resumed,
        route=route,
        runtime=runtime,
        target_projects=target_projects,
        service_types_by_project=selection.service_types_by_project,
    )
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
    preservation = restart_prestop_preservation(
        resumed,
        selected_services=selected_services,
        include_requirements=include_requirements,
        target_projects=target_projects,
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
            termination_result = runtime._terminate_services_from_state(
                resumed,
                selected_services=selected_services,
                aggressive=False,
                verify_ownership=True,
            )
            failed_services = unconfirmed_service_names(termination_result, selected_services)
            if failed_services:
                session.preserve_existing_state_on_failure = True
                raise RuntimeError(
                    "Restart aborted because existing services could not be stopped: "
                    + ", ".join(sorted(failed_services))
                )
            orphan_result = terminate_restart_orphan_listeners(
                state=resumed,
                selected_services=selected_services,
                aggressive=True,
            )
            failed_orphan_pids = failed_listener_pids(orphan_result)
            if failed_orphan_pids is None:
                session.preserve_existing_state_on_failure = True
                raise RuntimeError("Restart aborted because orphan listener cleanup was not confirmed")
            if failed_orphan_pids:
                session.preserve_existing_state_on_failure = True
                raise RuntimeError(
                    "Restart aborted because orphan listeners could not be stopped: "
                    + ", ".join(str(pid) for pid in sorted(failed_orphan_pids))
                )
            for requirements in preservation.requirements_to_release.values():
                runtime._release_requirement_ports(requirements)
            session.preserved_requirements = dict(preservation.preserved_requirements)
            session.preserved_services = dict(preservation.preserved_services)
            session.base_metadata = metadata_with_state_sources(
                {**dict(resumed.metadata), **dict(session.base_metadata)},
                resumed,
            )
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
            session.preserved_services = source_services
            session.preserved_requirements = source_requirements
            session.base_metadata = source_metadata
            session.preserve_existing_state_on_failure = True
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
        service_types_by_project=selection.service_types_by_project,
    )
    session.runtime_mode = restart_lookup_mode
    session.preserve_existing_state_on_failure = previous_preserve_flag
    return None


def _validate_restart_selection(
    *,
    state: Any,
    route: Route,
    runtime: Any,
    target_projects: set[str],
    service_types_by_project: dict[str, set[str]] | None = None,
) -> None:
    requested_projects = {str(project).strip() for project in route.projects if str(project).strip()}
    if requested_projects:
        known_projects = {name.casefold() for name in state_project_names(runtime=runtime, state=state)}
        unknown_projects = sorted(
            project for project in requested_projects if project.casefold() not in known_projects
        )
        if unknown_projects:
            raise RuntimeError("No active restart target found for project(s): " + ", ".join(unknown_projects))

    service_selectors = route.flags.get("services")
    requested_services = [
        str(selector).strip()
        for selector in (service_selectors if isinstance(service_selectors, list) else [])
        if str(selector).strip()
    ]
    requested_project_keys = {project.casefold() for project in requested_projects}
    selector_matches: dict[str, dict[str, set[str]]] = {}
    unmatched_services: list[str] = []
    for selector in requested_services:
        matches: dict[str, set[str]] = {}
        for source in (
            _observed_service_types_for_selector(
                state=state,
                runtime=runtime,
                selector=selector,
            ),
            _configured_service_projects_for_selector(
                state=state,
                runtime=runtime,
                selector=selector,
            ),
        ):
            for project, service_types in source.items():
                matches.setdefault(project, set()).update(service_types)
        scoped_matches = {
            project: service_types
            for project, service_types in matches.items()
            if not requested_project_keys or project.casefold() in requested_project_keys
        }
        selector_matches[selector] = scoped_matches
        if not scoped_matches:
            unmatched_services.append(selector)
    if unmatched_services:
        raise RuntimeError("No matching services found for restart: " + ", ".join(unmatched_services))
    if requested_services and not target_projects:
        possible_projects = {
            project.casefold()
            for matches in selector_matches.values()
            for project in matches
        }
        if len(possible_projects) > 1:
            raise RuntimeError(
                "Restart service selector is ambiguous across active projects; add --project: "
                + ", ".join(requested_services)
            )
        raise RuntimeError("No active restart target found for service(s): " + ", ".join(requested_services))

    if service_types_by_project is None:
        service_types_by_project = restart_service_types_by_project(
            state=state,
            route=route,
            runtime=runtime,
            target_projects=target_projects,
        )
    target_keys = {project.casefold() for project in target_projects}
    final_by_key = {
        project.casefold(): set(service_types)
        for project, service_types in service_types_by_project.items()
    }
    filtered_services = [
        selector
        for selector, matches in selector_matches.items()
        if not any(
            project.casefold() in target_keys
            and bool(service_types.intersection(final_by_key.get(project.casefold(), set())))
            for project, service_types in matches.items()
        )
    ]
    if filtered_services:
        raise RuntimeError(
            "Restart service selector conflicts with the requested launch scope: "
            + ", ".join(filtered_services)
        )


def restart_prestop_preservation(
    state: Any,
    *,
    selected_services: set[str],
    include_requirements: bool,
    target_projects: set[str],
) -> RestartPrestopPreservation:
    requirements_to_release: dict[str, object] = {}
    preserved_requirements: dict[str, object] = {}
    target_project_keys = {str(project).strip().casefold() for project in target_projects if str(project).strip()}
    for storage_name, requirements in getattr(state, "requirements", {}).items():
        project_name = str(getattr(requirements, "project", "") or storage_name).strip()
        if include_requirements and (
            not target_project_keys or project_name.casefold() in target_project_keys
        ):
            requirements_to_release[storage_name] = requirements
        else:
            preserved_requirements[storage_name] = requirements
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
    owners_by_cwd_type: dict[tuple[str, str], tuple[str, ...]] = {}
    port_lock_sessions_by_cwd_type: dict[tuple[str, str], tuple[str, ...]] = {}
    for service_name, service in getattr(state, "services", {}).items():
        if service_name not in selected_services:
            continue
        service_type = str(getattr(service, "type", "") or "").strip().lower()
        cwd = str(getattr(service, "cwd", "") or "").strip()
        if service_type not in ports_by_type or not cwd:
            continue
        selected_by_cwd.setdefault(cwd, set()).add(service_type)
        project = str(service_project_name(service) or service_name.rsplit(" ", 1)[0]).strip()
        if project:
            owners_by_cwd_type[(cwd, service_type)] = (
                f"{project}:{service_type}",
                f"{project}:services:{service_type}-launch",
                f"{project}:services",
            )
        raw_port_lock_session = getattr(service, "port_lock_session", None)
        port_lock_session = raw_port_lock_session.strip() if isinstance(raw_port_lock_session, str) else ""
        if port_lock_session:
            key = (cwd, service_type)
            port_lock_sessions_by_cwd_type[key] = tuple(
                dict.fromkeys((*port_lock_sessions_by_cwd_type.get(key, ()), port_lock_session))
            )
        for attr_name in ("actual_port", "requested_port"):
            port = getattr(service, attr_name, None)
            if isinstance(port, int) and port > 0:
                ports_by_type[service_type].update(range(max(1, port - span), port + span + 1))
    return RestartOrphanListenerScan(
        ports_by_type=ports_by_type,
        selected_by_cwd=selected_by_cwd,
        owners_by_cwd_type=owners_by_cwd_type,
        port_lock_sessions_by_cwd_type=port_lock_sessions_by_cwd_type,
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
                    matches.append(
                        RestartOrphanListenerMatch(
                            pid=pid,
                            port=port,
                            owner_candidates=scan.owners_by_cwd_type.get((cwd, service_type), ()),
                            port_lock_sessions=scan.port_lock_sessions_by_cwd_type.get((cwd, service_type), ()),
                        )
                    )
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
    port_planner: Any,
) -> set[int]:
    scan = restart_orphan_listener_scan(
        state,
        selected_services=selected_services,
        backend_port_base=backend_port_base,
        frontend_port_base=frontend_port_base,
        port_spacing=port_spacing,
    )
    if not scan.selected_by_cwd:
        return set()
    if not callable(listener_pids_for_port) or not callable(terminate_pid):
        return set()
    matches = restart_matching_orphan_listeners(
        scan,
        listener_pids_for_port=listener_pids_for_port,
        process_cwd=process_cwd,
    )
    failed_pids: set[int] = set()
    for match in matches:
        if terminate_pid(match.pid, term_timeout=0.5 if aggressive else 2.0, kill_timeout=1.0):
            expected_sessions = match.port_lock_sessions or (None,)
            for expected_session in expected_sessions:
                if release_port_reservation(
                    port_planner,
                    match.port,
                    owner_candidates=match.owner_candidates,
                    expected_session=expected_session,
                ):
                    break
        else:
            failed_pids.add(match.pid)
    return failed_pids


def terminate_restart_orphan_listeners_with_runtime(
    runtime: Any,
    *,
    state: Any,
    selected_services: set[str],
    aggressive: bool,
) -> set[int]:
    process_runtime = resolve_process_runtime(runtime)
    port_allocator = resolve_port_allocator(runtime)
    return terminate_restart_orphan_listeners(
        state=state,
        selected_services=selected_services,
        aggressive=aggressive,
        backend_port_base=int(runtime.config.backend_port_base),
        frontend_port_base=int(runtime.config.frontend_port_base),
        port_spacing=int(getattr(runtime.config, "port_spacing", 20) or 20),
        listener_pids_for_port=getattr(runtime, "_listener_pids_for_port", None),
        process_cwd=getattr(process_runtime, "process_cwd", process_cwd),
        terminate_pid=getattr(process_runtime, "terminate", None),
        port_planner=port_allocator,
    )
