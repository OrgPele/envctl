from __future__ import annotations

import concurrent.futures
from contextlib import nullcontext
import threading
import time
from typing import Any

from envctl_engine.runtime.command_router import MODE_TREE_TOKENS, Route
from envctl_engine.runtime.engine_runtime_env import _route_is_implicit_start
from envctl_engine.state.models import RequirementsResult, RunState
from envctl_engine.startup.startup_progress import (
    ProjectSpinnerGroup,
    report_progress,
    suppress_progress_output,
    suppress_timing_output,
)
from envctl_engine.startup.startup_selection_support import (
    _port_allocator as _port_allocator_impl,
    _process_runtime as _process_runtime_impl,
    _project_ports_text as _project_ports_text_impl,
    _restart_include_requirements as _restart_include_requirements_impl,
    _restart_selected_services as _restart_selected_services_impl,
    _restart_service_types_for_project as _restart_service_types_for_project_impl,
    _restart_target_projects as _restart_target_projects_impl,
    _restart_target_projects_for_selected_services as _restart_target_projects_for_selected_services_impl,
    _select_start_tree_projects as _select_start_tree_projects_impl,
    _state_matches_selected_projects as _state_matches_selected_projects_impl,
    _state_covers_selected_projects as _state_covers_selected_projects_impl,
    _state_project_names as _state_project_names_impl,
    _trees_start_selection_required as _trees_start_selection_required_impl,
)
from envctl_engine.startup.startup_execution_support import (
    _maybe_prewarm_docker as _maybe_prewarm_docker_impl,
    _requirements_for_restart_context as _requirements_for_restart_context_impl,
    _requirements_timing_enabled as _requirements_timing_enabled_impl,
    _startup_breakdown_enabled as _startup_breakdown_enabled_impl,
    print_startup_summary as print_startup_summary_impl,
    start_project_context as start_project_context_impl,
    start_project_services as start_project_services_impl,
    start_requirements_for_project as start_requirements_for_project_impl,
)
from envctl_engine.ui.debug_snapshot import emit_plan_handoff_snapshot, snapshot_enabled
from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy

_MODE_TREE_TOKENS_NORMALIZED = {str(token).strip().lower() for token in MODE_TREE_TOKENS}
_ProjectSpinnerGroup = ProjectSpinnerGroup


