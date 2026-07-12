from __future__ import annotations

import concurrent.futures
from contextlib import nullcontext
from dataclasses import replace
from typing import Any, Callable, cast

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.engine_runtime_env import effective_dependency_scope
from envctl_engine.startup.protocols import ProjectContextLike, StartupRuntime
from envctl_engine.startup.session import (
    ProjectStartupResult,
    StartupSession,
    track_startup_failure,
)
from envctl_engine.state.models import RequirementsResult, ServiceRecord
from envctl_engine.startup.startup_progress import suppress_progress_output as default_suppress_progress_output


def project_spinner_success_message(session: StartupSession, context: ProjectContextLike) -> str:
    dependency_scope = effective_dependency_scope(session.effective_route, session.runtime_mode)
    if session.runtime_mode == "trees" and dependency_scope == "shared":
        return f"startup completed ({_project_app_ports_text(context)})"
    return f"startup completed ({_project_ports_text(context)})"


def record_project_startup(
    session: StartupSession,
    context: ProjectContextLike,
    result: ProjectStartupResult,
) -> None:
    existing_service_names = set(session.preserved_services)
    existing_service_names.update(session.unterminated_services)
    for project_services in session.services_by_project.values():
        existing_service_names.update(project_services)
    collisions = sorted(existing_service_names.intersection(result.services))
    project_collision = (
        context.name in session.services_by_project
        or context.name in session.requirements_by_project
    )
    if collisions or project_collision:
        # The replacement processes are already live at this point. Give every
        # one a unique durable identity before raising so parallel projects and
        # preserved state can never overwrite one another during cleanup.
        preserved_collisions = set(session.preserved_services).intersection(collisions)
        session.preserve_existing_state_on_failure = bool(preserved_collisions)
        session.service_state_collisions.update(collisions)
        occupied_names = existing_service_names.union(result.services)
        for name, service in result.services.items():
            stored_name = name
            stored_service = (
                service
                if not isinstance(service, ServiceRecord) or service.project
                else replace(service, project=context.name)
            )
            if name in existing_service_names:
                stored_name = _unique_collision_service_name(name, service, occupied_names)
                occupied_names.add(stored_name)
                stored_service = replace(stored_service, name=stored_name)
                session.service_state_collision_rows.append(
                    {
                        "original_name": name,
                        "replacement_name": stored_name,
                        "replacement_pid": getattr(service, "pid", None),
                        "replacement_project": getattr(service, "project", None) or context.name,
                    }
                )
            session.unterminated_services[stored_name] = stored_service
        _record_collision_requirements(session, context.name, result.requirements)
        collision_labels = collisions or [f"project:{context.name}"]
        raise RuntimeError(
            "Refusing to overwrite preserved service state or tracked startup state "
            "with newly started services: "
            + ", ".join(collision_labels)
        )
    session.requirements_by_project[context.name] = result.requirements
    session.services_by_project[context.name] = {
        name: (
            service
            if not isinstance(service, ServiceRecord) or service.project
            else replace(service, project=context.name)
        )
        for name, service in result.services.items()
    }
    session.started_context_names.append(context.name)
    for warning in result.warnings:
        if "No local app system is configured" in warning:
            session.warnings.append(warning)


def _unique_collision_service_name(name: str, service: object, occupied: set[str]) -> str:
    pid = getattr(service, "pid", None)
    suffix = f"Restart Collision {pid}" if isinstance(pid, int) and pid > 0 else "Restart Collision"
    base = f"{name} {suffix}"
    candidate = base
    index = 2
    while candidate in occupied:
        candidate = f"{base} {index}"
        index += 1
    return candidate


def _record_collision_requirements(
    session: StartupSession,
    project: str,
    requirements: RequirementsResult,
) -> None:
    # A preserved requirement with the same storage key is remapped by the
    # failure finalizer, which can also record whether it remained managed.
    if project in session.preserved_requirements:
        session.requirements_by_project[project] = requirements
        return
    if project not in session.requirements_by_project:
        session.requirements_by_project[project] = requirements
        return
    occupied = set(session.preserved_requirements).union(session.requirements_by_project)
    base = f"{project} Restart Collision"
    storage_key = base
    index = 2
    while storage_key in occupied:
        storage_key = f"{base} {index}"
        index += 1
    session.requirements_by_project[storage_key] = requirements
    session.requirement_state_collision_rows.append(
        {
            "original_project": project,
            "replacement_project": storage_key,
            "replacement_requirements_retained": True,
        }
    )


