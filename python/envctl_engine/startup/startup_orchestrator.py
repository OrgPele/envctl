from __future__ import annotations

import concurrent.futures
from contextlib import nullcontext
from pathlib import Path
import shlex
import sys
import threading
import time
from typing import cast

from envctl_engine.runtime.command_router import MODE_TREE_TOKENS, Route
from envctl_engine.planning.plan_agent_launch_support import (
    CreatedPlanWorktree,
    attach_plan_agent_terminal,
    launch_plan_agent_terminals,
)
from envctl_engine.runtime.engine_runtime_env import route_is_implicit_start
from envctl_engine.runtime.engine_runtime_startup_support import evaluate_run_reuse, mark_run_reused
from envctl_engine.runtime.runtime_context import resolve_state_repository
from envctl_engine.state.models import RequirementsResult, ServiceRecord
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.startup.finalization import (
    build_failure_run_state,
    build_planning_dashboard_state,
    build_success_run_state,
)
from envctl_engine.startup.run_reuse_support import RunReuseDecision
from envctl_engine.startup.protocols import ProjectContextLike, StartupRuntime
from envctl_engine.startup.session import ProjectStartupResult, StartupSession
from envctl_engine.startup.startup_progress import (
    ProjectSpinnerGroup,
    report_progress,
    suppress_progress_output,
    suppress_timing_output,
)
from envctl_engine.startup.startup_selection_support import (
    port_allocator as port_allocator_impl,
    process_runtime as process_runtime_impl,
    project_ports_text as project_ports_text_impl,
    _restart_include_requirements as _restart_include_requirements_impl,
    _restart_selected_services as _restart_selected_services_impl,
    _restart_service_types_for_project as _restart_service_types_for_project_impl,
    restart_target_projects as restart_target_projects_impl,
    restart_target_projects_for_selected_services as restart_target_projects_for_selected_services_impl,
    select_start_tree_projects as select_start_tree_projects_impl,
    trees_start_selection_required as trees_start_selection_required_impl,
)
from envctl_engine.startup.startup_execution_support import (
    maybe_prewarm_docker as maybe_prewarm_docker_impl,
    print_startup_summary as print_startup_summary_impl,
    requirements_for_restart_context as requirements_for_restart_context_impl,
    requirements_timing_enabled as requirements_timing_enabled_impl,
    start_project_context as start_project_context_impl,
    start_project_services as start_project_services_impl,
    start_requirements_for_project as start_requirements_for_project_impl,
    startup_breakdown_enabled as startup_breakdown_enabled_impl,
)
from envctl_engine.ui.debug_snapshot import emit_plan_handoff_snapshot, snapshot_enabled
from envctl_engine.ui.path_links import local_paths_in_text, render_paths_in_terminal_text
from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy

_MODE_TREE_TOKENS_NORMALIZED = {str(token).strip().lower() for token in MODE_TREE_TOKENS}
_ProjectSpinnerGroup = ProjectSpinnerGroup