class StartupOrchestrator:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self._progress_lock = threading.Lock()
        self._last_progress_message_by_project: dict[str | None, str] = {}

    def execute(self, route: Route) -> int:
        rt: Any = self.runtime
        port_allocator = _port_allocator_impl(rt)
        requested_command = route.command
        startup_started_at = time.monotonic()
        startup_event_index = len(getattr(rt, "events", []))
        debug_plan_snapshot = snapshot_enabled(getattr(rt, "env", {}))
        preserved_services: dict[str, Any] = {}
        preserved_requirements: dict[str, RequirementsResult] = {}
        initial_runtime_mode = rt._effective_start_mode(route)
        hook_contract_issue = rt._startup_hook_contract_issue()
        if hook_contract_issue:
            print(hook_contract_issue)
            return 1
        try:
            rt._validate_mode_toggles(initial_runtime_mode, route=route)
        except RuntimeError as exc:
            print(str(exc))
            return 1
        if route.command == "restart":
            restart_lookup_mode = rt._effective_start_mode(route)
            resumed = rt._try_load_existing_state(mode=restart_lookup_mode)
            if resumed is not None and resumed.mode != restart_lookup_mode:
                rt._emit(
                    "restart.state_mode_mismatch",
                    requested_mode=restart_lookup_mode,
                    loaded_mode=resumed.mode,
                    run_id=resumed.run_id,
                )
                resumed = None
            if resumed is not None:
                selected_services = _restart_selected_services_impl(state=resumed, route=route)
                target_projects = _restart_target_projects_impl(state=resumed, route=route, runtime=rt)
                include_requirements = self._restart_include_requirements(route)
                if include_requirements and not target_projects:
                    target_projects = _restart_target_projects_for_selected_services_impl(
                        selected_services=selected_services,
                        state=resumed,
                        runtime=rt,
                    )
                rt._emit(
                    "restart.selection",
                    include_requirements=include_requirements,
                    target_projects=sorted(target_projects),
                    selected_services=sorted(selected_services),
                )
                prestop_policy = resolve_spinner_policy(getattr(rt, "env", {}))
                use_prestop_spinner = prestop_policy.enabled and not self._suppress_progress_output(route)
                emit_spinner_policy(
                    getattr(rt, "_emit", None),
                    prestop_policy,
                    context={"component": "startup_orchestrator", "op_id": "restart.prestop"},
                )
                with (
                    use_spinner_policy(prestop_policy),
                    spinner(
                        "Restarting services...",
                        enabled=use_prestop_spinner,
                    ) as prestop_spinner,
                ):
                    if use_prestop_spinner:
                        rt._emit(  # type: ignore[attr-defined]
                            "ui.spinner.lifecycle",
                            component="startup_orchestrator",
                            op_id="restart.prestop",
                            state="start",
                            message="Restarting services...",
                        )
                    try:
                        rt._terminate_services_from_state(
                            resumed,
                            selected_services=selected_services,
                            aggressive=False,
                            verify_ownership=True,
                        )
                        for project_name, requirements in resumed.requirements.items():
                            if include_requirements and (not target_projects or project_name in target_projects):
                                rt._release_requirement_ports(requirements)
                            else:
                                preserved_requirements[project_name] = requirements
                        preserved_services = {
                            name: service for name, service in resumed.services.items() if name not in selected_services
                        }
                        if use_prestop_spinner:
                            prestop_spinner.succeed("Restart pre-stop complete")
                            rt._emit(  # type: ignore[attr-defined]
                                "ui.spinner.lifecycle",
                                component="startup_orchestrator",
                                op_id="restart.prestop",
                                state="success",
                                message="Restart pre-stop complete",
                            )
                    except Exception:
                        if use_prestop_spinner:
                            prestop_spinner.fail("Restart pre-stop failed")
                            rt._emit(  # type: ignore[attr-defined]
                                "ui.spinner.lifecycle",
                                component="startup_orchestrator",
                                op_id="restart.prestop",
                                state="fail",
                                message="Restart pre-stop failed",
                            )
                        raise
                    finally:
                        if use_prestop_spinner:
                            rt._emit(  # type: ignore[attr-defined]
                                "ui.spinner.lifecycle",
                                component="startup_orchestrator",
                                op_id="restart.prestop",
                                state="stop",
                            )
                route = Route(
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

        runtime_mode = rt._effective_start_mode(route)
        reset_startup_warnings = getattr(rt, "_reset_project_startup_warnings", None)
        if callable(reset_startup_warnings):
            reset_startup_warnings()

        def emit_phase(phase: str, started_at: float, **extra: object) -> None:
            rt._emit(
                "startup.phase",
                command=requested_command,
                mode=runtime_mode,
                phase=phase,
                duration_ms=round((time.monotonic() - started_at) * 1000.0, 2),
                **extra,
            )

        def emit_snapshot(checkpoint: str, **extra: object) -> None:
            if not debug_plan_snapshot:
                return
            emit_plan_handoff_snapshot(
                getattr(rt, "_emit", None),
                env=getattr(rt, "env", {}),
                checkpoint=checkpoint,
                extra=extra or None,
            )

        budget_started = time.monotonic()
        if not rt._enforce_runtime_readiness_contract(scope=requested_command):
            emit_phase("runtime_readiness_gate", budget_started, status="blocked")
            print("Startup blocked: strict runtime readiness gate is incomplete.")
            return 1
        emit_phase("runtime_readiness_gate", budget_started, status="ok")

        run_id = rt._new_run_id()
        print(f"run_id: {run_id}")
        print(f"session_id: {rt._current_session_id() or 'unknown'}")

        selection_started = time.monotonic()
        project_contexts = rt._discover_projects(mode=runtime_mode)
        if route.command == "plan":
            project_contexts = rt._select_plan_projects(route, project_contexts)
        elif self._trees_start_selection_required(route=route, runtime_mode=runtime_mode):
            project_contexts = self._select_start_tree_projects(route=route, project_contexts=project_contexts)
        else:
            try:
                project_contexts = rt._apply_setup_worktree_selection(route, project_contexts)
            except RuntimeError as exc:
                print(str(exc))
                return 1
        if route.projects:
            allow = {project.lower() for project in route.projects}
            project_contexts = [ctx for ctx in project_contexts if ctx.name.lower() in allow]
        duplicate_error = rt._duplicate_project_context_error(project_contexts)
        if duplicate_error:
            emit_phase("project_selection", selection_started, status="error")
            print(duplicate_error)
            rt._emit("planning.projects.duplicate", error=duplicate_error)
            return 1
        emit_phase(
            "project_selection",
            selection_started,
            status="ok",
            project_count=len(project_contexts),
        )
        emit_snapshot(
            "plan_selector_exit",
            command=route.command,
            mode=runtime_mode,
            project_count=len(project_contexts),
            projects=[context.name for context in project_contexts],
        )
        if not project_contexts:
            if self._trees_start_selection_required(route=route, runtime_mode=runtime_mode):
                print("No worktrees selected.")
            else:
                print("No projects discovered for selected mode.")
            return 1

        selected_project_contexts = list(project_contexts)
        project_contexts_to_start = list(selected_project_contexts)
        restored_project_names: list[str] = []

        mode_runs_enabled = (
            rt.config.startup_enabled_for_mode(runtime_mode) if hasattr(rt.config, "startup_enabled_for_mode") else True
        )
        allow_disabled_dashboard = not mode_runs_enabled and (
            route.command == "plan" or _route_is_implicit_start(route)
        )
        if allow_disabled_dashboard:
            run_state = self._build_planning_dashboard_state(
                route=route,
                runtime_mode=runtime_mode,
                run_id=run_id,
                project_contexts=selected_project_contexts,
            )
            artifacts_started = time.monotonic()
            rt._write_artifacts(run_state, selected_project_contexts, errors=[])
            emit_phase("artifacts_write", artifacts_started, status="ok")
            enter_interactive_dashboard = rt._should_enter_post_start_interactive(route)
            if route.command == "plan":
                print(
                    f"Planning mode complete; skipping service startup because envctl runs are disabled for {runtime_mode}."
                )
            elif not enter_interactive_dashboard:
                print(f"envctl runs are disabled for {runtime_mode}; opening dashboard without starting services.")
            if enter_interactive_dashboard:
                return rt._run_interactive_dashboard_loop(run_state)
            return 0

        debug_orch_groups: set[str] = set()
        if requested_command == "plan":
            raw_orch_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_ORCH_GROUP", "")).strip().lower()
            debug_orch_groups = {
                token.strip() for token in raw_orch_group.replace("+", ",").split(",") if token.strip()
            }
        if requested_command != "restart" and mode_runs_enabled and rt._auto_resume_start_enabled(route):
            auto_resume_started = time.monotonic()
            existing_state = rt._load_auto_resume_state(runtime_mode)
            if existing_state is not None:
                selected_project_names = {
                    str(context.name).strip()
                    for context in selected_project_contexts
                    if str(getattr(context, "name", "")).strip()
                }
                state_project_names = _state_project_names_impl(runtime=rt, state=existing_state)
                exact_match = _state_matches_selected_projects_impl(
                    self,
                    runtime=rt,
                    state=existing_state,
                    contexts=selected_project_contexts,
                )
                subset_match = (
                    not exact_match
                    and runtime_mode == "trees"
                    and _state_covers_selected_projects_impl(
                        self,
                        runtime=rt,
                        state=existing_state,
                        contexts=selected_project_contexts,
                    )
                )
                expand_match = (
                    not exact_match
                    and not subset_match
                    and runtime_mode == "trees"
                    and route.command == "plan"
                    and bool(state_project_names)
                    and state_project_names.issubset(selected_project_names)
                )
                if exact_match or subset_match:
                    emit_phase(
                        "auto_resume_evaluate",
                        auto_resume_started,
                        status="resume",
                        match_mode="exact" if exact_match else "subset",
                        state_project_count=len(state_project_names),
                        selected_project_count=len(selected_project_contexts),
                    )
                    rt._emit(
                        "state.auto_resume",
                        run_id=existing_state.run_id,
                        mode=runtime_mode,
                        command=route.command,
                        match_mode="exact" if exact_match else "subset",
                        selected_projects=sorted(selected_project_names),
                    )
                    resume_route = Route(
                        command="resume",
                        mode=runtime_mode,
                        raw_args=route.raw_args,
                        passthrough_args=route.passthrough_args,
                        projects=route.projects,
                        flags={
                            **route.flags,
                            "_resume_source_command": route.command,
                        },
                    )
                    return rt._resume(resume_route)
                if expand_match:
                    missing_services = rt._reconcile_state_truth(existing_state)
                    if not missing_services:
                        restored_project_names = sorted(state_project_names)
                        preserved_services = dict(existing_state.services)
                        preserved_requirements = dict(existing_state.requirements)
                        project_contexts_to_start = [
                            context
                            for context in selected_project_contexts
                            if str(context.name).strip() not in state_project_names
                        ]
                        emit_phase(
                            "auto_resume_evaluate",
                            auto_resume_started,
                            status="reuse_existing",
                            match_mode="superset",
                            state_project_count=len(state_project_names),
                            selected_project_count=len(selected_project_contexts),
                            new_project_count=len(project_contexts_to_start),
                        )
                        rt._emit(
                            "state.auto_resume",
                            run_id=existing_state.run_id,
                            mode=runtime_mode,
                            command=route.command,
                            match_mode="superset",
                            selected_projects=sorted(selected_project_names),
                            restored_projects=restored_project_names,
                            new_projects=[context.name for context in project_contexts_to_start],
                        )
                        existing_state = None
                    else:
                        emit_phase(
                            "auto_resume_evaluate",
                            auto_resume_started,
                            status="skipped",
                            reason="stale_existing_state",
                            state_project_count=len(state_project_names),
                            selected_project_count=len(selected_project_contexts),
                            missing_service_count=len(missing_services),
                        )
                        rt._emit(
                            "state.auto_resume.skipped",
                            reason="stale_existing_state",
                            missing_services=missing_services,
                            state_projects=sorted(state_project_names),
                            selected_projects=sorted(selected_project_names),
                            mode=runtime_mode,
                            command=route.command,
                        )
                        existing_state = None
                if existing_state is not None:
                    emit_phase(
                        "auto_resume_evaluate",
                        auto_resume_started,
                        status="skipped",
                        reason="project_selection_mismatch",
                        state_project_count=len(state_project_names),
                        selected_project_count=len(selected_project_contexts),
                    )
                    rt._emit(
                        "state.auto_resume.skipped",
                        reason="project_selection_mismatch",
                        state_projects=sorted(state_project_names),
                        selected_projects=sorted(selected_project_names),
                        mode=runtime_mode,
                        command=route.command,
                    )
            else:
                emit_phase("auto_resume_evaluate", auto_resume_started, status="none")

        if route.command == "plan" and bool(route.flags.get("planning_prs")):
            rt._emit("planning.projects.start", projects=[context.name for context in project_contexts])
            code = rt._run_pr_action(route, project_contexts)
            rt._emit("planning.projects.finish", code=code, projects=[context.name for context in project_contexts])
            if code == 0:
                print("Planning PR mode complete; skipping service startup.")
            return code

        emit_snapshot(
            "startup_branch_enter",
            command=requested_command,
            mode=runtime_mode,
            orch_group=sorted(debug_orch_groups) or None,
        )

        services = {}
        requirements: dict[str, RequirementsResult] = {}
        started_contexts: list[Any] = []
        errors: list[str] = []
        spinner_message = f"Starting {len(project_contexts_to_start)} project(s)..."
        spinner_policy = resolve_spinner_policy(getattr(rt, "env", {}))
        use_startup_spinner = spinner_policy.enabled and not self._suppress_progress_output(route)
        emit_spinner_policy(
            getattr(rt, "_emit", None),
            spinner_policy,
            context={"component": "startup_orchestrator", "op_id": "startup.execute"},
        )
        parallel_enabled, parallel_workers = rt._tree_parallel_startup_config(
            mode=runtime_mode,
            route=route,
            project_count=len(project_contexts_to_start),
        )
        rt._emit(
            "startup.execution",
            mode="parallel" if parallel_enabled else "sequential",
            workers=parallel_workers,
            projects=[context.name for context in project_contexts_to_start],
        )
        prewarm_started = time.monotonic()
        self._maybe_prewarm_docker(route=route, mode=runtime_mode)
        emit_phase("docker_prewarm", prewarm_started, status="ok")
        debug_suppress_plan_progress = bool(
            requested_command == "plan"
            and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_SUPPRESS_PLAN_PROGRESS", "")).strip().lower()
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
            and len(selected_project_contexts) > 1
            and str(getattr(spinner_policy, "backend", "")) == "rich"
        )
        project_spinner_group = _ProjectSpinnerGroup(
            projects=[context.name for context in selected_project_contexts],
            enabled=use_project_spinner_group,
            policy=spinner_policy,
            emit=getattr(rt, "_emit", None),
            component="startup_orchestrator",
            op_id="startup.execute",
            env=getattr(rt, "env", {}),
        )
        use_single_spinner = use_startup_spinner and not use_project_spinner_group
        group_context = project_spinner_group if use_project_spinner_group else nullcontext(project_spinner_group)

        with (
            use_spinner_policy(spinner_policy),
            spinner(
                spinner_message,
                enabled=use_single_spinner,
            ) as active_spinner,
        ):
            if use_single_spinner:
                route_for_execution.flags["_spinner_update"] = active_spinner.update
                rt._emit(  # type: ignore[attr-defined]
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
                    if use_project_spinner_group and restored_project_names:
                        for project_name in restored_project_names:
                            project_spinner_group.mark_success(project_name, "restored")
                    if parallel_enabled:
                        completed: dict[str, tuple[RequirementsResult, dict[str, Any], list[str]]] = {}
                        failures: list[str] = []
                        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_workers) as executor:
                            future_map = {
                                executor.submit(
                                    rt._start_project_context,
                                    context=context,
                                    mode=runtime_mode,
                                    route=route_for_execution,
                                    run_id=run_id,
                                ): context
                                for context in project_contexts_to_start
                            }
                            for future in concurrent.futures.as_completed(future_map):
                                context = future_map[future]
                                try:
                                    req_result, project_services, project_warnings = future.result()
                                    completed[context.name] = (req_result, project_services, project_warnings)
                                    if use_single_spinner:
                                        done = len(restored_project_names) + len(completed)
                                        progress_message = (
                                            f"Started {done}/{len(selected_project_contexts)} project(s)..."
                                        )
                                        active_spinner.update(progress_message)
                                        rt._emit(  # type: ignore[attr-defined]
                                            "ui.spinner.lifecycle",
                                            component="startup_orchestrator",
                                            op_id="startup.execute",
                                            state="update",
                                            message=progress_message,
                                        )
                                    if use_project_spinner_group:
                                        project_spinner_group.mark_success(
                                            context.name,
                                            f"startup completed ({_project_ports_text_impl(context)})",
                                        )
                                    self._render_project_startup_warnings(
                                        context=context,
                                        warnings=project_warnings,
                                        route=route_for_execution,
                                        project_spinner_group=project_spinner_group
                                        if use_project_spinner_group
                                        else None,
                                    )
                                except RuntimeError as exc:
                                    failures.append(str(exc))
                                    rt._emit("startup.project.failed", project=context.name, error=str(exc))
                                    if use_project_spinner_group:
                                        project_spinner_group.mark_failure(context.name, str(exc))
                        for context in project_contexts_to_start:
                            entry = completed.get(context.name)
                            if entry is None:
                                continue
                            req_result, project_services, _project_warnings = entry
                            requirements[context.name] = req_result
                            services.update(project_services)
                            started_contexts.append(context)
                        if failures:
                            raise RuntimeError("; ".join(failures))
                    else:
                        for context in project_contexts_to_start:
                            req_result, project_services, project_warnings = rt._start_project_context(
                                context=context,
                                mode=runtime_mode,
                                route=route_for_execution,
                                run_id=run_id,
                            )
                            requirements[context.name] = req_result
                            services.update(project_services)
                            started_contexts.append(context)
                            self._render_project_startup_warnings(
                                context=context,
                                warnings=project_warnings,
                                route=route_for_execution,
                                project_spinner_group=project_spinner_group if use_project_spinner_group else None,
                            )
            except RuntimeError as exc:
                if use_single_spinner:
                    active_spinner.fail("Startup failed")
                    rt._emit(  # type: ignore[attr-defined]
                        "ui.spinner.lifecycle",
                        component="startup_orchestrator",
                        op_id="startup.execute",
                        state="fail",
                        message="Startup failed",
                    )
                    rt._emit(  # type: ignore[attr-defined]
                        "ui.spinner.lifecycle",
                        component="startup_orchestrator",
                        op_id="startup.execute",
                        state="stop",
                    )
                exc_text = str(exc)
                if "no free port found" in exc_text.lower():
                    error = f"Port reservation failed: {exc_text}"
                else:
                    error = f"Startup failed: {exc_text}"
                errors.append(error)
                rt._emit("startup.failed", mode=runtime_mode, command=route.command, error=error)
                rt._terminate_started_services(services)
                port_allocator.release_session()
                run_state = RunState(
                    run_id=run_id,
                    mode=runtime_mode,
                    services=services,
                    requirements=requirements,
                    pointers={},
                    metadata={
                        "command": route.command,
                        "failed": True,
                        "repo_scope_id": rt.config.runtime_scope_id,
                        "project_roots": {context.name: str(context.root) for context in selected_project_contexts},
                    },
                )
                failed_run_dir = rt._run_dir_path(run_id)
                run_state.pointers = {
                    "run_state": str(failed_run_dir / "run_state.json"),
                    "runtime_map": str(failed_run_dir / "runtime_map.json"),
                    "ports_manifest": str(failed_run_dir / "ports_manifest.json"),
                    "error_report": str(failed_run_dir / "error_report.json"),
                    "events": str(failed_run_dir / "events.jsonl"),
                    "runtime_readiness_report": str(failed_run_dir / "runtime_readiness_report.json"),
                }
                artifacts_started = time.monotonic()
                rt._write_artifacts(run_state, selected_project_contexts, errors=errors)
                emit_phase("artifacts_write", artifacts_started, status="error")
                print(error)
                return 1
            if use_single_spinner:
                active_spinner.succeed("Startup complete")
                rt._emit(  # type: ignore[attr-defined]
                    "ui.spinner.lifecycle",
                    component="startup_orchestrator",
                    op_id="startup.execute",
                    state="success",
                    message="Startup complete",
                )
                rt._emit(  # type: ignore[attr-defined]
                    "ui.spinner.lifecycle",
                    component="startup_orchestrator",
                    op_id="startup.execute",
                    state="stop",
                )
        if preserved_services:
            services = {**preserved_services, **services}
        if preserved_requirements:
            requirements = {**preserved_requirements, **requirements}

        run_state = RunState(
            run_id=run_id,
            mode=runtime_mode,
            services=services,
            requirements=requirements,
            pointers={},
            metadata={
                "command": route.command,
                "repo_scope_id": rt.config.runtime_scope_id,
                "project_roots": {context.name: str(context.root) for context in selected_project_contexts},
            },
        )
        run_dir = rt._run_dir_path(run_id)
        run_state.pointers = {
            "run_state": str(run_dir / "run_state.json"),
            "runtime_map": str(run_dir / "runtime_map.json"),
            "ports_manifest": str(run_dir / "ports_manifest.json"),
            "error_report": str(run_dir / "error_report.json"),
            "events": str(run_dir / "events.jsonl"),
            "runtime_readiness_report": str(run_dir / "runtime_readiness_report.json"),
        }

        if rt.config.runtime_truth_mode == "strict":
            reconcile_started = time.monotonic()
            degraded_services = rt._reconcile_state_truth(run_state)
            emit_phase(
                "post_start_reconcile",
                reconcile_started,
                status="degraded" if degraded_services else "ok",
                missing_count=len(degraded_services),
            )
            rt._emit(
                "state.reconcile",
                run_id=run_state.run_id,
                source="start.post_start",
                missing_count=len(degraded_services),
                missing_services=degraded_services,
            )
            if degraded_services:
                unique_services = sorted(set(degraded_services))
                error = "Startup failed: service truth degraded after startup: " + ", ".join(unique_services)
                errors.append(error)
                run_state.metadata["failed"] = True
                rt._emit(
                    "startup.failed",
                    mode=runtime_mode,
                    command=route.command,
                    error=error,
                    services=unique_services,
                )
                rt._terminate_started_services(services)
                port_allocator.release_session()
                artifacts_started = time.monotonic()
                rt._write_artifacts(run_state, selected_project_contexts, errors=errors)
                emit_phase("artifacts_write", artifacts_started, status="error")
                print(error)
                return 1

        artifacts_started = time.monotonic()
        rt._write_artifacts(run_state, selected_project_contexts, errors=errors)
        emit_phase("artifacts_write", artifacts_started, status="ok")
        if _requirements_timing_enabled_impl(self, route) and not self._suppress_timing_output(route):
            rt._emit(
                "startup.debug_tty_group",
                component="startup_orchestrator",
                group="output",
                action="print_startup_summary",
                enabled=True,
                detail="startup_branch",
            )
            print_startup_summary_impl(
                self,
                project_contexts=selected_project_contexts,
                start_event_index=startup_event_index,
                startup_started_at=startup_started_at,
            )
        else:
            rt._emit(
                "startup.debug_tty_group",
                component="startup_orchestrator",
                group="output",
                action="print_startup_summary",
                enabled=False,
                detail="startup_branch",
            )
        if _startup_breakdown_enabled_impl(self, route):
            rt._emit(
                "startup.breakdown",
                command=requested_command,
                mode=runtime_mode,
                project_count=len(selected_project_contexts),
                projects=[context.name for context in selected_project_contexts],
                total_ms=round((time.monotonic() - startup_started_at) * 1000.0, 2),
            )
        rt._emit(
            "startup.debug_tty_group",
            component="startup_orchestrator",
            group="output",
            action="dashboard_summary_or_status",
            enabled=True,
            detail="startup_branch",
        )
        if not self._suppress_progress_output(route):
            if not use_project_spinner_group:
                rt._print_summary(run_state, selected_project_contexts)
        else:
            rt._emit("ui.status", message="Startup complete; refreshing dashboard...")  # type: ignore[attr-defined]
        emit_snapshot(
            "before_dashboard_entry",
            source="startup_branch",
            command=requested_command,
            mode=runtime_mode,
            service_count=len(run_state.services),
            requirement_count=len(run_state.requirements),
        )
        if rt._should_enter_post_start_interactive(route):
            return rt._run_interactive_dashboard_loop(run_state)
        return 0

    def _build_planning_dashboard_state(
        self,
        *,
        route: Route,
        runtime_mode: str,
        run_id: str,
        project_contexts: list[Any],
    ) -> RunState:
        rt: Any = self.runtime
        run_state = RunState(
            run_id=run_id,
            mode=runtime_mode,
            services={},
            requirements={},
            pointers={},
            metadata={
                "command": route.command,
                "repo_scope_id": rt.config.runtime_scope_id,
                "project_roots": {context.name: str(context.root) for context in project_contexts},
                "dashboard_configured_service_types": self._configured_service_types_for_mode(runtime_mode),
                "dashboard_hidden_commands": [
                    "stop",
                    "restart",
                    "stop-all",
                    "blast-all",
                    "logs",
                    "clear-logs",
                    "health",
                    "errors",
                ],
                "dashboard_runs_disabled": True,
                "dashboard_banner": f"envctl runs are disabled for {runtime_mode}; planning and action commands remain available.",
            },
        )
        run_dir = rt._run_dir_path(run_id)
        run_state.pointers = {
            "run_state": str(run_dir / "run_state.json"),
            "runtime_map": str(run_dir / "runtime_map.json"),
            "ports_manifest": str(run_dir / "ports_manifest.json"),
            "error_report": str(run_dir / "error_report.json"),
            "events": str(run_dir / "events.jsonl"),
            "runtime_readiness_report": str(run_dir / "runtime_readiness_report.json"),
        }
        return run_state

    def _configured_service_types_for_mode(self, runtime_mode: str) -> list[str]:
        rt: Any = self.runtime
        if hasattr(rt.config, "profile_for_mode"):
            profile = rt.config.profile_for_mode(runtime_mode)
            configured: list[str] = []
            if bool(getattr(profile, "backend_enable", False)):
                configured.append("backend")
            if bool(getattr(profile, "frontend_enable", False)):
                configured.append("frontend")
            return configured
        return [
            service_name
            for service_name, enabled in (
                ("backend", rt.config.service_enabled_for_mode(runtime_mode, "backend")),
                ("frontend", rt.config.service_enabled_for_mode(runtime_mode, "frontend")),
            )
            if enabled
        ]

    def _render_project_startup_warnings(
        self,
        *,
        context: Any,
        warnings: list[str],
        route: Route,
        project_spinner_group: Any | None,
    ) -> None:
        warning_lines = [str(line).strip() for line in warnings if str(line).strip()]
        if not warning_lines:
            return
        rt: Any = self.runtime
        if project_spinner_group is not None and hasattr(project_spinner_group, "print_detail"):
            for line in warning_lines:
                project_spinner_group.print_detail(context.name, line)
            return
        if self._suppress_progress_output(route):
            for line in warning_lines:
                rt._emit("ui.status", message=line)  # type: ignore[attr-defined]
            return
        for line in warning_lines:
            print(line)

    def _trees_start_selection_required(self, *, route: Route, runtime_mode: str) -> bool:
        return _trees_start_selection_required_impl(self, route=route, runtime_mode=runtime_mode)

    def _select_start_tree_projects(self, *, route: Route, project_contexts: list[Any]) -> list[Any]:
        return _select_start_tree_projects_impl(self, route=route, project_contexts=project_contexts)

    @staticmethod
    def _restart_include_requirements(route: Route) -> bool:
        return _restart_include_requirements_impl(route)

    def start_project_context(
        self,
        *,
        context: Any,
        mode: str,
        route: Route,
        run_id: str,
    ) -> tuple[RequirementsResult, dict[str, Any], list[str]]:
        return start_project_context_impl(self, context=context, mode=mode, route=route, run_id=run_id)

    def _requirements_for_restart_context(
        self,
        *,
        context: Any,
        mode: str,
        route: Route | None,
    ) -> RequirementsResult:
        return _requirements_for_restart_context_impl(self, context=context, mode=mode, route=route)

    @staticmethod
    def _suppress_progress_output(route: Route) -> bool:
        return suppress_progress_output(route)

    @staticmethod
    def _suppress_timing_output(route: Route | None) -> bool:
        return suppress_timing_output(route)

    def _report_progress(self, route: Route, message: str, *, project: str | None = None) -> None:
        report_progress(
            self.runtime,
            route,
            progress_lock=self._progress_lock,
            last_progress_message_by_project=self._last_progress_message_by_project,
            message=message,
            project=project,
        )

    def start_requirements_for_project(
        self,
        context: Any,
        *,
        mode: str,
        route: Route | None = None,
    ) -> RequirementsResult:
        return start_requirements_for_project_impl(self, context, mode=mode, route=route)

    def _requirements_timing_enabled(self, route: Route | None) -> bool:
        return _requirements_timing_enabled_impl(self, route)

    def _maybe_prewarm_docker(self, *, route: Route | None, mode: str) -> None:
        return _maybe_prewarm_docker_impl(self, route=route, mode=mode)

    def start_project_services(
        self,
        context: Any,
        *,
        requirements: RequirementsResult,
        run_id: str,
        route: Route | None = None,
    ) -> dict[str, Any]:
        return start_project_services_impl(self, context, requirements=requirements, run_id=run_id, route=route)

    @staticmethod
    def _restart_service_types_for_project(
        *,
        route: Route | None,
        project_name: str,
        default_service_types: set[str] | None = None,
    ) -> set[str]:
        return _restart_service_types_for_project_impl(
            route=route, project_name=project_name, default_service_types=default_service_types
        )

    @staticmethod
    def _process_runtime(runtime: Any) -> Any:
        return _process_runtime_impl(runtime)