class _UnrecordedProjectStartup(RuntimeError):
    """Adapter used to feed a returned startup result into failure tracking."""

    def __init__(
        self,
        *,
        project: str,
        requirements: RequirementsResult | None,
        services: dict[str, ServiceRecord],
    ) -> None:
        super().__init__(f"startup result for {project} was not committed to the session")
        self.project = project
        self.requirements = requirements
        self.unterminated_services = services


def _retain_unrecorded_project_startup(
    session: StartupSession,
    context: ProjectContextLike,
    result: ProjectStartupResult,
) -> None:
    """Retain every resource returned before a callback/cancellation failure.

    ``record_project_startup`` is normally the ownership handoff. A signal can
    arrive after project startup returns but before (or during) that handoff.
    Feed only resources that are not already represented in the session through
    the same collision-aware failure tracker used by lower startup layers.
    """

    tracked_requirements = [
        *session.preserved_requirements.values(),
        *session.requirements_by_project.values(),
    ]
    requirements = (
        None
        if any(existing is result.requirements for existing in tracked_requirements)
        else result.requirements
    )
    tracked_services = [
        *session.preserved_services.values(),
        *session.unterminated_services.values(),
        *(
            service
            for project_services in session.services_by_project.values()
            for service in project_services.values()
        ),
    ]
    untracked_services = {
        name: service
        for name, service in result.services.items()
        if isinstance(service, ServiceRecord)
        and not any(_same_runtime_service(service, existing) for existing in tracked_services)
    }
    if requirements is None and not untracked_services:
        return
    track_startup_failure(
        session,
        _UnrecordedProjectStartup(
            project=str(context.name),
            requirements=requirements,
            services=untracked_services,
        ),
    )


def _same_runtime_service(left: ServiceRecord, right: ServiceRecord) -> bool:
    if left is right:
        return True
    for attribute in ("container_launch_token", "container_id"):
        left_value = str(getattr(left, attribute, "") or "").strip()
        right_value = str(getattr(right, attribute, "") or "").strip()
        if left_value and left_value == right_value:
            return True
    left_pid = getattr(left, "pid", None)
    right_pid = getattr(right, "pid", None)
    return (
        isinstance(left_pid, int)
        and not isinstance(left_pid, bool)
        and left_pid > 0
        and left_pid == right_pid
    )


def _retain_unrecorded_project_startup_safely(
    session: StartupSession,
    context: ProjectContextLike,
    result: ProjectStartupResult,
    triggering_error: BaseException,
) -> None:
    try:
        _retain_unrecorded_project_startup(session, context, result)
    except BaseException as retention_error:  # noqa: BLE001 - never replace the triggering cancellation
        try:
            triggering_error.add_note(f"startup result retention also failed: {retention_error}")
        except Exception:  # noqa: BLE001
            pass


