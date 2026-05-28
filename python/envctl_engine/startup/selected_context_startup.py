from __future__ import annotations

import concurrent.futures
from contextlib import nullcontext
from typing import Any, Callable, cast

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.engine_runtime_env import effective_dependency_scope
from envctl_engine.startup.protocols import ProjectContextLike, StartupRuntime
from envctl_engine.startup.session import ProjectStartupResult, StartupSession
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
    session.requirements_by_project[context.name] = result.requirements
    session.services_by_project[context.name] = result.services
    session.started_context_names.append(context.name)


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
    if not session.contexts_to_start:
        return
    spinner_message = f"Starting {len(session.contexts_to_start)} project(s)..."
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
        except RuntimeError:
            _fail_single_spinner(runtime=runtime, active_spinner=active_spinner, enabled=use_single_spinner)
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
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_workers) as executor:
        future_map = {
            executor.submit(
                runtime._start_project_context,
                context=context,
                mode=session.runtime_mode,
                route=route_for_execution,
                run_id=resolved_run_id(session),
            ): context
            for context in session.contexts_to_start
        }
        for future in concurrent.futures.as_completed(future_map):
            context = future_map[future]
            try:
                result = cast(ProjectStartupResult, future.result())
                completed[context.name] = result
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
            except RuntimeError as exc:
                if should_degrade_to_plan_agent_handoff(session, str(exc)):
                    record_plan_agent_handoff_local_startup_failure(session, project_name=context.name, error=str(exc))
                    if use_project_spinner_group:
                        project_spinner_group.mark_success(context.name, "AI session running; local startup failed")
                    continue
                failures.append(str(exc))
                runtime._emit("startup.project.failed", project=context.name, error=str(exc))
                if use_project_spinner_group:
                    project_spinner_group.mark_failure(context.name, str(exc))
    for context in session.contexts_to_start:
        result = completed.get(context.name)
        if result is not None:
            record_project_startup(session, context, result)
    if failures:
        raise RuntimeError("; ".join(failures))


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
            if should_degrade_to_plan_agent_handoff(session, str(exc)):
                record_plan_agent_handoff_local_startup_failure(session, project_name=context.name, error=str(exc))
                if use_project_spinner_group:
                    project_spinner_group.mark_success(context.name, "AI session running; local startup failed")
                continue
            raise
        record_project_startup(session, context, result)
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
