from __future__ import annotations

import concurrent.futures
from contextlib import nullcontext
import os
import threading
import time
from typing import Any

from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.runtime.command_router import MODE_TREE_TOKENS, Route
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.shared.parsing import parse_bool, parse_int
from envctl_engine.startup.startup_progress import (
    ProjectSpinnerGroup,
    report_progress,
    suppress_progress_output,
    suppress_timing_output,
)
from envctl_engine.startup.startup_selection_support import (
    _port_allocator as _port_allocator_impl,
    _process_runtime as _process_runtime_impl,
    _project_name_from_service_name as _project_name_from_service_name_impl,
    _project_ports_text as _project_ports_text_impl,
    _restart_include_requirements as _restart_include_requirements_impl,
    _restart_selected_services as _restart_selected_services_impl,
    _restart_service_types_for_project as _restart_service_types_for_project_impl,
    _restart_target_projects as _restart_target_projects_impl,
    _restart_target_projects_for_selected_services as _restart_target_projects_for_selected_services_impl,
    _route_explicit_trees_mode as _route_explicit_trees_mode_impl,
    _select_start_tree_projects as _select_start_tree_projects_impl,
    _state_matches_selected_projects as _state_matches_selected_projects_impl,
    _state_covers_selected_projects as _state_covers_selected_projects_impl,
    _state_project_names as _state_project_names_impl,
    _tree_preselected_projects_from_state as _tree_preselected_projects_from_state_impl,
    _trees_start_selection_required as _trees_start_selection_required_impl,
)
from envctl_engine.startup.startup_execution_support import (
    _docker_prewarm_enabled as _docker_prewarm_enabled_impl,
    _docker_prewarm_timeout_seconds as _docker_prewarm_timeout_seconds_impl,
    _maybe_prewarm_docker as _maybe_prewarm_docker_impl,
    _prewarm_requires_startup_requirements as _prewarm_requires_startup_requirements_impl,
    _requirements_for_restart_context as _requirements_for_restart_context_impl,
    _requirements_timing_enabled as _requirements_timing_enabled_impl,
    _service_attach_parallel_enabled as _service_attach_parallel_enabled_impl,
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
        port_allocator = self._port_allocator(rt)
        requested_command = route.command
        startup_started_at = time.monotonic()
        startup_event_index = len(getattr(rt, "events", []))
        debug_plan_snapshot = snapshot_enabled(getattr(rt, "env", {}))
        preserved_services: dict[str, Any] = {}
        preserved_requirements: dict[str, RequirementsResult] = {}
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
                selected_services = self._restart_selected_services(state=resumed, route=route)
                target_projects = self._restart_target_projects(state=resumed, route=route, runtime=rt)
                include_requirements = self._restart_include_requirements(route)
                if include_requirements and not target_projects:
                    target_projects = self._restart_target_projects_for_selected_services(
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
                with use_spinner_policy(prestop_policy), spinner(
                    "Restarting services...",
                    enabled=use_prestop_spinner,
                ) as prestop_spinner:
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
                            name: service
                            for name, service in resumed.services.items()
                            if name not in selected_services
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
        try:
            rt._validate_mode_toggles(runtime_mode, route=route)
        except RuntimeError as exc:
            print(str(exc))
            return 1

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
        if not rt._enforce_runtime_shell_budget_profile(scope=requested_command):
            emit_phase("shell_budget_gate", budget_started, status="blocked")
            print("Startup blocked: strict cutover shell budget profile is incomplete.")
            return 1
        emit_phase("shell_budget_gate", budget_started, status="ok")

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

        debug_orch_groups: set[str] = set()
        if requested_command == "plan":
            raw_orch_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_ORCH_GROUP", "")).strip().lower()
            debug_orch_groups = {
                token.strip()
                for token in raw_orch_group.replace("+", ",").split(",")
                if token.strip()
            }
        if requested_command != "restart" and rt._auto_resume_start_enabled(route):
            auto_resume_started = time.monotonic()
            existing_state = rt._load_auto_resume_state(runtime_mode)
            if existing_state is not None:
                exact_match = self._state_matches_selected_projects(runtime=rt, state=existing_state, contexts=project_contexts)
                subset_match = (
                    not exact_match
                    and runtime_mode == "trees"
                    and self._state_covers_selected_projects(runtime=rt, state=existing_state, contexts=project_contexts)
                )
                if exact_match or subset_match:
                    emit_phase(
                        "auto_resume_evaluate",
                        auto_resume_started,
                        status="resume",
                        match_mode="exact" if exact_match else "subset",
                        state_project_count=len(self._state_project_names(runtime=rt, state=existing_state)),
                        selected_project_count=len(project_contexts),
                    )
                    rt._emit(
                        "state.auto_resume",
                        run_id=existing_state.run_id,
                        mode=runtime_mode,
                        command=route.command,
                        match_mode="exact" if exact_match else "subset",
                        selected_projects=sorted({context.name for context in project_contexts}),
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
                emit_phase(
                    "auto_resume_evaluate",
                    auto_resume_started,
                    status="skipped",
                    reason="project_selection_mismatch",
                    state_project_count=len(self._state_project_names(runtime=rt, state=existing_state)),
                    selected_project_count=len(project_contexts),
                )
                rt._emit(
                    "state.auto_resume.skipped",
                    reason="project_selection_mismatch",
                    state_projects=sorted(self._state_project_names(runtime=rt, state=existing_state)),
                    selected_projects=sorted({context.name for context in project_contexts}),
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
        spinner_message = f"Starting {len(project_contexts)} project(s)..."
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
            project_count=len(project_contexts),
        )
        rt._emit(
            "startup.execution",
            mode="parallel" if parallel_enabled else "sequential",
            workers=parallel_workers,
            projects=[context.name for context in project_contexts],
        )
        prewarm_started = time.monotonic()
        self._maybe_prewarm_docker(route=route, mode=runtime_mode)
        emit_phase("docker_prewarm", prewarm_started, status="ok")
        debug_suppress_plan_progress = bool(
            requested_command == "plan"
            and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_SUPPRESS_PLAN_PROGRESS", "")).strip().lower() in {"1", "true", "yes", "on"}
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
            and len(project_contexts) > 1
            and str(getattr(spinner_policy, "backend", "")) == "rich"
        )
        project_spinner_group = _ProjectSpinnerGroup(
            projects=[context.name for context in project_contexts],
            enabled=use_project_spinner_group,
            policy=spinner_policy,
            emit=getattr(rt, "_emit", None),
            component="startup_orchestrator",
            op_id="startup.execute",
            env=getattr(rt, "env", {}),
        )
        use_single_spinner = use_startup_spinner and not use_project_spinner_group
        group_context = project_spinner_group if use_project_spinner_group else nullcontext(project_spinner_group)

        with use_spinner_policy(spinner_policy), spinner(
            spinner_message,
            enabled=use_single_spinner,
        ) as active_spinner:
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
                    if parallel_enabled:
                        completed: dict[str, tuple[RequirementsResult, dict[str, Any]]] = {}
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
                                for context in project_contexts
                            }
                            for future in concurrent.futures.as_completed(future_map):
                                context = future_map[future]
                                try:
                                    req_result, project_services = future.result()
                                    completed[context.name] = (req_result, project_services)
                                    if use_single_spinner:
                                        done = len(completed)
                                        progress_message = f"Started {done}/{len(project_contexts)} project(s)..."
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
                                            f"startup completed ({self._project_ports_text(context)})",
                                        )
                                except RuntimeError as exc:
                                    failures.append(str(exc))
                                    rt._emit("startup.project.failed", project=context.name, error=str(exc))
                                    if use_project_spinner_group:
                                        project_spinner_group.mark_failure(context.name, str(exc))
                        for context in project_contexts:
                            entry = completed.get(context.name)
                            if entry is None:
                                continue
                            req_result, project_services = entry
                            requirements[context.name] = req_result
                            services.update(project_services)
                            started_contexts.append(context)
                        if failures:
                            raise RuntimeError("; ".join(failures))
                    else:
                        for context in project_contexts:
                            req_result, project_services = rt._start_project_context(
                                context=context,
                                mode=runtime_mode,
                                route=route_for_execution,
                                run_id=run_id,
                            )
                            requirements[context.name] = req_result
                            services.update(project_services)
                            started_contexts.append(context)
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
                        "project_roots": {context.name: str(context.root) for context in project_contexts},
                    },
                )
                failed_run_dir = rt._run_dir_path(run_id)
                run_state.pointers = {
                    "run_state": str(failed_run_dir / "run_state.json"),
                    "runtime_map": str(failed_run_dir / "runtime_map.json"),
                    "ports_manifest": str(failed_run_dir / "ports_manifest.json"),
                    "error_report": str(failed_run_dir / "error_report.json"),
                    "events": str(failed_run_dir / "events.jsonl"),
                    "shell_prune_report": str(failed_run_dir / "shell_prune_report.json"),
                }
                artifacts_started = time.monotonic()
                rt._write_artifacts(run_state, started_contexts, errors=errors)
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
                "project_roots": {context.name: str(context.root) for context in project_contexts},
            },
        )
        run_dir = rt._run_dir_path(run_id)
        run_state.pointers = {
            "run_state": str(run_dir / "run_state.json"),
            "runtime_map": str(run_dir / "runtime_map.json"),
            "ports_manifest": str(run_dir / "ports_manifest.json"),
            "error_report": str(run_dir / "error_report.json"),
            "events": str(run_dir / "events.jsonl"),
            "shell_prune_report": str(run_dir / "shell_prune_report.json"),
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
                rt._write_artifacts(run_state, project_contexts, errors=errors)
                emit_phase("artifacts_write", artifacts_started, status="error")
                print(error)
                return 1

        artifacts_started = time.monotonic()
        rt._write_artifacts(run_state, project_contexts, errors=errors)
        emit_phase("artifacts_write", artifacts_started, status="ok")
        if self._requirements_timing_enabled(route) and not self._suppress_timing_output(route):
            rt._emit(
                "startup.debug_tty_group",
                component="startup_orchestrator",
                group="output",
                action="print_startup_summary",
                enabled=True,
                detail="startup_branch",
            )
            self._print_startup_summary(
                project_contexts=project_contexts,
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
        if self._startup_breakdown_enabled(route):
            rt._emit(
                "startup.breakdown",
                command=requested_command,
                mode=runtime_mode,
                project_count=len(project_contexts),
                projects=[context.name for context in project_contexts],
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
                rt._print_summary(run_state, project_contexts)
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

    @staticmethod
    def _project_ports_text(context: Any) -> str:
        return _project_ports_text_impl(context)

    @staticmethod
    def _state_project_names(*, runtime: Any, state: RunState) -> set[str]:
        return _state_project_names_impl(runtime=runtime, state=state)

    def _state_matches_selected_projects(self, *, runtime: Any, state: RunState, contexts: list[Any]) -> bool:
        return _state_matches_selected_projects_impl(self, runtime=runtime, state=state, contexts=contexts)

    def _state_covers_selected_projects(self, *, runtime: Any, state: RunState, contexts: list[Any]) -> bool:
        return _state_covers_selected_projects_impl(self, runtime=runtime, state=state, contexts=contexts)

    @staticmethod
    def _route_explicit_trees_mode(route: Route) -> bool:
        return _route_explicit_trees_mode_impl(route)

    def _trees_start_selection_required(self, *, route: Route, runtime_mode: str) -> bool:
        return _trees_start_selection_required_impl(self, route=route, runtime_mode=runtime_mode)

    def _tree_preselected_projects_from_state(self, *, runtime: Any, project_contexts: list[Any]) -> list[str]:
        return _tree_preselected_projects_from_state_impl(self, runtime=runtime, project_contexts=project_contexts)

    def _select_start_tree_projects(self, *, route: Route, project_contexts: list[Any]) -> list[Any]:
        return _select_start_tree_projects_impl(self, route=route, project_contexts=project_contexts)

    @staticmethod
    def _restart_include_requirements(route: Route) -> bool:
        return _restart_include_requirements_impl(route)

    @staticmethod
    def _restart_selected_services(*, state: RunState, route: Route) -> set[str]:
        return _restart_selected_services_impl(state=state, route=route)

    @staticmethod
    def _restart_target_projects(*, state: RunState, route: Route, runtime: Any) -> set[str]:
        return _restart_target_projects_impl(state=state, route=route, runtime=runtime)

    @staticmethod
    def _restart_target_projects_for_selected_services(*, selected_services: set[str], state: RunState, runtime: Any) -> set[str]:
        return _restart_target_projects_for_selected_services_impl(selected_services=selected_services, state=state, runtime=runtime)

    @staticmethod
    def _project_name_from_service_name(name: str) -> str | None:
        return _project_name_from_service_name_impl(name)

    def start_project_context(
        self,
        *,
        context: Any,
        mode: str,
        route: Route,
        run_id: str,
    ) -> tuple[RequirementsResult, dict[str, Any]]:
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

    def _docker_prewarm_enabled(self, route: Route | None) -> bool:
        return _docker_prewarm_enabled_impl(self, route)

    def _docker_prewarm_timeout_seconds(self, route: Route | None) -> int:
        return _docker_prewarm_timeout_seconds_impl(self, route)

    def _prewarm_requires_startup_requirements(self, *, mode: str, route: Route | None) -> bool:
        return _prewarm_requires_startup_requirements_impl(self, mode=mode, route=route)

    def _maybe_prewarm_docker(self, *, route: Route | None, mode: str) -> None:
        return _maybe_prewarm_docker_impl(self, route=route, mode=mode)

    def _startup_breakdown_enabled(self, route: Route | None) -> bool:
        return _startup_breakdown_enabled_impl(self, route)

    def _print_startup_summary(
        self,
        *,
        project_contexts: list[Any],
        start_event_index: int,
        startup_started_at: float,
    ) -> None:
        return print_startup_summary_impl(
            self,
            project_contexts=project_contexts,
            start_event_index=start_event_index,
            startup_started_at=startup_started_at,
        )

    def _service_attach_parallel_enabled(self, *, route: Route | None, selected_service_types: set[str]) -> bool:
        return _service_attach_parallel_enabled_impl(self, route=route, selected_service_types=selected_service_types)

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
        return _restart_service_types_for_project_impl(route=route, project_name=project_name, default_service_types=default_service_types)

    @staticmethod
    def _port_allocator(runtime: Any) -> Any:
        return _port_allocator_impl(runtime)

    @staticmethod
    def _process_runtime(runtime: Any) -> Any:
        return _process_runtime_impl(runtime)