def start_selected_contexts(
    *,
    runtime: StartupRuntime,
    session: StartupSession,
    suppress_progress_output: Callable[[Route], bool],
    resolved_run_id: Callable[[StartupSession], str],
    record_project_startup: Callable[[StartupSession, ProjectContextLike, ProjectStartupResult], None],
    render_project_startup_warnings: Callable[..., None],
    should_degrade_to_plan_agent_handoff: Callable[[StartupSession, str], bool],
    record_plan_agent_handoff_local_startup_failure: Callable[..., None],
    spinner_factory: Callable[..., Any],
    use_spinner_policy_fn: Callable[[Any], Any],
    resolve_spinner_policy_fn: Callable[[dict[str, str]], Any],
    emit_spinner_policy_fn: Callable[..., None],
    project_spinner_group_factory: Callable[..., Any],
) -> None:
    route = session.effective_route
    spinner_message = f"Starting {len(session.contexts_to_start)} project(s)..."
    spinner_policy = resolve_spinner_policy_fn(dict(runtime.env))
    use_startup_spinner = bool(spinner_policy.enabled) and not suppress_progress_output(route)
    emit_spinner_policy_fn(
        runtime._emit,
        spinner_policy,
        context={"component": "startup_orchestrator", "op_id": "startup.execute"},
    )
    parallel_enabled, parallel_workers = runtime._tree_parallel_startup_config(
        mode=session.runtime_mode,
        route=route,
        project_count=len(session.contexts_to_start),
    )
    runtime._emit(
        "startup.execution",
        mode="parallel" if parallel_enabled else "sequential",
        workers=parallel_workers,
        projects=[context.name for context in session.contexts_to_start],
    )
    route_for_execution = _execution_route(runtime=runtime, session=session)
    use_project_spinner_group = (
        parallel_enabled
        and use_startup_spinner
        and len(session.selected_contexts) > 1
        and str(getattr(spinner_policy, "backend", "")) == "rich"
    )
    session.used_project_spinner_group = use_project_spinner_group
    project_spinner_group = project_spinner_group_factory(
        projects=[context.name for context in session.selected_contexts],
        enabled=use_project_spinner_group,
        policy=spinner_policy,
        emit=runtime._emit,
        component="startup_orchestrator",
        op_id="startup.execute",
        env=dict(runtime.env),
    )
    use_single_spinner = use_startup_spinner and not use_project_spinner_group
    group_context = project_spinner_group if use_project_spinner_group else nullcontext(project_spinner_group)

    with (
        use_spinner_policy_fn(spinner_policy),
        spinner_factory(spinner_message, enabled=use_single_spinner) as active_spinner,
    ):
        if use_single_spinner:
            route_for_execution.flags["_spinner_update"] = active_spinner.update
            runtime._emit(
                "ui.spinner.lifecycle",
                component="startup_orchestrator",
                op_id="startup.execute",
                state="start",
                message=spinner_message,
            )
        if use_project_spinner_group:
            route_for_execution.flags["_spinner_update_project"] = project_spinner_group.update_project
        try:
            with group_context:
                _mark_resumed_contexts(
                    session=session,
                    project_spinner_group=project_spinner_group,
                    enabled=use_project_spinner_group,
                )
                if parallel_enabled:
                    _start_contexts_parallel(
                        runtime=runtime,
                        session=session,
                        route_for_execution=route_for_execution,
                        resolved_run_id=resolved_run_id,
                        record_project_startup=record_project_startup,
                        render_project_startup_warnings=render_project_startup_warnings,
                        should_degrade_to_plan_agent_handoff=should_degrade_to_plan_agent_handoff,
                        record_plan_agent_handoff_local_startup_failure=record_plan_agent_handoff_local_startup_failure,
                        parallel_workers=parallel_workers,
                        active_spinner=active_spinner,
                        use_single_spinner=use_single_spinner,
                        project_spinner_group=project_spinner_group,
                        use_project_spinner_group=use_project_spinner_group,
                    )
                else:
                    _start_contexts_sequential(
                        runtime=runtime,
                        session=session,
                        route_for_execution=route_for_execution,
                        resolved_run_id=resolved_run_id,
                        record_project_startup=record_project_startup,
                        render_project_startup_warnings=render_project_startup_warnings,
                        should_degrade_to_plan_agent_handoff=should_degrade_to_plan_agent_handoff,
                        record_plan_agent_handoff_local_startup_failure=record_plan_agent_handoff_local_startup_failure,
                        project_spinner_group=project_spinner_group,
                        use_project_spinner_group=use_project_spinner_group,
                    )
        except BaseException:
            try:
                _fail_single_spinner(runtime=runtime, active_spinner=active_spinner, enabled=use_single_spinner)
            except BaseException:  # noqa: BLE001 - presentation must not mask cancellation
                pass
            raise
        _succeed_single_spinner(
            runtime=runtime,
            session=session,
            active_spinner=active_spinner,
            enabled=use_single_spinner,
        )