class StartupOrchestrator:
    def __init__(self, runtime: StartupRuntime) -> None:
        self.runtime: StartupRuntime = runtime
        self._progress_lock: threading.Lock = threading.Lock()
        self._last_progress_message_by_project: dict[str | None, str] = {}

    def execute(self, route: Route) -> int:
        session = self._create_session(route)
        try:
            for phase in (
                self._validate_route_contract,
                self._handle_restart_prestop,
                self._select_contexts,
                self._resolve_run_reuse,
                self._resolve_disabled_startup_mode,
            ):
                code = phase(session)
                if code is not None:
                    return code
            self._ensure_run_id(session)
            self._announce_session_identifiers(session)
            self._prepare_execution(session)
            self._start_selected_contexts(session)
            self._reconcile_strict_truth(session)
            return self._finalize_success(session)
        except RuntimeError as exc:
            return self._finalize_failure(session, str(exc))
        except Exception as exc:
            return self._finalize_failure(session, str(exc))

    def _create_session(self, route: Route) -> StartupSession:
        rt = self.runtime
        runtime_mode = rt._effective_start_mode(route)
        session = StartupSession(
            requested_route=route,
            effective_route=route,
            requested_command=route.command,
            runtime_mode=runtime_mode,
            run_id=None,
            startup_event_index=len(rt.events),
            debug_plan_snapshot=snapshot_enabled(dict(rt.env)),
        )
        rt._reset_project_startup_warnings()
        return session

    def _ensure_run_id(self, session: StartupSession) -> None:
        if session.run_id is None:
            session.run_id = self.runtime._new_run_id()

    @staticmethod
    def _resolved_run_id(session: StartupSession) -> str:
        if session.run_id is None:
            raise RuntimeError("run_id must be resolved before use")
        return session.run_id

    def _announce_session_identifiers(self, session: StartupSession) -> None:
        if session.identifiers_announced:
            return
        self._ensure_run_id(session)
        if not self._headless_plan_output_only(session):
            print(f"run_id: {self._resolved_run_id(session)}")
            print(f"session_id: {self.runtime._current_session_id() or 'unknown'}")
        session.identifiers_announced = True

    def _validate_route_contract(self, session: StartupSession) -> int | None:
        rt = self.runtime
        hook_contract_issue = rt._startup_hook_contract_issue()
        if hook_contract_issue:
            print(hook_contract_issue)
            return 1
        try:
            rt._validate_mode_toggles(session.runtime_mode, route=session.effective_route)
        except RuntimeError as exc:
            print(str(exc))
            return 1

        budget_started = time.monotonic()
        if not rt._enforce_runtime_readiness_contract(scope=session.requested_command):
            self._emit_phase(session, "runtime_readiness_gate", budget_started, status="blocked")
            print("Startup blocked: strict runtime readiness gate is incomplete.")
            return 1
        self._emit_phase(session, "runtime_readiness_gate", budget_started, status="ok")
        return None

    def _handle_restart_prestop(self, session: StartupSession) -> int | None:
        rt = self.runtime
        route = session.effective_route
        if route.command != "restart":
            return None
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
        if resumed is None:
            session.effective_route = Route(
                command="start",
                mode=restart_lookup_mode,
                raw_args=route.raw_args,
                passthrough_args=route.passthrough_args,
                projects=route.projects,
                flags={**route.flags, "_restart_request": True},
            )
            session.runtime_mode = restart_lookup_mode
            return None

        selected_services = _restart_selected_services_impl(state=resumed, route=route)
        target_projects = restart_target_projects_impl(state=resumed, route=route, runtime=rt)
        include_requirements = self._restart_include_requirements(route)
        if include_requirements and not target_projects:
            target_projects = restart_target_projects_for_selected_services_impl(
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
        prestop_policy = resolve_spinner_policy(dict(rt.env))
        use_prestop_spinner = prestop_policy.enabled and not self._suppress_progress_output(route)
        emit_spinner_policy(
            rt._emit,
            prestop_policy,
            context={"component": "startup_orchestrator", "op_id": "restart.prestop"},
        )
        with (
            use_spinner_policy(prestop_policy),
            spinner("Restarting services...", enabled=use_prestop_spinner) as prestop_spinner,
        ):
            if use_prestop_spinner:
                rt._emit(
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
                        session.preserved_requirements[project_name] = requirements
                session.preserved_services = {
                    name: service for name, service in resumed.services.items() if name not in selected_services
                }
                if use_prestop_spinner:
                    prestop_spinner.succeed("Restart pre-stop complete")
                    rt._emit(
                        "ui.spinner.lifecycle",
                        component="startup_orchestrator",
                        op_id="restart.prestop",
                        state="success",
                        message="Restart pre-stop complete",
                    )
            except Exception:
                if use_prestop_spinner:
                    prestop_spinner.fail("Restart pre-stop failed")
                    rt._emit(
                        "ui.spinner.lifecycle",
                        component="startup_orchestrator",
                        op_id="restart.prestop",
                        state="fail",
                        message="Restart pre-stop failed",
                    )
                raise
            finally:
                if use_prestop_spinner:
                    rt._emit(
                        "ui.spinner.lifecycle",
                        component="startup_orchestrator",
                        op_id="restart.prestop",
                        state="stop",
                    )
        session.effective_route = Route(
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
        session.runtime_mode = restart_lookup_mode
        return None

    def _select_contexts(self, session: StartupSession) -> int | None:
        rt = self.runtime
        route = session.effective_route
        runtime_mode = session.runtime_mode
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
            self._emit_phase(session, "project_selection", selection_started, status="error")
            print(duplicate_error)
            rt._emit("planning.projects.duplicate", error=duplicate_error)
            return 1
        self._emit_phase(
            session,
            "project_selection",
            selection_started,
            status="ok",
            project_count=len(project_contexts),
        )
        self._emit_snapshot(
            session,
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
        if route.command == "plan" and not bool(route.flags.get("planning_prs")):
            planning_orchestrator = getattr(rt, "planning_worktree_orchestrator", None)
            selection_getter = getattr(planning_orchestrator, "last_plan_selection_result", None)
            if callable(selection_getter):
                selection_result = selection_getter()
                selected_names = {context.name for context in project_contexts}
                created_worktrees = tuple(
                    worktree
                    for worktree in getattr(selection_result, "created_worktrees", ())
                    if isinstance(worktree, CreatedPlanWorktree) and worktree.name in selected_names
                )
                if not created_worktrees and bool(route.flags.get("tmux")):
                    recovered_worktrees: list[CreatedPlanWorktree] = []
                    for context in project_contexts:
                        recovered_worktrees.append(
                            CreatedPlanWorktree(
                                name=context.name,
                                root=Path(context.root),
                                plan_file="",
                            )
                        )
                    created_worktrees = tuple(recovered_worktrees)
                launch_result = launch_plan_agent_terminals(rt, route=route, created_worktrees=created_worktrees)
                session.plan_agent_attach_target = launch_result.attach_target
        session.selected_contexts = list(project_contexts)
        session.contexts_to_start = list(project_contexts)
        return None

    def _resolve_disabled_startup_mode(self, session: StartupSession) -> int | None:
        rt = self.runtime
        route = session.effective_route
        mode_runs_enabled = (
            rt.config.startup_enabled_for_mode(session.runtime_mode)
            if hasattr(rt.config, "startup_enabled_for_mode")
            else True
        )
        allow_disabled_dashboard = not mode_runs_enabled and (route.command == "plan" or route_is_implicit_start(route))
        session.disabled_startup_mode = allow_disabled_dashboard
        if not allow_disabled_dashboard:
            return None
        self._ensure_run_id(session)
        self._announce_session_identifiers(session)
        run_state = build_planning_dashboard_state(
            rt,
            route=route,
            runtime_mode=session.runtime_mode,
            run_id=self._resolved_run_id(session),
            project_contexts=session.selected_contexts,
            configured_service_types=self._configured_service_types_for_mode(session.runtime_mode),
            base_metadata=session.base_metadata,
        )
        artifacts_started = time.monotonic()
        rt._write_artifacts(run_state, session.selected_contexts, errors=[])
        self._emit_phase(session, "artifacts_write", artifacts_started, status="ok")
        if self._headless_plan_output_only(session):
            self._print_headless_plan_session_summary(session)
            return 0
        enter_interactive_dashboard = rt._should_enter_post_start_interactive(route)
        if route.command == "plan":
            print(
                "Planning mode complete; skipping service startup because "
                f"envctl runs are disabled for {session.runtime_mode}."
            )
        attach_code = self._maybe_attach_plan_agent_terminal(session)
        if attach_code is not None:
            return attach_code
        elif not enter_interactive_dashboard:
            print(f"envctl runs are disabled for {session.runtime_mode}; opening dashboard without starting services.")
        if enter_interactive_dashboard:
            return rt._run_interactive_dashboard_loop(run_state)
        return 0

    def _resolve_run_reuse(self, session: StartupSession) -> int | None:
        rt = self.runtime
        route = session.effective_route
        runtime_mode = session.runtime_mode
        requested_command = session.requested_command
        if requested_command == "plan":
            raw_orch_group = str(rt.env.get("ENVCTL_DEBUG_PLAN_ORCH_GROUP", "")).strip().lower()
            debug_orch_groups = {
                token.strip() for token in raw_orch_group.replace("+", ",").split(",") if token.strip()
            }
        else:
            debug_orch_groups = set()
        if requested_command != "restart":
            reuse_started = time.monotonic()
            decision = cast(
                RunReuseDecision,
                evaluate_run_reuse(
                    rt,
                    runtime_mode=runtime_mode,
                    route=route,
                    contexts=cast(list[object], session.selected_contexts),
                ),
            )
            candidate_state = decision.candidate_state
            candidate_run_id = candidate_state.run_id if candidate_state is not None else None
            rt._emit(
                "state.run_reuse.evaluate",
                run_id=candidate_run_id,
                mode=runtime_mode,
                command=route.command,
                decision_kind=decision.decision_kind,
                reason=decision.reason,
                selected_projects=decision.selected_projects,
                state_projects=decision.state_projects,
                weak_identity=decision.weak_identity,
                mismatch_details=decision.mismatch_details,
            )
            if decision.decision_kind in {"resume_exact", "resume_subset"} and candidate_state is not None:
                previous_run_id = session.run_id
                previous_identifiers_announced = session.identifiers_announced
                session.run_id = candidate_state.run_id
                self._announce_session_identifiers(session)
                self._emit_phase(
                    session,
                    "auto_resume_evaluate",
                    reuse_started,
                    status="resume",
                    match_mode="exact" if decision.decision_kind == "resume_exact" else "subset",
                    state_project_count=len(decision.state_projects),
                    selected_project_count=len(session.selected_contexts),
                )
                rt._emit(
                    "state.auto_resume",
                    run_id=candidate_state.run_id,
                    mode=runtime_mode,
                    command=route.command,
                    match_mode="exact" if decision.decision_kind == "resume_exact" else "subset",
                    selected_projects=[project["name"] for project in decision.selected_projects],
                )
                rt._emit(
                    "state.run_reuse.applied",
                    run_id=candidate_state.run_id,
                    mode=runtime_mode,
                    command=route.command,
                    decision_kind=decision.decision_kind,
                    reason=decision.reason,
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
                        "_run_reuse_reason": decision.decision_kind,
                    },
                )
                resume_code = rt._resume(resume_route)
                if int(resume_code) == 0:
                    return 0
                session.run_id = previous_run_id
                session.identifiers_announced = previous_identifiers_announced
                rt._emit(
                    "state.auto_resume.skipped",
                    reason="resume_failed",
                    resume_code=int(resume_code),
                    state_projects=[project["name"] for project in decision.state_projects],
                    selected_projects=[project["name"] for project in decision.selected_projects],
                    mode=runtime_mode,
                    command=route.command,
                )
                rt._emit(
                    "state.run_reuse.skipped",
                    run_id=candidate_state.run_id,
                    reason="resume_failed",
                    resume_code=int(resume_code),
                    mode=runtime_mode,
                    command=route.command,
                )
            elif decision.decision_kind == "reuse_expand" and candidate_state is not None:
                missing_services = rt._reconcile_state_truth(candidate_state)
                if not missing_services:
                    session.base_metadata = mark_run_reused(candidate_state.metadata, reason="reuse_expand")
                    session.resumed_context_names = [project["name"] for project in decision.state_projects]
                    session.preserved_services = dict(candidate_state.services)
                    session.preserved_requirements = dict(candidate_state.requirements)
                    resumed_names = {name.lower() for name in session.resumed_context_names}
                    session.contexts_to_start = [
                        context
                        for context in session.selected_contexts
                        if str(context.name).strip().lower() not in resumed_names
                    ]
                    self._emit_phase(
                        session,
                        "auto_resume_evaluate",
                        reuse_started,
                        status="reuse_existing",
                        match_mode="superset",
                        state_project_count=len(decision.state_projects),
                        selected_project_count=len(session.selected_contexts),
                        new_project_count=len(session.contexts_to_start),
                    )
                    rt._emit(
                        "state.auto_resume",
                        run_id=candidate_state.run_id,
                        mode=runtime_mode,
                        command=route.command,
                        match_mode="superset",
                        selected_projects=[project["name"] for project in decision.selected_projects],
                        restored_projects=session.resumed_context_names,
                        new_projects=[context.name for context in session.contexts_to_start],
                    )
                    rt._emit(
                        "state.run_reuse.applied",
                        run_id=candidate_state.run_id,
                        mode=runtime_mode,
                        command=route.command,
                        decision_kind=decision.decision_kind,
                        reason=decision.reason,
                        restored_projects=session.resumed_context_names,
                        new_projects=[context.name for context in session.contexts_to_start],
                    )
                else:
                    self._emit_phase(
                        session,
                        "auto_resume_evaluate",
                        reuse_started,
                        status="skipped",
                        reason="stale_existing_state",
                        state_project_count=len(decision.state_projects),
                        selected_project_count=len(session.selected_contexts),
                        missing_service_count=len(missing_services),
                    )
                    rt._emit(
                        "state.auto_resume.skipped",
                        reason="stale_existing_state",
                        missing_services=missing_services,
                        state_projects=[project["name"] for project in decision.state_projects],
                        selected_projects=[project["name"] for project in decision.selected_projects],
                        mode=runtime_mode,
                        command=route.command,
                    )
                    rt._emit(
                        "state.run_reuse.skipped",
                        run_id=candidate_state.run_id,
                        reason="stale_existing_state",
                        missing_services=missing_services,
                        mode=runtime_mode,
                        command=route.command,
                    )
            elif decision.decision_kind == "resume_dashboard_exact" and candidate_state is not None:
                session.run_id = candidate_state.run_id
                self._announce_session_identifiers(session)
                candidate_state.metadata = build_planning_dashboard_state(
                    rt,
                    route=route,
                    runtime_mode=session.runtime_mode,
                    run_id=candidate_state.run_id,
                    project_contexts=session.selected_contexts,
                    configured_service_types=self._configured_service_types_for_mode(session.runtime_mode),
                    base_metadata=mark_run_reused(candidate_state.metadata, reason="resume_dashboard_exact"),
                ).metadata
                resolve_state_repository(rt).save_resume_state(
                    state=candidate_state,
                    emit=rt._emit,
                    runtime_map_builder=cast(object, build_runtime_map),
                )
                self._emit_phase(
                    session,
                    "auto_resume_evaluate",
                    reuse_started,
                    status="dashboard_resume",
                    match_mode="exact",
                    state_project_count=len(decision.state_projects),
                    selected_project_count=len(session.selected_contexts),
                )
                rt._emit(
                    "state.run_reuse.applied",
                    run_id=candidate_state.run_id,
                    mode=runtime_mode,
                    command=route.command,
                    decision_kind=decision.decision_kind,
                    reason=decision.reason,
                )
                rt._emit(
                    "state.dashboard_resume",
                    run_id=candidate_state.run_id,
                    mode=runtime_mode,
                    command=route.command,
                )
                if self._headless_plan_output_only(session):
                    self._print_headless_plan_session_summary(session)
                    return 0
                enter_interactive_dashboard = rt._should_enter_post_start_interactive(route)
                if route.command == "plan":
                    print(
                        "Planning mode complete; skipping service startup because "
                        f"envctl runs are disabled for {session.runtime_mode}."
                    )
                    attach_code = self._maybe_attach_plan_agent_terminal(session)
                    if attach_code is not None:
                        return attach_code
                elif not enter_interactive_dashboard:
                    print(
                        f"envctl runs are disabled for {session.runtime_mode}; opening dashboard without starting services."
                    )
                if enter_interactive_dashboard:
                    return rt._run_interactive_dashboard_loop(candidate_state)
                return 0
            else:
                self._emit_phase(
                    session,
                    "auto_resume_evaluate",
                    reuse_started,
                    status="skipped" if candidate_state is not None else "none",
                    reason=decision.reason if candidate_state is not None else None,
                    state_project_count=len(decision.state_projects),
                    selected_project_count=len(session.selected_contexts),
                )
                if candidate_state is not None:
                    rt._emit(
                        "state.auto_resume.skipped",
                        reason=decision.reason,
                        state_projects=[project["name"] for project in decision.state_projects],
                        selected_projects=[project["name"] for project in decision.selected_projects],
                        mode=runtime_mode,
                        command=route.command,
                    )
                    rt._emit(
                        "state.run_reuse.skipped",
                        run_id=candidate_state.run_id,
                        reason=decision.reason,
                        mode=runtime_mode,
                        command=route.command,
                        mismatch_details=decision.mismatch_details,
                    )

        if route.command == "plan" and bool(route.flags.get("planning_prs")):
            rt._emit("planning.projects.start", projects=[context.name for context in session.selected_contexts])
            code = rt._run_pr_action(route, session.selected_contexts)
            rt._emit(
                "planning.projects.finish", code=code, projects=[context.name for context in session.selected_contexts]
            )
            if code == 0:
                print("Planning PR mode complete; skipping service startup.")
            return code

        self._emit_snapshot(
            session,
            "startup_branch_enter",
            command=requested_command,
            mode=runtime_mode,
            orch_group=sorted(debug_orch_groups) or None,
        )
        return None

    def _prepare_execution(self, session: StartupSession) -> None:
        route = session.effective_route
        prewarm_started = time.monotonic()
        self._maybe_prewarm_docker(route=route, mode=session.runtime_mode)
        self._emit_phase(session, "docker_prewarm", prewarm_started, status="ok")

    def _start_selected_contexts(self, session: StartupSession) -> None:
        rt = self.runtime
        route = session.effective_route
        spinner_message = f"Starting {len(session.contexts_to_start)} project(s)..."
        spinner_policy = resolve_spinner_policy(dict(rt.env))
        use_startup_spinner = spinner_policy.enabled and not self._suppress_progress_output(route)
        emit_spinner_policy(
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
            and str(rt.env.get("ENVCTL_DEBUG_SUPPRESS_PLAN_PROGRESS", "")).strip().lower() in {"1", "true", "yes", "on"}
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
        project_spinner_group = _ProjectSpinnerGroup(
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
            use_spinner_policy(spinner_policy),
            spinner(spinner_message, enabled=use_single_spinner) as active_spinner,
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
                        completed: dict[str, ProjectStartupResult] = {}
                        failures: list[str] = []
                        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel_workers) as executor:
                            future_map = {
                                executor.submit(
                                    rt._start_project_context,
                                    context=context,
                                    mode=session.runtime_mode,
                                    route=route_for_execution,
                                    run_id=self._resolved_run_id(session),
                                ): context
                                for context in session.contexts_to_start
                            }
                            for future in concurrent.futures.as_completed(future_map):
                                context = future_map[future]
                                try:
                                    result = future.result()
                                    completed[context.name] = result
                                    if use_single_spinner:
                                        done = len(session.resumed_context_names) + len(completed)
                                        progress_message = (
                                            f"Started {done}/{len(session.selected_contexts)} project(s)..."
                                        )
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
                                            f"startup completed ({project_ports_text_impl(context)})",
                                        )
                                    self._render_project_startup_warnings(
                                        context=context,
                                        warnings=result.warnings,
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
                        for context in session.contexts_to_start:
                            result = completed.get(context.name)
                            if result is None:
                                continue
                            self._record_project_startup(session, context, result)
                        if failures:
                            raise RuntimeError("; ".join(failures))
                    else:
                        for context in session.contexts_to_start:
                            result = rt._start_project_context(
                                context=context,
                                mode=session.runtime_mode,
                                route=route_for_execution,
                                run_id=self._resolved_run_id(session),
                            )
                            self._record_project_startup(session, context, result)
                            self._render_project_startup_warnings(
                                context=context,
                                warnings=result.warnings,
                                route=route_for_execution,
                                project_spinner_group=project_spinner_group if use_project_spinner_group else None,
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
                active_spinner.succeed("Startup complete")
                rt._emit(
                    "ui.spinner.lifecycle",
                    component="startup_orchestrator",
                    op_id="startup.execute",
                    state="success",
                    message="Startup complete",
                )
                rt._emit(
                    "ui.spinner.lifecycle",
                    component="startup_orchestrator",
                    op_id="startup.execute",
                    state="stop",
                )

    def _reconcile_strict_truth(self, session: StartupSession) -> None:
        rt = self.runtime
        if rt.config.runtime_truth_mode != "strict":
            return
        run_state = build_success_run_state(rt, session)
        reconcile_started = time.monotonic()
        degraded_services = rt._reconcile_state_truth(run_state)
        self._emit_phase(
            session,
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
            session.strict_truth_failed = True
            unique_services = sorted(set(degraded_services))
            raise RuntimeError("service truth degraded after startup: " + ", ".join(unique_services))

    def _finalize_success(self, session: StartupSession) -> int:
        rt = self.runtime
        self._ensure_run_id(session)
        run_state = build_success_run_state(rt, session)
        artifacts_started = time.monotonic()
        rt._write_artifacts(run_state, session.selected_contexts, errors=session.errors)
        self._emit_phase(session, "artifacts_write", artifacts_started, status="ok")
        if requirements_timing_enabled_impl(self, session.effective_route) and not self._suppress_timing_output(
            session.effective_route
        ):
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
                project_contexts=session.selected_contexts,
                start_event_index=session.startup_event_index,
                startup_started_at=session.startup_started_at,
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
        if startup_breakdown_enabled_impl(self, session.effective_route):
            rt._emit(
                "startup.breakdown",
                command=session.requested_command,
                mode=session.runtime_mode,
                project_count=len(session.selected_contexts),
                projects=[context.name for context in session.selected_contexts],
                total_ms=round((time.monotonic() - session.startup_started_at) * 1000.0, 2),
            )
        rt._emit(
            "startup.debug_tty_group",
            component="startup_orchestrator",
            group="output",
            action="dashboard_summary_or_status",
            enabled=True,
            detail="startup_branch",
        )
        if not self._suppress_progress_output(session.effective_route):
            if session.used_project_spinner_group:
                pass
            else:
                rt._print_summary(run_state, session.selected_contexts)
        else:
            rt._emit("ui.status", message="Startup complete; refreshing dashboard...")
        self._emit_snapshot(
            session,
            "before_dashboard_entry",
            source="startup_branch",
            command=session.requested_command,
            mode=session.runtime_mode,
            service_count=len(run_state.services),
            requirement_count=len(run_state.requirements),
        )
        if self._headless_plan_output_only(session):
            self._print_headless_plan_session_summary(session)
            return 0
        attach_code = self._maybe_attach_plan_agent_terminal(session)
        if attach_code is not None:
            return attach_code
        if rt._should_enter_post_start_interactive(session.effective_route):
            return rt._run_interactive_dashboard_loop(run_state)
        return 0

    def _headless_plan_output_only(self, session: StartupSession) -> bool:
        route = session.effective_route
        return route.command == "plan" and bool(route.flags.get("batch"))

    def _maybe_attach_plan_agent_terminal(self, session: StartupSession) -> int | None:
        attach_target = session.plan_agent_attach_target
        if attach_target is None:
            return None
        session.plan_agent_attach_target = None
        attach_code = attach_plan_agent_terminal(self.runtime, attach_target)
        if attach_code != 0:
            self._print_headless_plan_session_summary(session, attach_target=attach_target)
            return 0
        return attach_code

    def _print_headless_plan_session_summary(self, session: StartupSession, *, attach_target: object | None = None) -> None:
        resolved_target = attach_target or session.plan_agent_attach_target
        if resolved_target is None:
            return
        session_name = str(getattr(resolved_target, "session_name", "")).strip()
        attach_parts: tuple[str, ...]
        if session_name:
            attach_parts = ("tmux", "attach-session", "-t", session_name)
        else:
            attach_parts = tuple(
                str(part).strip() for part in getattr(resolved_target, "attach_command", ()) if str(part).strip()
            )
        attach_command = shlex.join(attach_parts) if attach_parts else ""
        if attach_command:
            print(f"attach: {attach_command}")
        if session_name:
            print(f"kill: tmux kill-session -t {shlex.quote(session_name)}")

    def _finalize_failure(self, session: StartupSession, error: str) -> int:
        rt = self.runtime
        self._ensure_run_id(session)
        port_allocator = port_allocator_impl(rt)
        if "no free port found" in error.lower():
            final_error = f"Port reservation failed: {error}"
        elif error.startswith("Startup failed:"):
            final_error = error
        else:
            final_error = f"Startup failed: {error}"
        session.failure_message = final_error
        session.errors.append(final_error)
        failure_payload: dict[str, object] = {
            "mode": session.runtime_mode,
            "command": session.effective_route.command,
            "error": final_error,
        }
        if session.strict_truth_failed:
            failure_payload["services"] = sorted(session.merged_services)
        rt._emit("startup.failed", **failure_payload)
        started_services: dict[str, ServiceRecord] = {}
        for project_name in session.started_context_names:
            project_services = session.services_by_project.get(project_name, {})
            started_services.update(project_services)
        if started_services:
            rt._terminate_started_services(started_services)
        port_allocator.release_session()
        run_state = build_failure_run_state(rt, session, final_error)
        artifacts_started = time.monotonic()
        rt._write_artifacts(run_state, session.selected_contexts, errors=session.errors)
        self._emit_phase(session, "artifacts_write", artifacts_started, status="error")
        link_mode = str(rt.env.get("ENVCTL_UI_HYPERLINK_MODE", "")).strip().lower()
        print(
            render_paths_in_terminal_text(
                final_error,
                paths=local_paths_in_text(final_error),
                env=rt.env,
                stream=sys.stdout,
                interactive_tty=(True if link_mode == "on" else None),
            )
        )
        return 1

    def _record_project_startup(
        self,
        session: StartupSession,
        context: ProjectContextLike,
        result: ProjectStartupResult,
    ) -> None:
        session.requirements_by_project[context.name] = result.requirements
        session.services_by_project[context.name] = result.services
        session.started_context_names.append(context.name)

    def _emit_phase(self, session: StartupSession, phase: str, started_at: float, **extra: object) -> None:
        self.runtime._emit(
            "startup.phase",
            command=session.requested_command,
            mode=session.runtime_mode,
            phase=phase,
            duration_ms=round((time.monotonic() - started_at) * 1000.0, 2),
            **extra,
        )

    def _emit_snapshot(self, session: StartupSession, checkpoint: str, **extra: object) -> None:
        if not session.debug_plan_snapshot:
            return
        emit_plan_handoff_snapshot(
            self.runtime._emit,
            env=dict(self.runtime.env),
            checkpoint=checkpoint,
            extra=extra or None,
        )

    def _configured_service_types_for_mode(self, runtime_mode: str) -> list[str]:
        rt = self.runtime
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
        context: ProjectContextLike,
        warnings: list[str],
        route: Route,
        project_spinner_group: object | None,
    ) -> None:
        warning_lines = [str(line).strip() for line in warnings if str(line).strip()]
        if not warning_lines:
            return
        rt = self.runtime
        if project_spinner_group is not None and hasattr(project_spinner_group, "print_detail"):
            for line in warning_lines:
                getattr(project_spinner_group, "print_detail")(context.name, line)
            return
        if self._suppress_progress_output(route):
            for line in warning_lines:
                rt._emit("ui.status", message=line)  # type: ignore[attr-defined]
            return
        link_mode = str(rt.env.get("ENVCTL_UI_HYPERLINK_MODE", "")).strip().lower()
        for line in warning_lines:
            print(
                render_paths_in_terminal_text(
                    line,
                    paths=local_paths_in_text(line),
                    env=rt.env,
                    stream=sys.stdout,
                    interactive_tty=(True if link_mode == "on" else None),
                )
            )

    def _trees_start_selection_required(self, *, route: Route, runtime_mode: str) -> bool:
        return trees_start_selection_required_impl(self, route=route, runtime_mode=runtime_mode)

    def _select_start_tree_projects(
        self, *, route: Route, project_contexts: list[ProjectContextLike]
    ) -> list[ProjectContextLike]:
        return select_start_tree_projects_impl(self, route=route, project_contexts=project_contexts)

    @staticmethod
    def _restart_include_requirements(route: Route) -> bool:
        return _restart_include_requirements_impl(route)

    def start_project_context(
        self,
        *,
        context: ProjectContextLike,
        mode: str,
        route: Route,
        run_id: str,
    ) -> ProjectStartupResult:
        return start_project_context_impl(self, context=context, mode=mode, route=route, run_id=run_id)

    def _requirements_for_restart_context(
        self,
        *,
        context: ProjectContextLike,
        mode: str,
        route: Route | None,
    ) -> RequirementsResult:
        return requirements_for_restart_context_impl(self, context=context, mode=mode, route=route)

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
        context: ProjectContextLike,
        *,
        mode: str,
        route: Route | None = None,
    ) -> RequirementsResult:
        return start_requirements_for_project_impl(self, context, mode=mode, route=route)

    def _requirements_timing_enabled(self, route: Route | None) -> bool:
        return requirements_timing_enabled_impl(self, route)

    def _maybe_prewarm_docker(self, *, route: Route | None, mode: str) -> None:
        return maybe_prewarm_docker_impl(self, route=route, mode=mode)

    def start_project_services(
        self,
        context: ProjectContextLike,
        *,
        requirements: RequirementsResult,
        run_id: str,
        route: Route | None = None,
    ) -> dict[str, ServiceRecord]:
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
    def _process_runtime(runtime: object):
        return process_runtime_impl(runtime)
