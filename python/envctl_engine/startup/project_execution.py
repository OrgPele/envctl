from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
from contextlib import nullcontext
from typing import cast

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.session import ProjectStartupResult
from envctl_engine.startup.session import StartupSession


def execute_project_startup_plan(
    orchestrator: object,
    session: StartupSession,
    *,
    project_spinner_group_factory: Callable[..., object],
    resolve_spinner_policy_fn: Callable[..., object],
    emit_spinner_policy_fn: Callable[..., None],
    use_spinner_policy_fn: Callable[..., object],
    spinner_factory: Callable[..., object],
    project_success_message_fn: Callable[..., str],
) -> None:
    rt = orchestrator.runtime
    route = session.effective_route
    spinner_message = f"Starting {len(session.contexts_to_start)} project(s)..."
    spinner_policy = resolve_spinner_policy_fn(dict(rt.env))
    use_startup_spinner = spinner_policy.enabled and not orchestrator._suppress_progress_output(route)
    emit_spinner_policy_fn(
        rt._emit,
        spinner_policy,
        context={"component": "startup_orchestrator", "op_id": "startup.execute"},
    )
    parallel_enabled, parallel_workers = rt._tree_parallel_startup_config(
        mode=session.runtime_mode,
        route=route,
        project_count=len(session.contexts_to_start),
    )
    rt._emit(
        "startup.execution",
        mode="parallel" if parallel_enabled else "sequential",
        workers=parallel_workers,
        projects=[context.name for context in session.contexts_to_start],
    )
    debug_suppress_plan_progress = bool(
        session.requested_command == "plan"
        and str(rt.env.get("ENVCTL_DEBUG_SUPPRESS_PLAN_PROGRESS", "")).strip().lower()
        in {"1", "true", "yes", "on"}
    )
    route_for_execution = Route(
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
        emit=rt._emit,
        component="startup_orchestrator",
        op_id="startup.execute",
        env=dict(rt.env),
    )
    use_single_spinner = use_startup_spinner and not use_project_spinner_group
    group_context = project_spinner_group if use_project_spinner_group else nullcontext(project_spinner_group)

    with (
        use_spinner_policy_fn(spinner_policy),
        spinner_factory(spinner_message, enabled=use_single_spinner) as active_spinner,
    ):
        if use_single_spinner:
            route_for_execution.flags["_spinner_update"] = active_spinner.update
            rt._emit(
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
                if use_project_spinner_group and session.resumed_context_names:
                    for project_name in session.resumed_context_names:
                        project_spinner_group.mark_success(project_name, "restored")
                if parallel_enabled:
                    _execute_parallel_project_startup(
                        orchestrator,
                        session,
                        route_for_execution=route_for_execution,
                        active_spinner=active_spinner,
                        project_spinner_group=project_spinner_group,
                        use_single_spinner=use_single_spinner,
                        use_project_spinner_group=use_project_spinner_group,
                        project_success_message_fn=project_success_message_fn,
                        parallel_workers=parallel_workers,
                    )
                else:
                    _execute_sequential_project_startup(
                        orchestrator,
                        session,
                        route_for_execution=route_for_execution,
                        project_spinner_group=project_spinner_group,
                        use_project_spinner_group=use_project_spinner_group,
                    )
        except RuntimeError:
            if use_single_spinner:
                active_spinner.fail("Startup failed")
                rt._emit(
                    "ui.spinner.lifecycle",
                    component="startup_orchestrator",
                    op_id="startup.execute",
                    state="fail",
                    message="Startup failed",
                )
                rt._emit(
                    "ui.spinner.lifecycle",
                    component="startup_orchestrator",
                    op_id="startup.execute",
                    state="stop",
                )
            raise
        if use_single_spinner:
            success_message = (
                "AI session running; local startup failed"
                if session.plan_agent_handoff_degraded
                else "Startup complete"
            )
            active_spinner.succeed(success_message)
            rt._emit(
                "ui.spinner.lifecycle",
                component="startup_orchestrator",
                op_id="startup.execute",
                state="success",
                message=success_message,
            )
            rt._emit(
                "ui.spinner.lifecycle",
                component="startup_orchestrator",
                op_id="startup.execute",
                state="stop",
            )


def _execute_parallel_project_startup(
    orchestrator: object,
    session: StartupSession,
    *,
    route_for_execution: Route,
    active_spinner: object,
    project_spinner_group: object,
    use_single_spinner: bool,
    use_project_spinner_group: bool,
    project_success_message_fn: Callable[..., str],
    parallel_workers: int,
) -> None:
    rt = orchestrator.runtime
    completed: dict[str, ProjectStartupResult] = {}
    failures: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_workers) as executor:
        future_map = {
            executor.submit(
                rt._start_project_context,
                context=context,
                mode=session.runtime_mode,
                route=route_for_execution,
                run_id=orchestrator._resolved_run_id(session),
            ): context
            for context in session.contexts_to_start
        }
        for future in concurrent.futures.as_completed(future_map):
            context = future_map[future]
            try:
                result = cast(ProjectStartupResult, future.result())
                completed[context.name] = result
                if use_single_spinner:
                    done = len(session.resumed_context_names) + len(completed)
                    progress_message = f"Started {done}/{len(session.selected_contexts)} project(s)..."
                    active_spinner.update(progress_message)
                    rt._emit(
                        "ui.spinner.lifecycle",
                        component="startup_orchestrator",
                        op_id="startup.execute",
                        state="update",
                        message=progress_message,
                    )
                if use_project_spinner_group:
                    project_spinner_group.mark_success(
                        context.name,
                        project_success_message_fn(session, context),
                    )
                orchestrator._render_project_startup_warnings(
                    context=context,
                    warnings=result.warnings,
                    route=route_for_execution,
                    project_spinner_group=project_spinner_group if use_project_spinner_group else None,
                )
            except RuntimeError as exc:
                if orchestrator._should_degrade_to_plan_agent_handoff(session, error=str(exc)):
                    orchestrator._record_plan_agent_handoff_local_startup_failure(
                        session,
                        project_name=context.name,
                        error=str(exc),
                    )
                    if use_project_spinner_group:
                        project_spinner_group.mark_success(
                            context.name,
                            "AI session running; local startup failed",
                        )
                    continue
                failures.append(str(exc))
                rt._emit("startup.project.failed", project=context.name, error=str(exc))
                if use_project_spinner_group:
                    project_spinner_group.mark_failure(context.name, str(exc))
    for context in session.contexts_to_start:
        result = completed.get(context.name)
        if result is None:
            continue
        orchestrator._record_project_startup(session, context, result)
    if failures:
        raise RuntimeError("; ".join(failures))


def _execute_sequential_project_startup(
    orchestrator: object,
    session: StartupSession,
    *,
    route_for_execution: Route,
    project_spinner_group: object,
    use_project_spinner_group: bool,
) -> None:
    rt = orchestrator.runtime
    for context in session.contexts_to_start:
        try:
            result = cast(
                ProjectStartupResult,
                rt._start_project_context(
                    context=context,
                    mode=session.runtime_mode,
                    route=route_for_execution,
                    run_id=orchestrator._resolved_run_id(session),
                ),
            )
        except RuntimeError as exc:
            if orchestrator._should_degrade_to_plan_agent_handoff(session, error=str(exc)):
                orchestrator._record_plan_agent_handoff_local_startup_failure(
                    session,
                    project_name=context.name,
                    error=str(exc),
                )
                if use_project_spinner_group:
                    project_spinner_group.mark_success(
                        context.name,
                        "AI session running; local startup failed",
                    )
                continue
            raise
        orchestrator._record_project_startup(session, context, result)
        orchestrator._render_project_startup_warnings(
            context=context,
            warnings=result.warnings,
            route=route_for_execution,
            project_spinner_group=project_spinner_group if use_project_spinner_group else None,
        )