def start_selected_contexts_with_runtime(
    runtime: StartupRuntime,
    session: StartupSession,
    *,
    resolved_run_id: Callable[[StartupSession], str],
    render_project_startup_warnings: Callable[..., None],
    should_degrade_to_plan_agent_handoff: Callable[[StartupSession, str], bool],
    record_plan_agent_handoff_local_startup_failure: Callable[..., None],
    spinner_factory: Callable[..., Any],
    use_spinner_policy_fn: Callable[[Any], Any],
    resolve_spinner_policy_fn: Callable[[dict[str, str]], Any],
    emit_spinner_policy_fn: Callable[..., None],
    project_spinner_group_factory: Callable[..., Any],
    suppress_progress_output: Callable[[Route], bool] = default_suppress_progress_output,
) -> None:
    start_selected_contexts(
        runtime=runtime,
        session=session,
        suppress_progress_output=suppress_progress_output,
        resolved_run_id=resolved_run_id,
        record_project_startup=record_project_startup,
        render_project_startup_warnings=render_project_startup_warnings,
        should_degrade_to_plan_agent_handoff=should_degrade_to_plan_agent_handoff,
        record_plan_agent_handoff_local_startup_failure=record_plan_agent_handoff_local_startup_failure,
        spinner_factory=spinner_factory,
        use_spinner_policy_fn=use_spinner_policy_fn,
        resolve_spinner_policy_fn=resolve_spinner_policy_fn,
        emit_spinner_policy_fn=emit_spinner_policy_fn,
        project_spinner_group_factory=project_spinner_group_factory,
    )


def _execution_route(*, runtime: StartupRuntime, session: StartupSession) -> Route:
    route = session.effective_route
    debug_suppress_plan_progress = bool(
        session.requested_command == "plan"
        and str(runtime.env.get("ENVCTL_DEBUG_SUPPRESS_PLAN_PROGRESS", "")).strip().lower()
        in {"1", "true", "yes", "on"}
    )
    return Route(
        command=route.command,
        mode=route.mode,
        raw_args=route.raw_args,
        passthrough_args=route.passthrough_args,
        projects=route.projects,
        flags={
            **route.flags,
            "_spinner_update": None,
            "_spinner_update_project": None,
            "debug_suppress_progress_output": debug_suppress_plan_progress,
        },
    )


def _mark_resumed_contexts(*, session: StartupSession, project_spinner_group: Any, enabled: bool) -> None:
    if not enabled:
        return
    for project_name in session.resumed_context_names:
        project_spinner_group.mark_success(project_name, "restored")


