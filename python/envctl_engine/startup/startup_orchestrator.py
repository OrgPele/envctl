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

        debug_skip_plan_startup = False
        debug_real_noop_execution = False
        debug_exec_group = "completion"
        debug_service_group = ""
        debug_attach_group = ""
        debug_listener_group = ""
        debug_pid_wait_group = ""
        debug_pid_wait_service = ""
        debug_backend_actual_group = ""
        debug_poststart_truth_group = ""
        debug_orch_groups: set[str] = set()
        debug_tty_groups: set[str] = set()
        debug_branch_groups: set[str] = set()
        debug_preentry_group = ""
        debug_preentry_groups: set[str] = set()
        debug_branch_setup_group = ""
        debug_branch_common_group = ""
        debug_branch_root_group = ""
        debug_branch_shell_group = ""
        debug_preselector_group = ""
        debug_prefix_group = ""
        debug_prefix_tail_group = ""
        debug_post_preentry_group = ""
        if requested_command == "plan":
            raw_skip_plan_startup = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_SKIP_PLAN_STARTUP", "")).strip().lower()
            debug_skip_plan_startup = raw_skip_plan_startup in {"1", "true", "yes", "on"}
            raw_real_noop = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_REAL_NOOP_EXECUTION", "")).strip().lower()
            debug_real_noop_execution = raw_real_noop in {"1", "true", "yes", "on"}
            raw_exec_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_EXEC_GROUP", "")).strip().lower()
            if raw_exec_group in {"requirements", "services", "completion"}:
                debug_exec_group = raw_exec_group
            raw_service_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_SERVICE_GROUP", "")).strip().lower()
            if raw_service_group in {"bootstrap", "launch_attach", "record_merge"}:
                debug_service_group = raw_service_group
            raw_attach_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_ATTACH_GROUP", "")).strip().lower()
            if raw_attach_group in {"process_start", "listener_probe", "attach_merge"}:
                debug_attach_group = raw_attach_group
            raw_listener_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_LISTENER_GROUP", "")).strip().lower()
            if raw_listener_group in {"pid_wait", "port_fallback", "rebound_discovery"}:
                debug_listener_group = raw_listener_group
            raw_pid_wait_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_PID_WAIT_GROUP", "")).strip().lower()
            if raw_pid_wait_group in {"signal_gate", "pid_port_lsof", "tree_port_scan"}:
                debug_pid_wait_group = raw_pid_wait_group
            raw_pid_wait_service = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_PID_WAIT_SERVICE", "")).strip().lower()
            if raw_pid_wait_service in {"backend", "frontend", "both"}:
                debug_pid_wait_service = raw_pid_wait_service
            raw_backend_actual_group = str(
                getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_BACKEND_ACTUAL_GROUP", "")
            ).strip().lower()
            if raw_backend_actual_group in {"request_setup", "detect_call", "resolve_actual"}:
                debug_backend_actual_group = raw_backend_actual_group
            raw_poststart_truth_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_POSTSTART_TRUTH_GROUP", "")).strip().lower()
            if raw_poststart_truth_group in {"pid_wait", "port_fallback", "truth_discovery"}:
                debug_poststart_truth_group = raw_poststart_truth_group
            raw_preselector_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP", "")).strip().lower()
            if raw_preselector_group in {"startup_direct", "dashboard_direct", "command_context"}:
                debug_preselector_group = raw_preselector_group
            raw_preentry_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_PREENTRY_GROUP", "")).strip().lower()
            parsed_preentry_groups = {
                token.strip()
                for token in raw_preentry_group.replace("+", ",").split(",")
                if token.strip()
            }
            valid_preentry_groups = {"branch_setup", "project_loop", "finalize"}
            if parsed_preentry_groups and parsed_preentry_groups.issubset(valid_preentry_groups):
                debug_preentry_groups = parsed_preentry_groups
                if len(debug_preentry_groups) == 1:
                    debug_preentry_group = next(iter(debug_preentry_groups))
            raw_branch_setup_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_BRANCH_GROUP", "")).strip().lower()
            if raw_branch_setup_group in {"policy", "route", "live"}:
                debug_branch_setup_group = raw_branch_setup_group
            raw_branch_common_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_BRANCH_COMMON_GROUP", "")).strip().lower()
            if raw_branch_common_group in {"env_policy", "route_scaffold", "context_setup"}:
                debug_branch_common_group = raw_branch_common_group
            raw_branch_root_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_BRANCH_ROOT_GROUP", "")).strip().lower()
            if raw_branch_root_group in {"entry", "route_context", "tail_live"}:
                debug_branch_root_group = raw_branch_root_group
            raw_branch_shell_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_BRANCH_SHELL_GROUP", "")).strip().lower()
            if raw_branch_shell_group in {"callsite", "emit_shell", "body"}:
                debug_branch_shell_group = raw_branch_shell_group
            raw_prefix_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_PREFIX_GROUP", "")).strip().lower()
            if raw_prefix_group in {"gating_only", "branch_enter_only", "full_prefix"}:
                debug_prefix_group = raw_prefix_group
            raw_prefix_tail_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_PREFIX_TAIL_GROUP", "")).strip().lower()
            if raw_prefix_tail_group in {"dashboard", "snapshot_dashboard", "selector_direct"}:
                debug_prefix_tail_group = raw_prefix_tail_group
            raw_post_preentry_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_POSTPREENTRY_GROUP", "")).strip().lower()
            if raw_post_preentry_group in {"direct_selector", "minimal_dashboard", "full_dashboard"}:
                debug_post_preentry_group = raw_post_preentry_group
            raw_orch_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_ORCH_GROUP", "")).strip().lower()
            debug_orch_groups = {
                token.strip()
                for token in raw_orch_group.replace("+", ",").split(",")
                if token.strip()
            }
            if not debug_orch_groups or "tty" in debug_orch_groups:
                raw_tty_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_TTY_GROUP", "")).strip().lower()
                debug_tty_groups = {
                    token.strip()
                    for token in raw_tty_group.replace("+", ",").split(",")
                    if token.strip()
                }
            if debug_real_noop_execution:
                raw_branch_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_REAL_BRANCH_GROUP", "")).strip().lower()
                debug_branch_groups = {
                    token.strip()
                    for token in raw_branch_group.replace("+", ",").split(",")
                    if token.strip()
                }
            if debug_real_noop_execution:
                rt._emit(
                    "startup.debug_execution_mode",
                    command=route.command,
                    mode=runtime_mode,
                    execution="real_noop_execution",
                    exec_group=debug_exec_group,
                    branch_setup_group=debug_branch_setup_group or None,
                    branch_common_group=debug_branch_common_group or None,
                    branch_root_group=debug_branch_root_group or None,
                    branch_shell_group=debug_branch_shell_group or None,
                    attach_group=debug_attach_group or None,
                    preentry_group=sorted(debug_preentry_groups) or None,
                    prefix_group=debug_prefix_group or None,
                    prefix_tail_group=debug_prefix_tail_group or None,
                    preselector_group=debug_preselector_group or None,
                    orch_group=sorted(debug_orch_groups) or None,
                    tty_group=sorted(debug_tty_groups) or None,
                    branch_group=sorted(debug_branch_groups) or None,
                )
            if debug_skip_plan_startup:
                raw_debug_split_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_SPLIT_GROUP", "")).strip().lower()
                debug_split_groups = {
                    token.strip()
                    for token in raw_debug_split_group.replace("+", ",").split(",")
                    if token.strip()
                }
                rt._emit(
                    "startup.debug_skip",
                    command=route.command,
                    mode=runtime_mode,
                    reason="debug_skip_plan_startup",
                    project_count=len(project_contexts),
                    split_group=sorted(debug_split_groups) or None,
                )
                synthetic_state = self._debug_skip_plan_state(
                    run_id=run_id,
                    runtime_mode=runtime_mode,
                    route=route,
                    project_contexts=project_contexts,
                    split_groups=debug_split_groups,
                )
                if "startup_scaffolding" in debug_split_groups:
                    self._debug_skip_plan_scaffolding(
                        route=route,
                        requested_command=requested_command,
                        runtime_mode=runtime_mode,
                        project_contexts=project_contexts,
                    )
                if "persist_reload" in debug_split_groups:
                    rt._emit(
                        "startup.debug_split_group",
                        command=route.command,
                        group="persist_reload",
                        action="write_reload_state",
                    )
                    rt._write_artifacts(synthetic_state, project_contexts, errors=[])
                    reloaded = rt.state_repository.load_latest(mode=runtime_mode, strict_mode_match=True)
                    if isinstance(reloaded, RunState):
                        synthetic_state = reloaded
                if "emit_output" in debug_split_groups:
                    rt._emit(
                        "startup.debug_split_group",
                        command=route.command,
                        group="emit_output",
                        action="emit_startup_output",
                    )
                    print("+ Startup complete")
                    rt._print_summary(synthetic_state, project_contexts)
                if "handoff" in debug_split_groups:
                    rt._emit(
                        "startup.debug_split_group",
                        command=route.command,
                        group="handoff",
                        action="emit_handoff_events",
                    )
                    rt._emit(
                        "startup.breakdown",
                        command=requested_command,
                        mode=runtime_mode,
                        project_count=len(project_contexts),
                        projects=[context.name for context in project_contexts],
                        total_ms=round((time.monotonic() - startup_started_at) * 1000.0, 2),
                    )
                    rt._emit("ui.status", message="Startup complete; refreshing dashboard...")
                if bool(getattr(route, "flags", {}).get("batch")) or bool(getattr(route, "flags", {}).get("headless")):
                    print("Debug skip plan startup enabled; skipping resume/startup after planning sync.")
                    return 0
                emit_snapshot(
                    "before_dashboard_entry",
                    source="debug_skip_plan_startup",
                    minimal_dashboard=str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_MINIMAL_DASHBOARD", "")).strip().lower() in {"1", "true", "yes", "on"},
                    service_count=len(synthetic_state.services),
                    requirement_count=len(synthetic_state.requirements),
                )
                return rt._run_interactive_dashboard_loop(synthetic_state)

        if debug_prefix_group:
            return self._debug_run_prefix_group(
                group=debug_prefix_group,
                tail_group=debug_prefix_tail_group,
                run_id=run_id,
                requested_command=requested_command,
                runtime_mode=runtime_mode,
                route=route,
                project_contexts=project_contexts,
                emit_phase=emit_phase,
                emit_snapshot=emit_snapshot,
                post_preentry_group=debug_post_preentry_group,
            )

        debug_skip_plan_auto_resume = False
        if requested_command == "plan":
            raw_skip_plan_resume = str(getattr(rt, 'env', {}).get('ENVCTL_DEBUG_SKIP_PLAN_AUTO_RESUME', '')).strip().lower()
            debug_skip_plan_auto_resume = raw_skip_plan_resume in {'1', 'true', 'yes', 'on'}
            if debug_real_noop_execution or debug_preentry_groups:
                debug_skip_plan_auto_resume = True
            if debug_skip_plan_auto_resume:
                rt._emit(
                    'state.auto_resume.skipped',
                    reason=(
                        'debug_preentry_forces_skip_plan_auto_resume'
                        if debug_preentry_groups
                        else 'debug_real_noop_forces_skip_plan_auto_resume'
                        if debug_real_noop_execution and raw_skip_plan_resume not in {'1', 'true', 'yes', 'on'}
                        else 'debug_skip_plan_auto_resume'
                    ),
                    mode=runtime_mode,
                    command=route.command,
                )

        if requested_command != "restart" and rt._auto_resume_start_enabled(route) and not debug_skip_plan_auto_resume:
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
            real_noop_execution=debug_real_noop_execution,
            exec_group=debug_exec_group if debug_real_noop_execution else None,
            orch_group=sorted(debug_orch_groups) or None,
        )
        if debug_preentry_groups:
            if len(debug_preentry_groups) == 1:
                selected_group = next(iter(debug_preentry_groups))
                return self._debug_run_preentry_group(
                    group=selected_group,
                    run_id=run_id,
                    requested_command=requested_command,
                    runtime_mode=runtime_mode,
                    route=route,
                    project_contexts=project_contexts,
                    debug_exec_group=debug_exec_group,
                    debug_branch_setup_group=debug_branch_setup_group,
                    debug_branch_common_group=debug_branch_common_group,
                    debug_branch_root_group=debug_branch_root_group,
                    debug_branch_shell_group=debug_branch_shell_group,
                    startup_started_at=startup_started_at,
                    startup_event_index=startup_event_index,
                    emit_snapshot=emit_snapshot,
                    post_preentry_group=debug_post_preentry_group,
                )
            return self._debug_run_preentry_groups(
                groups=debug_preentry_groups,
                run_id=run_id,
                requested_command=requested_command,
                runtime_mode=runtime_mode,
                route=route,
                project_contexts=project_contexts,
                debug_exec_group=debug_exec_group,
                debug_branch_setup_group=debug_branch_setup_group,
                debug_branch_common_group=debug_branch_common_group,
                debug_branch_root_group=debug_branch_root_group,
                debug_branch_shell_group=debug_branch_shell_group,
                startup_started_at=startup_started_at,
                startup_event_index=startup_event_index,
                emit_snapshot=emit_snapshot,
                post_preentry_group=debug_post_preentry_group,
            )
        if debug_preentry_group:
            return self._debug_run_preentry_group(
                group=debug_preentry_group,
                run_id=run_id,
                requested_command=requested_command,
                runtime_mode=runtime_mode,
                route=route,
                project_contexts=project_contexts,
                debug_exec_group=debug_exec_group,
                debug_branch_setup_group=debug_branch_setup_group,
                debug_branch_common_group=debug_branch_common_group,
                debug_branch_root_group=debug_branch_root_group,
                debug_branch_shell_group=debug_branch_shell_group,
                startup_started_at=startup_started_at,
                startup_event_index=startup_event_index,
                emit_snapshot=emit_snapshot,
            )

        services = {}
        requirements: dict[str, RequirementsResult] = {}
        started_contexts: list[Any] = []
        errors: list[str] = []
        branch_entry_enabled = not debug_branch_groups or "entry" in debug_branch_groups
        branch_loop_enabled = not debug_branch_groups or "loop" in debug_branch_groups
        branch_dashboard_enabled = not debug_branch_groups or "dashboard" in debug_branch_groups
        spinner_message = f"Starting {len(project_contexts)} project(s)..."
        spinner_policy = resolve_spinner_policy(getattr(rt, "env", {}))
        use_startup_spinner = spinner_policy.enabled and not self._suppress_progress_output(route)
        if debug_orch_groups and "threads" not in debug_orch_groups:
            use_startup_spinner = False
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
        if debug_orch_groups and "threads" not in debug_orch_groups:
            parallel_enabled = False
            parallel_workers = 1
        if branch_entry_enabled:
            rt._emit(
                "startup.execution",
                mode="parallel" if parallel_enabled else "sequential",
                workers=parallel_workers,
                projects=[context.name for context in project_contexts],
            )
            prewarm_started = time.monotonic()
            self._maybe_prewarm_docker(route=route, mode=runtime_mode)
            emit_phase("docker_prewarm", prewarm_started, status="ok")
        else:
            use_startup_spinner = False
            parallel_enabled = False
            parallel_workers = 1
            rt._emit(
                "startup.debug_branch_group",
                group="entry",
                action="bypass",
                command=requested_command,
            )
        debug_suppress_plan_progress = bool(
            requested_command == "plan"
            and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_SUPPRESS_PLAN_PROGRESS", "")).strip().lower() in {"1", "true", "yes", "on"}
        )
        if debug_orch_groups and "tty" not in debug_orch_groups:
            debug_suppress_plan_progress = True
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
                "_debug_real_noop_execution": debug_real_noop_execution,
                "_debug_exec_group": debug_exec_group,
                "_debug_service_group": debug_service_group,
                "_debug_attach_group": debug_attach_group,
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

        if branch_loop_enabled:
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
        else:
            rt._emit(
                "startup.debug_branch_group",
                group="loop",
                action="bypass",
                command=requested_command,
            )
            synthetic_loop_state = self._debug_skip_plan_state(
                run_id=run_id,
                runtime_mode=runtime_mode,
                route=route,
                project_contexts=project_contexts,
                split_groups={"state_shape"},
            )
            services = dict(synthetic_loop_state.services)
            requirements = dict(synthetic_loop_state.requirements)
            started_contexts = list(project_contexts)

        if preserved_services:
            services = {**preserved_services, **services}
        if preserved_requirements:
            requirements = {**preserved_requirements, **requirements}

        debug_skip_plan_post_reconcile = bool(
            requested_command == "plan"
            and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_SKIP_PLAN_POST_RECONCILE", "")).strip().lower() in {"1", "true", "yes", "on"}
        )
        debug_skip_plan_artifacts = bool(
            requested_command == "plan"
            and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_SKIP_PLAN_ARTIFACTS", "")).strip().lower() in {"1", "true", "yes", "on"}
        )
        debug_skip_plan_summary = bool(
            requested_command == "plan"
            and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_SKIP_PLAN_SUMMARY", "")).strip().lower() in {"1", "true", "yes", "on"}
        )
        if debug_orch_groups and "transition" not in debug_orch_groups:
            debug_skip_plan_summary = True

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

        if rt.config.runtime_truth_mode == "strict" and not debug_skip_plan_post_reconcile:
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

        if not branch_dashboard_enabled:
            rt._emit(
                "startup.debug_branch_group",
                group="dashboard",
                action="bypass",
                command=requested_command,
            )
            emit_snapshot(
                "before_dashboard_entry",
                source="startup_branch_dashboard_bypass",
                command=requested_command,
                mode=runtime_mode,
                service_count=len(run_state.services),
                requirement_count=len(run_state.requirements),
                real_noop_execution=debug_real_noop_execution,
                exec_group=debug_exec_group if debug_real_noop_execution else None,
            )
            return rt._run_interactive_dashboard_loop(
                self._debug_skip_plan_state(
                    run_id=run_id,
                    runtime_mode=runtime_mode,
                    route=route,
                    project_contexts=project_contexts,
                    split_groups=set(),
                )
            )

        if debug_skip_plan_artifacts:
            rt._emit("artifacts.debug_skip", command=requested_command, reason="debug_skip_plan_artifacts")
        else:
            artifacts_started = time.monotonic()
            rt._write_artifacts(run_state, project_contexts, errors=errors)
            emit_phase("artifacts_write", artifacts_started, status="ok")
        if not debug_skip_plan_summary and self._requirements_timing_enabled(route) and not self._suppress_timing_output(route):
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
        if self._startup_breakdown_enabled(route) and not (debug_orch_groups and "transition" not in debug_orch_groups):
            rt._emit(
                "startup.breakdown",
                command=requested_command,
                mode=runtime_mode,
                project_count=len(project_contexts),
                projects=[context.name for context in project_contexts],
                total_ms=round((time.monotonic() - startup_started_at) * 1000.0, 2),
            )
        tty_output_enabled = not debug_tty_groups or "output" in debug_tty_groups
        rt._emit(
            "startup.debug_tty_group",
            component="startup_orchestrator",
            group="output",
            action="dashboard_summary_or_status",
            enabled=tty_output_enabled,
            detail="startup_branch",
        )
        if not self._suppress_progress_output(route) and not (
            debug_orch_groups and ("tty" not in debug_orch_groups or not tty_output_enabled)
        ):
            if not use_project_spinner_group and not debug_skip_plan_summary:
                rt._print_summary(run_state, project_contexts)
        else:
            if tty_output_enabled:
                rt._emit("ui.status", message="Startup complete; refreshing dashboard...")  # type: ignore[attr-defined]
        emit_snapshot(
            "before_dashboard_entry",
            source="startup_branch",
            command=requested_command,
            mode=runtime_mode,
            service_count=len(run_state.services),
            requirement_count=len(run_state.requirements),
            real_noop_execution=debug_real_noop_execution,
            exec_group=debug_exec_group if debug_real_noop_execution else None,
        )
        if debug_preselector_group == "startup_direct":
            rt._emit(
                "startup.debug_preselector_group",
                command=requested_command,
                group=debug_preselector_group,
                action="direct_selector_before_dashboard",
            )
            from envctl_engine.ui.command_loop import _open_debug_grouped_selector

            previous_selector = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_SELECTOR_GROUP", ""))
            try:
                rt.env["ENVCTL_DEBUG_PLAN_SELECTOR_GROUP"] = "standalone_child"
                _open_debug_grouped_selector(rt, run_state)
                return 0
            finally:
                if previous_selector:
                    rt.env["ENVCTL_DEBUG_PLAN_SELECTOR_GROUP"] = previous_selector
                else:
                    rt.env.pop("ENVCTL_DEBUG_PLAN_SELECTOR_GROUP", None)
        if rt._should_enter_post_start_interactive(route):
            if debug_preselector_group in {"dashboard_direct", "command_context"}:
                previous_postloop = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_POSTLOOP_GROUP", ""))
                previous_selector = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_SELECTOR_GROUP", ""))
                try:
                    rt._emit(
                        "startup.debug_preselector_group",
                        command=requested_command,
                        group=debug_preselector_group,
                        action="dashboard_loop_override",
                    )
                    if debug_preselector_group == "dashboard_direct":
                        rt.env["ENVCTL_DEBUG_PLAN_POSTLOOP_GROUP"] = "direct_selector"
                        rt.env["ENVCTL_DEBUG_PLAN_SELECTOR_GROUP"] = "standalone_child"
                    else:
                        rt.env.pop("ENVCTL_DEBUG_PLAN_POSTLOOP_GROUP", None)
                        rt.env["ENVCTL_DEBUG_PLAN_SELECTOR_GROUP"] = "standalone_child"
                    return rt._run_interactive_dashboard_loop(run_state)
                finally:
                    if previous_postloop:
                        rt.env["ENVCTL_DEBUG_PLAN_POSTLOOP_GROUP"] = previous_postloop
                    else:
                        rt.env.pop("ENVCTL_DEBUG_PLAN_POSTLOOP_GROUP", None)
                    if previous_selector:
                        rt.env["ENVCTL_DEBUG_PLAN_SELECTOR_GROUP"] = previous_selector
                    else:
                        rt.env.pop("ENVCTL_DEBUG_PLAN_SELECTOR_GROUP", None)
            return rt._run_interactive_dashboard_loop(run_state)
        return 0

    @staticmethod
    def _project_ports_text(context: Any) -> str:
        return _project_ports_text_impl(context)

    def _debug_skip_plan_state(
        self,
        *,
        run_id: str,
        runtime_mode: str,
        route: Route,
        project_contexts: list[Any],
        split_groups: set[str],
    ) -> RunState:
        rt: Any = self.runtime
        synthetic_services: dict[str, ServiceRecord] = {}
        synthetic_requirements: dict[str, RequirementsResult] = {}
        profile_for_mode = getattr(rt.config, "profile_for_mode", None)
        profile = profile_for_mode(runtime_mode) if callable(profile_for_mode) else None
        backend_enabled = bool(getattr(profile, "backend_enable", True))
        frontend_enabled = bool(getattr(profile, "frontend_enable", True))
        richer_state = "state_shape" in split_groups
        dependency_map = {definition.id: definition for definition in dependency_definitions()}
        for context in project_contexts:
            if backend_enabled:
                backend_name = f"{context.name} Backend"
                backend_port = int(getattr(context.ports.get("backend"), "final", 0) or 0)
                synthetic_services[backend_name] = ServiceRecord(
                    name=backend_name,
                    type="backend",
                    cwd=str(context.root),
                    requested_port=backend_port or None,
                    actual_port=backend_port or None if richer_state else None,
                    status="running" if richer_state else "unknown",
                    synthetic=True,
                )
            if frontend_enabled:
                frontend_name = f"{context.name} Frontend"
                frontend_port = int(getattr(context.ports.get("frontend"), "final", 0) or 0)
                synthetic_services[frontend_name] = ServiceRecord(
                    name=frontend_name,
                    type="frontend",
                    cwd=str(context.root),
                    requested_port=frontend_port or None,
                    actual_port=frontend_port or None if richer_state else None,
                    status="running" if richer_state else "unknown",
                    synthetic=True,
                )
            if richer_state:
                components: dict[str, dict[str, Any]] = {}
                for dependency_id, definition in dependency_map.items():
                    resource = definition.resources[0]
                    plan = context.ports.get(resource.legacy_port_key)
                    final_port = int(getattr(plan, "final", 0) or 0) if plan is not None else 0
                    enabled = bool(getattr(profile, "dependency_enabled", lambda _x: True)(dependency_id))
                    components[dependency_id] = {
                        "enabled": enabled,
                        "success": enabled,
                        "health": "healthy" if enabled else "disabled",
                        "requested_port": final_port or None,
                        "final_port": final_port or None,
                        "resources": {"primary": final_port or None},
                    }
                synthetic_requirements[context.name] = RequirementsResult(
                    project=context.name,
                    components=components,
                    health="healthy",
                    failures=[],
                )
        metadata: dict[str, Any] = {
            "command": route.command,
            "debug_skip_plan_startup": True,
            "repo_scope_id": rt.config.runtime_scope_id,
            "project_roots": {context.name: str(context.root) for context in project_contexts},
        }
        if split_groups:
            metadata["debug_split_group"] = sorted(split_groups)
        if richer_state:
            metadata["debug_state_shape"] = "startup_like"
        return RunState(
            run_id=run_id,
            mode=runtime_mode,
            services=synthetic_services,
            requirements=synthetic_requirements,
            metadata=metadata,
        )

    def _debug_skip_plan_scaffolding(
        self,
        *,
        route: Route,
        requested_command: str,
        runtime_mode: str,
        project_contexts: list[Any],
        root_group: str = "",
        branch_group: str = "",
        common_group: str = "",
        shell_group: str = "",
    ) -> None:
        rt: Any = self.runtime
        body_enabled = not shell_group or shell_group == "body"
        root_entry_enabled = not root_group or root_group == "entry"
        root_route_context_enabled = not root_group or root_group == "route_context"
        root_tail_live_enabled = not root_group or root_group == "tail_live"
        policy_enabled = not branch_group or branch_group == "policy"
        route_enabled = not branch_group or branch_group == "route"
        live_enabled = not branch_group or branch_group == "live"
        common_env_enabled = not common_group or common_group == "env_policy"
        common_route_enabled = not common_group or common_group == "route_scaffold"
        common_context_enabled = not common_group or common_group == "context_setup"
        rt._emit(
            "startup.debug_branch_setup_group",
            command=route.command,
            group=branch_group or "all",
            root_group=root_group or None,
            common_group=common_group or None,
            root_entry_enabled=root_entry_enabled,
            root_route_context_enabled=root_route_context_enabled,
            root_tail_live_enabled=root_tail_live_enabled,
            shell_group=shell_group or None,
            body_enabled=body_enabled,
            policy_enabled=policy_enabled,
            route_enabled=route_enabled,
            live_enabled=live_enabled,
            common_env_enabled=common_env_enabled,
            common_route_enabled=common_route_enabled,
            common_context_enabled=common_context_enabled,
        )
        if shell_group == "emit_shell":
            rt._emit(
                "startup.debug_branch_shell_group",
                command=route.command,
                shell_group="emit_shell",
                action="return_after_initial_emit",
            )
            return
        spinner_message = f"Starting {len(project_contexts)} project(s)..."
        spinner_policy = resolve_spinner_policy(getattr(rt, "env", {})) if root_entry_enabled and common_env_enabled else resolve_spinner_policy({})
        use_startup_spinner = bool(root_entry_enabled and common_env_enabled and spinner_policy.enabled and not self._suppress_progress_output(route))
        if root_entry_enabled and policy_enabled:
            emit_spinner_policy(
                getattr(rt, "_emit", None),
                spinner_policy,
                context={"component": "startup_orchestrator", "op_id": "startup.execute.debug_skip"},
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
                debug_skip_plan_scaffolding=True,
                debug_branch_setup_group=branch_group or None,
            )
        else:
            parallel_enabled = False
            parallel_workers = 1
            rt._emit(
                "startup.debug_branch_setup_group",
                command=route.command,
                group=branch_group or "all",
                root_group=root_group or None,
                common_group=common_group or None,
                action="skip_entry",
            )
        if root_route_context_enabled and route_enabled and common_route_enabled:
            self._maybe_prewarm_docker(route=route, mode=runtime_mode)
        else:
            rt._emit(
                "startup.debug_branch_setup_group",
                command=route.command,
                group=branch_group or "all",
                root_group=root_group or None,
                common_group=common_group or None,
                action="skip_route_context",
            )
        if root_route_context_enabled and common_route_enabled:
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
        else:
            route_for_execution = Route(
                command=route.command,
                mode=route.mode,
                raw_args=route.raw_args,
                passthrough_args=route.passthrough_args,
                projects=route.projects,
                flags={**route.flags},
            )
        use_project_spinner_group = (
            root_route_context_enabled
            and common_context_enabled
            and parallel_enabled
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
            op_id="startup.execute.debug_skip",
            env=getattr(rt, "env", {}),
        ) if root_route_context_enabled and common_context_enabled else nullcontext(None)
        use_single_spinner = use_startup_spinner and not use_project_spinner_group
        group_context = project_spinner_group if use_project_spinner_group else nullcontext(project_spinner_group)
        if root_tail_live_enabled and live_enabled and common_context_enabled:
            with use_spinner_policy(spinner_policy), spinner(
                spinner_message,
                enabled=use_single_spinner,
            ) as active_spinner:
                if use_single_spinner:
                    route_for_execution.flags["_spinner_update"] = active_spinner.update
                    rt._emit(
                        "ui.spinner.lifecycle",
                        component="startup_orchestrator",
                        op_id="startup.execute.debug_skip",
                        state="start",
                        message=spinner_message,
                    )
                    active_spinner.succeed("Startup complete")
                    rt._emit(
                        "ui.spinner.lifecycle",
                        component="startup_orchestrator",
                        op_id="startup.execute.debug_skip",
                        state="success",
                        message="Startup complete",
                    )
                    rt._emit(
                        "ui.spinner.lifecycle",
                        component="startup_orchestrator",
                        op_id="startup.execute.debug_skip",
                        state="stop",
                    )
                if use_project_spinner_group:
                    route_for_execution.flags["_spinner_update_project"] = project_spinner_group.update_project
                with group_context:
                    pass
        else:
            rt._emit(
                "startup.debug_branch_setup_group",
                command=route.command,
                group=branch_group or "all",
                root_group=root_group or None,
                common_group=common_group or None,
                action="skip_tail_live",
            )
        if root_tail_live_enabled:
            rt._emit(
                "startup.debug_split_group",
                command=route.command,
                group="startup_scaffolding",
                action="complete",
                use_startup_spinner=use_startup_spinner,
                use_project_spinner_group=use_project_spinner_group,
                debug_branch_root_group=root_group or None,
                debug_branch_setup_group=branch_group or None,
                debug_branch_common_group=common_group or None,
            )

    def _debug_build_loop_route(
        self,
        *,
        route: Route,
        command: str,
        exec_group: str,
    ) -> Route:
        rt: Any = self.runtime
        requested_command = route.command
        debug_suppress_plan_progress = bool(
            requested_command == "plan"
            and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_SUPPRESS_PLAN_PROGRESS", "")).strip().lower() in {"1", "true", "yes", "on"}
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
                "_debug_real_noop_execution": True,
                "_debug_exec_group": exec_group,
                "_debug_service_group": (
                    str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_SERVICE_GROUP", "")).strip().lower()
                    if exec_group == "services"
                    else ""
                ),
                "_debug_attach_group": (
                    str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_ATTACH_GROUP", "")).strip().lower()
                    if exec_group == "services"
                    and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_SERVICE_GROUP", "")).strip().lower() == "launch_attach"
                    else ""
                ),
                "_debug_listener_group": (
                    str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_LISTENER_GROUP", "")).strip().lower()
                    if exec_group == "services"
                    and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_SERVICE_GROUP", "")).strip().lower() == "launch_attach"
                    and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_ATTACH_GROUP", "")).strip().lower() == "listener_probe"
                    else ""
                ),
                "_debug_pid_wait_group": (
                    str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_PID_WAIT_GROUP", "")).strip().lower()
                    if exec_group == "services"
                    and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_SERVICE_GROUP", "")).strip().lower() == "launch_attach"
                    and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_ATTACH_GROUP", "")).strip().lower() == "listener_probe"
                    and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_LISTENER_GROUP", "")).strip().lower() == "pid_wait"
                    else ""
                ),
                "_debug_pid_wait_service": (
                    str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_PID_WAIT_SERVICE", "")).strip().lower()
                    if exec_group == "services"
                    and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_SERVICE_GROUP", "")).strip().lower() == "launch_attach"
                    and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_ATTACH_GROUP", "")).strip().lower() == "listener_probe"
                    and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_LISTENER_GROUP", "")).strip().lower() == "pid_wait"
                    else ""
                ),
                "_debug_backend_actual_group": (
                    str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_BACKEND_ACTUAL_GROUP", "")).strip().lower()
                    if exec_group == "services"
                    and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_SERVICE_GROUP", "")).strip().lower() == "launch_attach"
                    and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_ATTACH_GROUP", "")).strip().lower() == "listener_probe"
                    and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_LISTENER_GROUP", "")).strip().lower() == "pid_wait"
                    and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_PID_WAIT_SERVICE", "")).strip().lower() == "backend"
                    else ""
                ),
                "_debug_poststart_truth_group": (
                    str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_POSTSTART_TRUTH_GROUP", "")).strip().lower()
                    if exec_group == "services"
                    and str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_SERVICE_GROUP", "")).strip().lower() == "launch_attach"
                    else ""
                ),
                "_debug_preentry_group": command,
            },
        )

    def _debug_run_project_loop_bundle(
        self,
        *,
        project_contexts: list[Any],
        runtime_mode: str,
        route_for_execution: Route,
        run_id: str,
    ) -> tuple[dict[str, Any], dict[str, RequirementsResult], list[Any], list[str]]:
        rt: Any = self.runtime
        services: dict[str, Any] = {}
        requirements: dict[str, RequirementsResult] = {}
        started_contexts: list[Any] = []
        errors: list[str] = []
        for context in project_contexts:
            try:
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
                errors.append(str(exc))
                rt._emit("startup.project.failed", project=context.name, error=str(exc), debug_preentry_group="project_loop")
        return services, requirements, started_contexts, errors

    def _debug_make_run_state(
        self,
        *,
        run_id: str,
        runtime_mode: str,
        route: Route,
        project_contexts: list[Any],
        services: dict[str, Any],
        requirements: dict[str, RequirementsResult],
        metadata_extra: dict[str, Any] | None = None,
    ) -> RunState:
        rt: Any = self.runtime
        metadata: dict[str, Any] = {
            "command": route.command,
            "repo_scope_id": rt.config.runtime_scope_id,
            "project_roots": {context.name: str(context.root) for context in project_contexts},
        }
        if metadata_extra:
            metadata.update(metadata_extra)
        run_state = RunState(
            run_id=run_id,
            mode=runtime_mode,
            services=services,
            requirements=requirements,
            pointers={},
            metadata=metadata,
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
        return run_state


    def _debug_run_post_preentry_tail(
        self,
        *,
        run_state: RunState,
        requested_command: str,
        runtime_mode: str,
        emit_snapshot: Any,
        source: str,
        group_payload: dict[str, Any],
        post_preentry_group: str,
    ) -> int:
        rt: Any = self.runtime
        from envctl_engine.ui.command_loop import _open_debug_grouped_selector

        tail_group = post_preentry_group or "direct_selector"
        preselector_group = str(getattr(rt, "env", {}).get("ENVCTL_DEBUG_PLAN_PRESELECTOR_GROUP", "")).strip().lower()
        if preselector_group not in {"startup_direct", "dashboard_direct", "command_context"}:
            preselector_group = ""
        emit_snapshot(
            "before_dashboard_entry",
            source=source,
            command=requested_command,
            mode=runtime_mode,
            service_count=len(run_state.services),
            requirement_count=len(run_state.requirements),
            **group_payload,
            debug_post_preentry_group=tail_group,
        )
        rt._emit(
            "startup.debug_post_preentry_group",
            command=requested_command,
            action="enter",
            group=tail_group,
            **group_payload,
        )
        env = getattr(rt, "env", None)
        if preselector_group == "startup_direct":
            rt._emit(
                "startup.debug_preselector_group",
                command=requested_command,
                group=preselector_group,
                action="direct_selector_before_dashboard",
                **group_payload,
            )
            previous_selector = ""
            if isinstance(env, dict):
                previous_selector = str(env.get("ENVCTL_DEBUG_PLAN_SELECTOR_GROUP", ""))
                env["ENVCTL_DEBUG_PLAN_SELECTOR_GROUP"] = "standalone_child"
            try:
                _open_debug_grouped_selector(rt, run_state)
                return 0
            finally:
                if isinstance(env, dict):
                    if previous_selector:
                        env["ENVCTL_DEBUG_PLAN_SELECTOR_GROUP"] = previous_selector
                    else:
                        env.pop("ENVCTL_DEBUG_PLAN_SELECTOR_GROUP", None)
        if tail_group in {"minimal_dashboard", "full_dashboard"} and preselector_group in {"dashboard_direct", "command_context"}:
            previous_postloop = ""
            previous_selector = ""
            previous_minimal_dashboard = ""
            if isinstance(env, dict):
                previous_postloop = str(env.get("ENVCTL_DEBUG_PLAN_POSTLOOP_GROUP", ""))
                previous_selector = str(env.get("ENVCTL_DEBUG_PLAN_SELECTOR_GROUP", ""))
                previous_minimal_dashboard = str(env.get("ENVCTL_DEBUG_MINIMAL_DASHBOARD", ""))
            try:
                rt._emit(
                    "startup.debug_preselector_group",
                    command=requested_command,
                    group=preselector_group,
                    action="dashboard_loop_override",
                    **group_payload,
                )
                if isinstance(env, dict):
                    if preselector_group == "dashboard_direct":
                        env["ENVCTL_DEBUG_PLAN_POSTLOOP_GROUP"] = "direct_selector"
                    else:
                        env.pop("ENVCTL_DEBUG_PLAN_POSTLOOP_GROUP", None)
                    env["ENVCTL_DEBUG_PLAN_SELECTOR_GROUP"] = "standalone_child"
                    if tail_group == "minimal_dashboard":
                        env["ENVCTL_DEBUG_MINIMAL_DASHBOARD"] = "1"
                return rt._run_interactive_dashboard_loop(run_state)
            finally:
                if isinstance(env, dict):
                    if previous_postloop:
                        env["ENVCTL_DEBUG_PLAN_POSTLOOP_GROUP"] = previous_postloop
                    else:
                        env.pop("ENVCTL_DEBUG_PLAN_POSTLOOP_GROUP", None)
                    if previous_selector:
                        env["ENVCTL_DEBUG_PLAN_SELECTOR_GROUP"] = previous_selector
                    else:
                        env.pop("ENVCTL_DEBUG_PLAN_SELECTOR_GROUP", None)
                    if tail_group == "minimal_dashboard":
                        if previous_minimal_dashboard:
                            env["ENVCTL_DEBUG_MINIMAL_DASHBOARD"] = previous_minimal_dashboard
                        else:
                            env.pop("ENVCTL_DEBUG_MINIMAL_DASHBOARD", None)
        if tail_group == "minimal_dashboard":
            previous_minimal_dashboard = ""
            if isinstance(env, dict):
                previous_minimal_dashboard = str(env.get("ENVCTL_DEBUG_MINIMAL_DASHBOARD", ""))
                env["ENVCTL_DEBUG_MINIMAL_DASHBOARD"] = "1"
            try:
                return rt._run_interactive_dashboard_loop(run_state)
            finally:
                if isinstance(env, dict):
                    if previous_minimal_dashboard:
                        env["ENVCTL_DEBUG_MINIMAL_DASHBOARD"] = previous_minimal_dashboard
                    else:
                        env.pop("ENVCTL_DEBUG_MINIMAL_DASHBOARD", None)
        if tail_group == "full_dashboard":
            return rt._run_interactive_dashboard_loop(run_state)
        print("DEBUG DIRECT SELECTOR MODE (no dashboard). Do not press t.")
        rt._emit(
            "startup.debug_post_preentry_group",
            command=requested_command,
            action="direct_selector_mode",
            group=tail_group,
            **group_payload,
        )
        previous_selector_group = ""
        if isinstance(env, dict):
            previous_selector_group = str(env.get("ENVCTL_DEBUG_PLAN_SELECTOR_GROUP", ""))
            env["ENVCTL_DEBUG_PLAN_SELECTOR_GROUP"] = "standalone_child"
        try:
            _open_debug_grouped_selector(rt, run_state)
        finally:
            if isinstance(env, dict):
                if previous_selector_group:
                    env["ENVCTL_DEBUG_PLAN_SELECTOR_GROUP"] = previous_selector_group
                else:
                    env.pop("ENVCTL_DEBUG_PLAN_SELECTOR_GROUP", None)
        return 0

    def _debug_run_preentry_group(
        self,
        *,
        group: str,
        run_id: str,
        requested_command: str,
        runtime_mode: str,
        route: Route,
        project_contexts: list[Any],
        debug_exec_group: str,
        debug_branch_setup_group: str,
        debug_branch_common_group: str,
        debug_branch_root_group: str,
        debug_branch_shell_group: str,
        startup_started_at: float,
        startup_event_index: int,
        emit_snapshot: Any,
        post_preentry_group: str,
    ) -> int:
        rt: Any = self.runtime
        from envctl_engine.ui.command_loop import _open_debug_grouped_selector

        rt._emit(
            "startup.debug_preentry_group",
            command=requested_command,
            group=group,
            action="enter",
        )
        if group == "branch_setup":
            if debug_branch_shell_group == "callsite":
                rt._emit(
                    "startup.debug_branch_shell_group",
                    command=requested_command,
                    shell_group="callsite",
                    action="skip_scaffolding_call",
                )
            else:
                self._debug_skip_plan_scaffolding(
                    route=route,
                    requested_command=requested_command,
                    runtime_mode=runtime_mode,
                    project_contexts=project_contexts,
                    root_group=debug_branch_root_group,
                    branch_group=debug_branch_setup_group,
                    common_group=debug_branch_common_group,
                    shell_group=debug_branch_shell_group,
                )
            run_state = self._debug_skip_plan_state(
                run_id=run_id,
                runtime_mode=runtime_mode,
                route=route,
                project_contexts=project_contexts,
                split_groups=set(),
            )
        elif group == "project_loop":
            route_for_execution = self._debug_build_loop_route(
                route=route,
                command=group,
                exec_group=debug_exec_group,
            )
            services, requirements, _started_contexts, errors = self._debug_run_project_loop_bundle(
                project_contexts=project_contexts,
                runtime_mode=runtime_mode,
                route_for_execution=route_for_execution,
                run_id=run_id,
            )
            run_state = self._debug_make_run_state(
                run_id=run_id,
                runtime_mode=runtime_mode,
                route=route,
                project_contexts=project_contexts,
                services=services,
                requirements=requirements,
                metadata_extra={
                    "debug_preentry_group": group,
                    "debug_errors": list(errors),
                },
            )
        else:
            synthetic_loop_state = self._debug_skip_plan_state(
                run_id=run_id,
                runtime_mode=runtime_mode,
                route=route,
                project_contexts=project_contexts,
                split_groups={"state_shape"},
            )
            run_state = self._debug_make_run_state(
                run_id=run_id,
                runtime_mode=runtime_mode,
                route=route,
                project_contexts=project_contexts,
                services=dict(synthetic_loop_state.services),
                requirements=dict(synthetic_loop_state.requirements),
                metadata_extra={
                    "debug_preentry_group": group,
                    "debug_state_shape": "startup_like",
                },
            )
            artifacts_started = time.monotonic()
            rt._write_artifacts(run_state, project_contexts, errors=[])
            rt._emit(
                "startup.phase",
                command=requested_command,
                mode=runtime_mode,
                phase="artifacts_write",
                duration_ms=round((time.monotonic() - artifacts_started) * 1000.0, 2),
                status="ok",
                debug_preentry_group=group,
            )
            if self._requirements_timing_enabled(route) and not self._suppress_timing_output(route):
                self._print_startup_summary(
                    project_contexts=project_contexts,
                    start_event_index=startup_event_index,
                    startup_started_at=startup_started_at,
                )
            rt._emit(
                "startup.breakdown",
                command=requested_command,
                mode=runtime_mode,
                project_count=len(project_contexts),
                projects=[context.name for context in project_contexts],
                total_ms=round((time.monotonic() - startup_started_at) * 1000.0, 2),
                debug_preentry_group=group,
            )
            rt._emit("ui.status", message="Startup complete; refreshing dashboard...", debug_preentry_group=group)
        return self._debug_run_post_preentry_tail(
            run_state=run_state,
            requested_command=requested_command,
            runtime_mode=runtime_mode,
            emit_snapshot=emit_snapshot,
            source=f"debug_preentry_{group}",
            group_payload={"debug_preentry_group": group},
            post_preentry_group=post_preentry_group,
        )

    def _debug_run_preentry_groups(
        self,
        *,
        groups: set[str],
        run_id: str,
        requested_command: str,
        runtime_mode: str,
        route: Route,
        project_contexts: list[Any],
        debug_exec_group: str,
        debug_branch_setup_group: str,
        debug_branch_common_group: str,
        debug_branch_root_group: str,
        debug_branch_shell_group: str,
        startup_started_at: float,
        startup_event_index: int,
        emit_snapshot: Any,
        post_preentry_group: str,
    ) -> int:
        rt: Any = self.runtime
        from envctl_engine.ui.command_loop import _open_debug_grouped_selector

        selected_groups = sorted(groups)
        rt._emit(
            "startup.debug_preentry_group",
            command=requested_command,
            groups=selected_groups,
            action="enter_combo",
        )

        if "branch_setup" in groups:
            self._debug_skip_plan_scaffolding(
                route=route,
                requested_command=requested_command,
                runtime_mode=runtime_mode,
                project_contexts=project_contexts,
                root_group=debug_branch_root_group,
                branch_group=debug_branch_setup_group,
                common_group=debug_branch_common_group,
                shell_group=debug_branch_shell_group,
            )

        if "project_loop" in groups:
            route_for_execution = self._debug_build_loop_route(
                route=route,
                command="project_loop",
                exec_group=debug_exec_group,
            )
            services, requirements, _started_contexts, errors = self._debug_run_project_loop_bundle(
                project_contexts=project_contexts,
                runtime_mode=runtime_mode,
                route_for_execution=route_for_execution,
                run_id=run_id,
            )
        else:
            synthetic_loop_state = self._debug_skip_plan_state(
                run_id=run_id,
                runtime_mode=runtime_mode,
                route=route,
                project_contexts=project_contexts,
                split_groups={"state_shape"},
            )
            services = dict(synthetic_loop_state.services)
            requirements = dict(synthetic_loop_state.requirements)
            errors = []

        run_state = self._debug_make_run_state(
            run_id=run_id,
            runtime_mode=runtime_mode,
            route=route,
            project_contexts=project_contexts,
            services=services,
            requirements=requirements,
            metadata_extra={
                "debug_preentry_groups": selected_groups,
                "debug_state_shape": "startup_like" if "project_loop" not in groups else None,
                "debug_errors": list(errors),
            },
        )

        if "finalize" in groups:
            artifacts_started = time.monotonic()
            rt._write_artifacts(run_state, project_contexts, errors=[])
            rt._emit(
                "startup.phase",
                command=requested_command,
                mode=runtime_mode,
                phase="artifacts_write",
                duration_ms=round((time.monotonic() - artifacts_started) * 1000.0, 2),
                status="ok",
                debug_preentry_groups=selected_groups,
            )
            if self._requirements_timing_enabled(route) and not self._suppress_timing_output(route):
                self._print_startup_summary(
                    project_contexts=project_contexts,
                    start_event_index=startup_event_index,
                    startup_started_at=startup_started_at,
                )
            rt._emit(
                "startup.breakdown",
                command=requested_command,
                mode=runtime_mode,
                project_count=len(project_contexts),
                projects=[context.name for context in project_contexts],
                total_ms=round((time.monotonic() - startup_started_at) * 1000.0, 2),
                debug_preentry_groups=selected_groups,
            )
            rt._emit(
                "ui.status",
                message="Startup complete; refreshing dashboard...",
                debug_preentry_groups=selected_groups,
            )

        return self._debug_run_post_preentry_tail(
            run_state=run_state,
            requested_command=requested_command,
            runtime_mode=runtime_mode,
            emit_snapshot=emit_snapshot,
            source=f"debug_preentry_combo_{'_'.join(selected_groups)}",
            group_payload={"debug_preentry_groups": selected_groups},
            post_preentry_group=post_preentry_group,
        )

    def _debug_run_prefix_group(
        self,
        *,
        group: str,
        tail_group: str,
        run_id: str,
        requested_command: str,
        runtime_mode: str,
        route: Route,
        project_contexts: list[Any],
        emit_phase: Any,
        emit_snapshot: Any,
    ) -> int:
        rt: Any = self.runtime
        from envctl_engine.ui.command_loop import _open_debug_grouped_selector

        rt._emit(
            "startup.debug_prefix_group",
            command=requested_command,
            group=group,
            tail_group=tail_group or None,
            action="enter",
        )

        run_state = self._debug_skip_plan_state(
            run_id=run_id,
            runtime_mode=runtime_mode,
            route=route,
            project_contexts=project_contexts,
            split_groups=set(),
        )

        if group in {"gating_only", "full_prefix"}:
            auto_resume_started = time.monotonic()
            existing_state = rt._load_auto_resume_state(runtime_mode)
            if existing_state is not None:
                emit_phase(
                    "auto_resume_evaluate",
                    auto_resume_started,
                    status="skipped",
                    reason="debug_prefix_group",
                    state_project_count=len(self._state_project_names(runtime=rt, state=existing_state)),
                    selected_project_count=len(project_contexts),
                )
                rt._emit(
                    "state.auto_resume.skipped",
                    reason="debug_prefix_group",
                    debug_prefix_group=group,
                    state_projects=sorted(self._state_project_names(runtime=rt, state=existing_state)),
                    selected_projects=sorted({context.name for context in project_contexts}),
                    mode=runtime_mode,
                    command=route.command,
                )
            else:
                emit_phase("auto_resume_evaluate", auto_resume_started, status="none", debug_prefix_group=group)
            rt._emit(
                "startup.debug_prefix_group",
                command=requested_command,
                group=group,
                action="gating_complete",
            )

        if group in {"branch_enter_only", "full_prefix"}:
            emit_snapshot(
                "startup_branch_enter",
                command=requested_command,
                mode=runtime_mode,
                real_noop_execution=True,
                exec_group="completion",
                debug_prefix_group=group,
            )
            rt._emit(
                "startup.debug_prefix_group",
                command=requested_command,
                group=group,
                action="branch_enter_complete",
            )

        env = getattr(rt, "env", None)
        if tail_group == "dashboard":
            rt._emit(
                "startup.debug_prefix_group",
                command=requested_command,
                group=group,
                tail_group=tail_group,
                action="dashboard_entry",
            )
            previous_minimal_dashboard = ""
            if isinstance(env, dict):
                previous_minimal_dashboard = str(env.get("ENVCTL_DEBUG_MINIMAL_DASHBOARD", ""))
                env["ENVCTL_DEBUG_MINIMAL_DASHBOARD"] = "1"
            try:
                return rt._run_interactive_dashboard_loop(run_state)
            finally:
                if isinstance(env, dict):
                    if previous_minimal_dashboard:
                        env["ENVCTL_DEBUG_MINIMAL_DASHBOARD"] = previous_minimal_dashboard
                    else:
                        env.pop("ENVCTL_DEBUG_MINIMAL_DASHBOARD", None)

        emit_snapshot(
            "before_dashboard_entry",
            source=f"debug_prefix_{group}",
            command=requested_command,
            mode=runtime_mode,
            service_count=len(run_state.services),
            requirement_count=len(run_state.requirements),
            debug_prefix_group=group,
            debug_prefix_tail_group=tail_group or None,
        )

        if tail_group == "snapshot_dashboard":
            rt._emit(
                "startup.debug_prefix_group",
                command=requested_command,
                group=group,
                tail_group=tail_group,
                action="snapshot_then_dashboard",
            )
            previous_minimal_dashboard = ""
            if isinstance(env, dict):
                previous_minimal_dashboard = str(env.get("ENVCTL_DEBUG_MINIMAL_DASHBOARD", ""))
                env["ENVCTL_DEBUG_MINIMAL_DASHBOARD"] = "1"
            try:
                return rt._run_interactive_dashboard_loop(run_state)
            finally:
                if isinstance(env, dict):
                    if previous_minimal_dashboard:
                        env["ENVCTL_DEBUG_MINIMAL_DASHBOARD"] = previous_minimal_dashboard
                    else:
                        env.pop("ENVCTL_DEBUG_MINIMAL_DASHBOARD", None)

        print("DEBUG DIRECT SELECTOR MODE (no dashboard). Do not press t.")
        print("DEBUG DIRECT SELECTOR MODE (no dashboard). Do not press t.")
        previous_selector_group = ""
        if isinstance(env, dict):
            previous_selector_group = str(env.get("ENVCTL_DEBUG_PLAN_SELECTOR_GROUP", ""))
            env["ENVCTL_DEBUG_PLAN_SELECTOR_GROUP"] = "standalone_child"
        try:
            _open_debug_grouped_selector(rt, run_state)
        finally:
            if isinstance(env, dict):
                if previous_selector_group:
                    env["ENVCTL_DEBUG_PLAN_SELECTOR_GROUP"] = previous_selector_group
                else:
                    env.pop("ENVCTL_DEBUG_PLAN_SELECTOR_GROUP", None)
        return 0

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