def _start_contexts_parallel(
    *,
    runtime: StartupRuntime,
    session: StartupSession,
    route_for_execution: Route,
    resolved_run_id: Callable[[StartupSession], str],
    record_project_startup: Callable[[StartupSession, ProjectContextLike, ProjectStartupResult], None],
    render_project_startup_warnings: Callable[..., None],
    should_degrade_to_plan_agent_handoff: Callable[[StartupSession, str], bool],
    record_plan_agent_handoff_local_startup_failure: Callable[..., None],
    parallel_workers: int,
    active_spinner: Any,
    use_single_spinner: bool,
    project_spinner_group: Any,
    use_project_spinner_group: bool,
) -> None:
    completed: dict[str, ProjectStartupResult] = {}
    failures: list[str] = []
    ui_failures: list[Exception] = []
    future_map: dict[concurrent.futures.Future[Any], ProjectContextLike] = {}
    try:
        # Let the executor context finish its wait before handling a main-thread
        # cancellation. Once control reaches the outer handler, every submitted
        # worker has a terminal result that can be transferred to the session.
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_workers) as executor:
            for context in session.contexts_to_start:
                future = executor.submit(
                    runtime._start_project_context,
                    context=context,
                    mode=session.runtime_mode,
                    route=route_for_execution,
                    run_id=resolved_run_id(session),
                )
                future_map[future] = context
            for future in concurrent.futures.as_completed(future_map):
                context = future_map[future]
                try:
                    result = cast(ProjectStartupResult, future.result())
                except RuntimeError as exc:
                    track_startup_failure(session, exc)
                    try:
                        degrade = should_degrade_to_plan_agent_handoff(session, str(exc))
                    except Exception as callback_exc:  # noqa: BLE001
                        ui_failures.append(callback_exc)
                        degrade = False
                    if degrade:
                        try:
                            record_plan_agent_handoff_local_startup_failure(
                                session,
                                project_name=context.name,
                                error=str(exc),
                            )
                            if use_project_spinner_group:
                                project_spinner_group.mark_success(
                                    context.name,
                                    "AI session running; local startup failed",
                                )
                        except Exception as callback_exc:  # noqa: BLE001
                            ui_failures.append(callback_exc)
                        continue
                    failures.append(str(exc))
                    try:
                        runtime._emit("startup.project.failed", project=context.name, error=str(exc))
                        if use_project_spinner_group:
                            project_spinner_group.mark_failure(context.name, str(exc))
                    except Exception as callback_exc:  # noqa: BLE001
                        ui_failures.append(callback_exc)
                    continue
                except Exception as exc:  # noqa: BLE001
                    track_startup_failure(session, exc)
                    failures.append(str(exc))
                    try:
                        runtime._emit("startup.project.failed", project=context.name, error=str(exc))
                        if use_project_spinner_group:
                            project_spinner_group.mark_failure(context.name, str(exc))
                    except Exception as callback_exc:  # noqa: BLE001
                        ui_failures.append(callback_exc)
                    continue

                try:
                    record_project_startup(session, context, result)
                except Exception as exc:  # noqa: BLE001
                    _retain_unrecorded_project_startup_safely(session, context, result, exc)
                    track_startup_failure(session, exc)
                    failures.append(str(exc))
                    try:
                        runtime._emit("startup.project.failed", project=context.name, error=str(exc))
                        if use_project_spinner_group:
                            project_spinner_group.mark_failure(context.name, str(exc))
                    except Exception as callback_exc:  # noqa: BLE001
                        ui_failures.append(callback_exc)
                    # Keep draining the executor. Other futures may already have
                    # launched resources that must be recorded for final cleanup.
                    continue
                completed[context.name] = result
                try:
                    _record_parallel_success(
                        runtime=runtime,
                        session=session,
                        context=context,
                        result=result,
                        route_for_execution=route_for_execution,
                        render_project_startup_warnings=render_project_startup_warnings,
                        active_spinner=active_spinner,
                        use_single_spinner=use_single_spinner,
                        project_spinner_group=project_spinner_group,
                        use_project_spinner_group=use_project_spinner_group,
                        completed_count=len(completed),
                    )
                except Exception as exc:  # noqa: BLE001
                    ui_failures.append(exc)
    except BaseException as exc:  # noqa: BLE001 - cancellation requires a complete ownership drain
        _drain_parallel_startup_futures(
            session=session,
            future_map=future_map,
            triggering_error=exc,
        )
        raise
    if failures:
        raise RuntimeError("; ".join(failures))
    if ui_failures:
        raise ui_failures[0]


def _drain_parallel_startup_futures(
    *,
    session: StartupSession,
    future_map: dict[concurrent.futures.Future[Any], ProjectContextLike],
    triggering_error: BaseException,
) -> None:
    """Transfer every completed worker result after a main-thread interruption."""

    for future, context in future_map.items():
        try:
            result = cast(ProjectStartupResult, future.result())
        except BaseException as worker_error:  # noqa: BLE001 - retain any failure-owned resources
            try:
                track_startup_failure(session, worker_error)
            except BaseException as retention_error:  # noqa: BLE001
                try:
                    triggering_error.add_note(
                        f"startup failure retention also failed for {context.name}: {retention_error}"
                    )
                except Exception:  # noqa: BLE001
                    pass
            continue
        _retain_unrecorded_project_startup_safely(
            session,
            context,
            result,
            triggering_error,
        )


def _record_parallel_success(
    *,
    runtime: StartupRuntime,
    session: StartupSession,
    context: ProjectContextLike,
    result: ProjectStartupResult,
    route_for_execution: Route,
    render_project_startup_warnings: Callable[..., None],
    active_spinner: Any,
    use_single_spinner: bool,
    project_spinner_group: Any,
    use_project_spinner_group: bool,
    completed_count: int,
) -> None:
    if use_single_spinner:
        done = len(session.resumed_context_names) + completed_count
        progress_message = f"Started {done}/{len(session.selected_contexts)} project(s)..."
        active_spinner.update(progress_message)
        runtime._emit(
            "ui.spinner.lifecycle",
            component="startup_orchestrator",
            op_id="startup.execute",
            state="update",
            message=progress_message,
        )
    if use_project_spinner_group:
        project_spinner_group.mark_success(context.name, project_spinner_success_message(session, context))
    render_project_startup_warnings(
        context=context,
        warnings=result.warnings,
        route=route_for_execution,
        project_spinner_group=project_spinner_group if use_project_spinner_group else None,
    )


def _start_contexts_sequential(
    *,
    runtime: StartupRuntime,
    session: StartupSession,
    route_for_execution: Route,
    resolved_run_id: Callable[[StartupSession], str],
    record_project_startup: Callable[[StartupSession, ProjectContextLike, ProjectStartupResult], None],
    render_project_startup_warnings: Callable[..., None],
    should_degrade_to_plan_agent_handoff: Callable[[StartupSession, str], bool],
    record_plan_agent_handoff_local_startup_failure: Callable[..., None],
    project_spinner_group: Any,
    use_project_spinner_group: bool,
) -> None:
    for context in session.contexts_to_start:
        try:
            result = cast(
                ProjectStartupResult,
                runtime._start_project_context(
                    context=context,
                    mode=session.runtime_mode,
                    route=route_for_execution,
                    run_id=resolved_run_id(session),
                ),
            )
        except RuntimeError as exc:
            track_startup_failure(session, exc)
            if should_degrade_to_plan_agent_handoff(session, str(exc)):
                record_plan_agent_handoff_local_startup_failure(session, project_name=context.name, error=str(exc))
                if use_project_spinner_group:
                    project_spinner_group.mark_success(context.name, "AI session running; local startup failed")
                continue
            raise
        except BaseException as exc:  # noqa: BLE001 - persist failure-owned resources before propagation
            track_startup_failure(session, exc)
            raise
        try:
            record_project_startup(session, context, result)
        except BaseException as exc:  # noqa: BLE001 - result may already own live resources
            _retain_unrecorded_project_startup_safely(session, context, result, exc)
            track_startup_failure(session, exc)
            raise
        render_project_startup_warnings(
            context=context,
            warnings=result.warnings,
            route=route_for_execution,
            project_spinner_group=project_spinner_group if use_project_spinner_group else None,
        )


def _fail_single_spinner(*, runtime: StartupRuntime, active_spinner: Any, enabled: bool) -> None:
    if not enabled:
        return
    active_spinner.fail("Startup failed")
    runtime._emit(
        "ui.spinner.lifecycle",
        component="startup_orchestrator",
        op_id="startup.execute",
        state="fail",
        message="Startup failed",
    )
    runtime._emit(
        "ui.spinner.lifecycle",
        component="startup_orchestrator",
        op_id="startup.execute",
        state="stop",
    )


def _succeed_single_spinner(
    *, runtime: StartupRuntime, session: StartupSession, active_spinner: Any, enabled: bool
) -> None:
    if not enabled:
        return
    success_message = (
        "AI session running; local startup failed" if session.plan_agent_handoff_degraded else "Startup complete"
    )
    active_spinner.succeed(success_message)
    runtime._emit(
        "ui.spinner.lifecycle",
        component="startup_orchestrator",
        op_id="startup.execute",
        state="success",
        message=success_message,
    )
    runtime._emit(
        "ui.spinner.lifecycle",
        component="startup_orchestrator",
        op_id="startup.execute",
        state="stop",
    )


def _project_ports_text(context: ProjectContextLike) -> str:
    return (
        f"backend={context.ports['backend'].final} "
        f"frontend={context.ports['frontend'].final} "
        f"db={context.ports['db'].final} "
        f"redis={context.ports['redis'].final} "
        f"n8n={context.ports['n8n'].final}"
    )


def _project_app_ports_text(context: ProjectContextLike) -> str:
    return f"backend={context.ports['backend'].final} frontend={context.ports['frontend'].final}"
