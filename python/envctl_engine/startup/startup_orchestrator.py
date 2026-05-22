from __future__ import annotations

from pathlib import Path
import sys
import threading
import time
from typing import Callable, Mapping, cast, Iterable

from envctl_engine.runtime.command_router import MODE_TREE_TOKENS, Route
from envctl_engine.planning.plan_agent.config import resolve_plan_agent_launch_config
from envctl_engine.planning.plan_agent.launch import launch_plan_agent_terminals
from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree, PlanAgentLaunchConfig, PlanAgentLaunchResult
from envctl_engine.planning.plan_agent.omx_transport import validate_plan_agent_attach_target
from envctl_engine.planning.plan_agent.tmux_transport import attach_plan_agent_terminal
from envctl_engine.runtime.engine_runtime_env import route_is_implicit_start
from envctl_engine.runtime.engine_runtime_startup_support import evaluate_run_reuse, mark_run_reused
from envctl_engine.state.models import RequirementsResult, ServiceRecord
from envctl_engine.startup.dependency_bootstrap import prepare_project_dependencies
from envctl_engine.startup.context_selection import select_startup_contexts
from envctl_engine.startup.finalization import (
    build_failure_run_state,
    build_planning_dashboard_state,
    build_success_run_state,
    emit_preserved_service_merge as finalization_emit_preserved_service_merge,
    failure_context_label as finalization_failure_context_label,
    format_failure_context_label as finalization_format_failure_context_label,
    headless_plan_session_summary_lines,
    plan_agent_degraded_handoff_text,
    plan_dry_run_preview_lines,
    plan_session_summary_lines as finalization_plan_session_summary_lines,
    render_final_failure_status as finalization_render_final_failure_status,
    render_project_startup_warnings as finalization_render_project_startup_warnings,
    restart_port_rebound_summary_lines,
)
from envctl_engine.startup.run_reuse_support import (
    dashboard_stopped_service_entries as dashboard_stopped_service_entries_impl,
    fresh_start_replacement_services as fresh_start_replacement_services_impl,
    metadata_without_dashboard_stopped_services as metadata_without_dashboard_stopped_services_impl,
)
from envctl_engine.startup.run_reuse_resolution import resolve_startup_run_reuse
from envctl_engine.startup.plan_agent_handoff import (
    emit_plan_agent_launch_state as emit_plan_agent_launch_state_impl,
    launch_plan_agent_terminals_with_spinner as launch_plan_agent_terminals_with_spinner_impl,
    local_startup_failure_reason as plan_agent_local_startup_failure_reason,
    plan_agent_launch_failure_message as plan_agent_launch_failure_message_impl,
    plan_agent_launch_spinner_label as plan_agent_launch_spinner_label_impl,
    plan_agent_launch_spinner_message as plan_agent_launch_spinner_message_impl,
    plan_agent_launch_spinner_success_message as plan_agent_launch_spinner_success_message_impl,
    plan_agent_handoff_validation_required as plan_agent_handoff_validation_required_impl,
    prepare_plan_agent_dependencies_for_launch as prepare_plan_agent_dependencies_for_launch_impl,
    record_plan_agent_handoff_local_startup_failure as record_plan_agent_handoff_local_startup_failure_impl,
    record_stale_plan_agent_handoff as record_stale_plan_agent_handoff_impl,
    should_degrade_to_plan_agent_handoff as should_degrade_to_plan_agent_handoff_impl,
    should_fail_for_plan_agent_launch_result as should_fail_for_plan_agent_launch_result_impl,
)
from envctl_engine.startup.post_start_reconcile import reconcile_strict_truth_after_start
from envctl_engine.startup.protocols import ProjectContextLike, StartupRuntime
from envctl_engine.startup.restart_prestop_support import (
    apply_restart_ports_to_contexts,
    restart_prestop_preservation,
    restart_prestop_selection,
    restart_prestop_state,
    restart_start_route,
    terminate_restart_orphan_listeners,
)
from envctl_engine.startup.session import ProjectStartupResult, StartupSession
from envctl_engine.startup.session_lifecycle import (
    announce_session_identifiers as announce_session_identifiers_impl,
    create_startup_session,
    ensure_run_id,
    resolved_run_id,
    validate_startup_route_contract,
)
from envctl_engine.startup.selected_context_startup import start_selected_contexts
from envctl_engine.startup.startup_progress import (
    ProjectSpinnerGroup,
    report_progress,
    suppress_progress_output,
    suppress_timing_output,
)
from envctl_engine.startup.startup_selection_support import (
    port_allocator as port_allocator_impl,
    process_runtime as process_runtime_impl,
    _restart_include_requirements as _restart_include_requirements_impl,
    _restart_service_types_for_project as _restart_service_types_for_project_impl,
    select_start_tree_projects as select_start_tree_projects_impl,
    trees_start_selection_required as trees_start_selection_required_impl,
)
from envctl_engine.startup.service_bootstrap_domain import (
    configured_service_types_for_mode as configured_service_types_for_mode_impl,
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
from envctl_engine.ui.debug_snapshot import emit_plan_handoff_snapshot
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
        self._shared_dependency_lock: threading.Lock = threading.Lock()
        self._shared_dependency_requirements: RequirementsResult | None = None
        self._shared_dependency_progress_reported: bool = False

    def execute(self, route: Route) -> int:
        session = self._create_session(route)
        try:
            for phase in (
                self._validate_route_contract,
                self._handle_restart_prestop,
                self._select_contexts,
                self._resolve_plan_dry_run,
                self._prepare_and_launch_plan_agent_worktrees,
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
        return create_startup_session(self.runtime, route)

    def _ensure_run_id(self, session: StartupSession) -> None:
        ensure_run_id(self.runtime, session)

    @staticmethod
    def _resolved_run_id(session: StartupSession) -> str:
        return resolved_run_id(session)

    def _announce_session_identifiers(self, session: StartupSession) -> None:
        announce_session_identifiers_impl(
            self.runtime,
            session,
            headless_plan_output_only=self._headless_plan_output_only,
        )

    def _validate_route_contract(self, session: StartupSession) -> int | None:
        return validate_startup_route_contract(self.runtime, session, emit_phase=self._emit_phase)

    def _handle_restart_prestop(self, session: StartupSession) -> int | None:
        rt = self.runtime
        route = session.effective_route
        if route.command != "restart":
            return None
        prestop_state = restart_prestop_state(route=route, runtime=rt)
        restart_lookup_mode = prestop_state.restart_lookup_mode
        resumed = prestop_state.state
        if prestop_state.fallback_route is not None:
            session.effective_route = prestop_state.fallback_route
            session.runtime_mode = restart_lookup_mode
            return None
        session.restart_state = resumed

        selection = restart_prestop_selection(state=resumed, route=route, runtime=rt)
        selected_services = selection.selected_services
        target_projects = selection.target_projects
        include_requirements = selection.include_requirements
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
                self._terminate_restart_orphan_listeners(
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
                    rt._release_requirement_ports(requirements)
                session.preserved_requirements = dict(preservation.preserved_requirements)
                session.preserved_services = dict(preservation.preserved_services)
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
        session.effective_route = restart_start_route(
            route,
            restart_lookup_mode=restart_lookup_mode,
            selected_services=selected_services,
            target_projects=target_projects,
            include_requirements=include_requirements,
        )
        session.runtime_mode = restart_lookup_mode
        return None

    def _select_contexts(self, session: StartupSession) -> int | None:
        return select_startup_contexts(
            runtime=self.runtime,
            session=session,
            trees_start_selection_required=lambda route, runtime_mode: self._trees_start_selection_required(
                route=route,
                runtime_mode=runtime_mode,
            ),
            select_start_tree_projects=lambda *, route, project_contexts: self._select_start_tree_projects(
                route=route,
                project_contexts=project_contexts,
            ),
            apply_restart_ports=self._apply_restart_ports,
            emit_phase=self._emit_phase,
            emit_snapshot=self._emit_snapshot,
        )

    def _apply_restart_ports(self, session: StartupSession, contexts: list[ProjectContextLike]) -> None:
        apply_restart_ports_to_contexts(
            session.restart_state,
            route=session.effective_route,
            contexts=contexts,
            project_name_from_service=self.runtime._project_name_from_service,
            set_plan_port=self.runtime._set_plan_port,
        )

    def _terminate_restart_orphan_listeners(
        self,
        *,
        state,
        selected_services: set[str],
        aggressive: bool,
    ) -> None:
        rt = self.runtime
        listener_pids_for_port = cast(Callable[[int], Iterable[int]], getattr(rt, "_listener_pids_for_port", None))
        process_runtime = self._process_runtime(rt)
        port_allocator = port_allocator_impl(rt)
        terminate_restart_orphan_listeners(
            state=state,
            selected_services=selected_services,
            aggressive=aggressive,
            backend_port_base=int(rt.config.backend_port_base),
            frontend_port_base=int(rt.config.frontend_port_base),
            port_spacing=int(getattr(rt.config, "port_spacing", 20) or 20),
            listener_pids_for_port=listener_pids_for_port,
            process_cwd=self._process_cwd,
            terminate_pid=getattr(process_runtime, "terminate", None),
            release_port=port_allocator.release,
        )

    @staticmethod
    def _process_cwd(pid: int) -> str | None:
        try:
            return str(Path(f"/proc/{pid}/cwd").resolve())
        except OSError:
            return None

    def _resolve_plan_dry_run(self, session: StartupSession) -> int | None:
        route = session.effective_route
        if route.command != "plan" or not bool(route.flags.get("dry_run")):
            return None
        self._print_plan_dry_run_preview(session)
        return 0

    def _prepare_and_launch_plan_agent_worktrees(self, session: StartupSession) -> int | None:
        route = session.effective_route
        if route.command != "plan" or bool(route.flags.get("planning_prs")):
            return None
        if not session.plan_agent_launch_requested:
            return None
        created_worktrees = tuple(session.pending_plan_agent_worktrees)
        rt = self.runtime
        launch_config = resolve_plan_agent_launch_config(rt.config, getattr(rt, "env", {}), route=route)
        if launch_config.enabled and created_worktrees:
            self._ensure_run_id(session)
            prepare_plan_agent_dependencies_for_launch_impl(
                rt,
                session,
                created_worktrees=created_worktrees,
                launch_config=launch_config,
                report_progress=self._report_progress,
                prepare_fn=prepare_project_dependencies,
            )
        launch_result = self._launch_plan_agent_terminals_with_spinner(
            session,
            created_worktrees=created_worktrees,
            launch_config=launch_config,
        )
        session.plan_agent_launch_result = launch_result
        session.plan_agent_attach_target = launch_result.attach_target
        self._validate_plan_agent_handoff(session, phase="post_launch")
        self._emit_plan_agent_launch_state(session, launch_result)
        if self._should_fail_for_plan_agent_launch_result(session, launch_result):
            raise RuntimeError(self._plan_agent_launch_failure_message(launch_result))
        return None

    def _should_fail_for_plan_agent_launch_result(
        self,
        session: StartupSession,
        launch_result: PlanAgentLaunchResult,
    ) -> bool:
        return should_fail_for_plan_agent_launch_result_impl(session, launch_result)

    @staticmethod
    def _plan_agent_launch_failure_message(launch_result: PlanAgentLaunchResult) -> str:
        return plan_agent_launch_failure_message_impl(launch_result)

    def _launch_plan_agent_terminals_with_spinner(
        self,
        session: StartupSession,
        *,
        created_worktrees: tuple[CreatedPlanWorktree, ...],
        launch_config: PlanAgentLaunchConfig,
    ) -> PlanAgentLaunchResult:
        return cast(
            PlanAgentLaunchResult,
            launch_plan_agent_terminals_with_spinner_impl(
                self.runtime,
                route=session.effective_route,
                created_worktrees=created_worktrees,
                launch_config=launch_config,
                suppress_progress_output=self._suppress_progress_output(session.effective_route),
                launch_fn=launch_plan_agent_terminals,
            ),
        )

    @staticmethod
    def _plan_agent_launch_spinner_label(launch_config: PlanAgentLaunchConfig) -> str:
        return plan_agent_launch_spinner_label_impl(launch_config)

    @classmethod
    def _plan_agent_launch_spinner_message(cls, launch_config: PlanAgentLaunchConfig, *, count: int) -> str:
        return plan_agent_launch_spinner_message_impl(launch_config, count=count)

    @classmethod
    def _plan_agent_launch_spinner_success_message(cls, launch_config: PlanAgentLaunchConfig, *, count: int) -> str:
        return plan_agent_launch_spinner_success_message_impl(launch_config, count=count)

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
        if route.command == "plan":
            self._validate_plan_agent_handoff(session, phase="disabled_startup_finalization")
            self._print_plan_dry_run_preview(session)
            print(
                "Planning mode complete; skipping service startup because "
                f"envctl runs are disabled for {session.runtime_mode}."
            )
        if self._headless_plan_output_only(session):
            self._print_headless_plan_session_summary(session)
            return 0
        enter_interactive_dashboard = rt._should_enter_post_start_interactive(route)
        attach_code = self._maybe_attach_plan_agent_terminal(session)
        if attach_code is not None:
            return attach_code
        elif not enter_interactive_dashboard:
            print(f"envctl runs are disabled for {session.runtime_mode}; opening dashboard without starting services.")
        if enter_interactive_dashboard:
            return rt._run_interactive_dashboard_loop(run_state)
        return 0

    def _resolve_run_reuse(self, session: StartupSession) -> int | None:
        return resolve_startup_run_reuse(
            runtime=self.runtime,
            session=session,
            evaluate_run_reuse_fn=evaluate_run_reuse,
            prepare_dashboard_stopped_service_restore=self._prepare_dashboard_stopped_service_restore,
            announce_session_identifiers=self._announce_session_identifiers,
            emit_phase=self._emit_phase,
            headless_plan_output_only=self._headless_plan_output_only,
            maybe_attach_plan_agent_terminal=self._maybe_attach_plan_agent_terminal,
            print_headless_plan_session_summary=self._print_headless_plan_session_summary,
            print_plan_dry_run_preview=self._print_plan_dry_run_preview,
            configured_service_types_for_mode=self._configured_service_types_for_mode,
            emit_snapshot=self._emit_snapshot,
            replace_existing_project_services_for_fresh_start=self._replace_existing_project_services_for_fresh_start,
        )

    def _replace_existing_project_services_for_fresh_start(
        self,
        session: StartupSession,
        *,
        candidate_state,
        reason: str,
    ) -> None:
        if reason != "startup_fingerprint_mismatch":
            return
        route = session.effective_route
        if route.flags.get("runtime_scope") == "dependencies":
            return
        selected_services = self._fresh_start_replacement_services(
            session,
            candidate_state=candidate_state,
        )
        if not selected_services:
            return
        rt = self.runtime
        self._announce_session_identifiers(session)
        self._report_progress(
            route,
            f"Startup selection changed; replacing {len(selected_services)} existing service(s)...",
        )
        rt._emit(
            "state.run_reuse.replace_existing_services",
            run_id=candidate_state.run_id,
            mode=session.runtime_mode,
            reason=reason,
            selected_services=sorted(selected_services),
        )
        rt._terminate_services_from_state(
            candidate_state,
            selected_services=selected_services,
            aggressive=False,
            verify_ownership=True,
        )
        self._terminate_restart_orphan_listeners(
            state=candidate_state,
            selected_services=selected_services,
            aggressive=True,
        )

    def _fresh_start_replacement_services(self, session: StartupSession, *, candidate_state) -> set[str]:
        return fresh_start_replacement_services_impl(
            route=session.effective_route,
            selected_contexts=list(session.selected_contexts),
            candidate_state=candidate_state,
            configured_service_types=set(self._configured_service_types_for_mode(session.runtime_mode)),
            additional_services=tuple(getattr(self.runtime.config, "additional_services", ()) or ()),
            project_name_from_service=self.runtime._project_name_from_service,
        )

    def _prepare_dashboard_stopped_service_restore(
        self,
        session: StartupSession,
        *,
        candidate_state,
        reuse_started: float,
        decision_kind: str,
    ) -> bool:
        active_service_names = set(candidate_state.services)
        stopped_entries = [
            entry
            for entry in self._dashboard_stopped_service_entries(candidate_state)
            if entry["name"] not in active_service_names
        ]
        if not stopped_entries:
            return False
        selected_context_by_name = {
            str(context.name).strip().casefold(): context
            for context in session.selected_contexts
            if str(getattr(context, "name", "")).strip()
        }
        restore_entries = [
            entry for entry in stopped_entries if entry["project"].casefold() in selected_context_by_name
        ]
        if not restore_entries:
            return False
        target_project_names = sorted({entry["project"] for entry in restore_entries}, key=str.casefold)
        target_project_keys = {name.casefold() for name in target_project_names}
        contexts_to_start = [
            context
            for key, context in selected_context_by_name.items()
            if key in target_project_keys
        ]
        if not contexts_to_start:
            return False
        stopped_service_names = sorted({entry["name"] for entry in restore_entries})
        stopped_service_types = sorted({entry["type"] for entry in restore_entries})
        session.base_metadata = self._metadata_without_dashboard_stopped_services(
            mark_run_reused(candidate_state.metadata, reason="restore_stopped_services"),
            restored_service_names=set(stopped_service_names),
        )
        session.preserved_services = dict(candidate_state.services)
        session.preserved_requirements = dict(candidate_state.requirements)
        session.contexts_to_start = contexts_to_start
        route = session.effective_route
        session.effective_route = Route(
            command=route.command,
            mode=route.mode,
            raw_args=route.raw_args,
            passthrough_args=route.passthrough_args,
            projects=target_project_names,
            flags={
                **route.flags,
                "_restart_request": True,
                "_restore_dashboard_stopped_services": True,
                "services": stopped_service_names,
                "restart_service_types": stopped_service_types,
                "restart_include_requirements": False,
            },
        )
        self._emit_phase(
            session,
            "auto_resume_evaluate",
            reuse_started,
            status="restore_stopped_services",
            match_mode="exact" if decision_kind == "resume_exact" else "subset",
            stopped_service_count=len(stopped_service_names),
            target_projects=target_project_names,
        )
        self.runtime._emit(
            "state.auto_resume.restore_stopped_services",
            run_id=candidate_state.run_id,
            mode=session.runtime_mode,
            command=route.command,
            projects=target_project_names,
            services=stopped_service_names,
        )
        self.runtime._emit(
            "state.run_reuse.applied",
            run_id=candidate_state.run_id,
            mode=session.runtime_mode,
            command=route.command,
            decision_kind="restore_stopped_services",
            reason="dashboard_stopped_services",
            restored_projects=target_project_names,
            restored_services=stopped_service_names,
        )
        return True

    @staticmethod
    def _dashboard_stopped_service_entries(state) -> list[dict[str, str]]:
        return dashboard_stopped_service_entries_impl(state)

    @staticmethod
    def _metadata_without_dashboard_stopped_services(
        metadata: Mapping[str, object],
        *,
        restored_service_names: set[str],
    ) -> dict[str, object]:
        return metadata_without_dashboard_stopped_services_impl(
            metadata,
            restored_service_names=restored_service_names,
        )

    def _prepare_execution(self, session: StartupSession) -> None:
        route = session.effective_route
        prewarm_started = time.monotonic()
        self._maybe_prewarm_docker(route=route, mode=session.runtime_mode)
        self._emit_phase(session, "docker_prewarm", prewarm_started, status="ok")

    def _start_selected_contexts(self, session: StartupSession) -> None:
        start_selected_contexts(
            runtime=self.runtime,
            session=session,
            suppress_progress_output=self._suppress_progress_output,
            resolved_run_id=self._resolved_run_id,
            record_project_startup=self._record_project_startup,
            render_project_startup_warnings=self._render_project_startup_warnings,
            should_degrade_to_plan_agent_handoff=lambda session, error: self._should_degrade_to_plan_agent_handoff(
                session,
                error=error,
            ),
            record_plan_agent_handoff_local_startup_failure=self._record_plan_agent_handoff_local_startup_failure,
            spinner_factory=spinner,
            use_spinner_policy_fn=use_spinner_policy,
            resolve_spinner_policy_fn=resolve_spinner_policy,
            emit_spinner_policy_fn=emit_spinner_policy,
            project_spinner_group_factory=_ProjectSpinnerGroup,
        )

    def _reconcile_strict_truth(self, session: StartupSession) -> None:
        reconcile_strict_truth_after_start(
            runtime=self.runtime,
            session=session,
            build_run_state=build_success_run_state,
            reconcile_state_truth=self.runtime._reconcile_state_truth,
            emit_phase=self._emit_phase,
        )

    def _finalize_success(self, session: StartupSession) -> int:
        if session.plan_agent_handoff_degraded:
            return self._finalize_plan_agent_degraded_handoff(session)
        rt = self.runtime
        self._ensure_run_id(session)
        self._validate_plan_agent_handoff(session, phase="success_finalization")
        run_state = build_success_run_state(rt, session)
        self._emit_preserved_service_merge(session)
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
                self._print_restart_port_rebound_summary(session)
                rt._print_summary(run_state, session.selected_contexts)
        else:
            self._print_restart_port_rebound_summary(session)
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

    def _print_restart_port_rebound_summary(self, session: StartupSession) -> None:
        for line in restart_port_rebound_summary_lines(session, self.runtime.events):
            print(line)

    def _headless_plan_output_only(self, session: StartupSession) -> bool:
        route = session.effective_route
        return route.command == "plan" and bool(route.flags.get("batch"))

    def _print_plan_dry_run_preview(self, session: StartupSession) -> None:
        route = session.effective_route
        if route.command != "plan" or not bool(route.flags.get("dry_run")):
            return
        planning_orchestrator = getattr(self.runtime, "planning_worktree_orchestrator", None)
        selection_getter = getattr(planning_orchestrator, "last_plan_selection_result", None)
        selection_result = selection_getter() if callable(selection_getter) else None
        created_names = {
            worktree.name
            for worktree in getattr(selection_result, "created_worktrees", ())
            if isinstance(worktree, CreatedPlanWorktree)
        }
        for line in plan_dry_run_preview_lines(session, created_names=created_names):
            print(line)

    def _maybe_attach_plan_agent_terminal(self, session: StartupSession) -> int | None:
        self._validate_plan_agent_handoff(session, phase="interactive_attach")
        attach_target = session.plan_agent_attach_target
        if attach_target is None:
            return None
        session.plan_agent_attach_target = None
        attach_code = attach_plan_agent_terminal(self.runtime, attach_target)
        if attach_code != 0:
            self._print_headless_plan_session_summary(session, attach_target=attach_target)
            return 0
        return attach_code

    def _finalize_plan_agent_degraded_handoff(self, session: StartupSession) -> int:
        rt = self.runtime
        self._ensure_run_id(session)
        self._validate_plan_agent_handoff(session, phase="degraded_finalization")
        run_state = build_success_run_state(rt, session)
        artifacts_started = time.monotonic()
        rt._write_artifacts(run_state, session.selected_contexts, errors=session.errors)
        self._emit_phase(session, "artifacts_write", artifacts_started, status="degraded")
        self._render_plan_agent_degraded_handoff(session)
        if self._headless_plan_output_only(session):
            return 0
        attach_code = self._maybe_attach_plan_agent_terminal(session)
        if attach_code is not None:
            return attach_code
        return 0

    def _emit_preserved_service_merge(self, session: StartupSession) -> None:
        finalization_emit_preserved_service_merge(self.runtime, session)

    def _print_headless_plan_session_summary(
        self,
        session: StartupSession,
        *,
        attach_target: object | None = None,
    ) -> None:
        if attach_target is None:
            self._validate_plan_agent_handoff(session, phase="headless_output")
        for line in headless_plan_session_summary_lines(session, attach_target=attach_target):
            print(line)

    def _plan_session_summary_lines(
        self,
        session: StartupSession,
        *,
        attach_target: object | None = None,
    ) -> list[str]:
        return finalization_plan_session_summary_lines(session, attach_target=attach_target)

    def _render_plan_agent_degraded_handoff(self, session: StartupSession) -> None:
        text = plan_agent_degraded_handoff_text(session)
        link_mode = str(self.runtime.env.get("ENVCTL_UI_HYPERLINK_MODE", "")).strip().lower()
        print(
            render_paths_in_terminal_text(
                text,
                paths=local_paths_in_text(text),
                env=self.runtime.env,
                stream=sys.stdout,
                interactive_tty=(True if link_mode == "on" else None),
            )
        )

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
        rendered_error = self._render_final_failure_status(
            session,
            final_error,
            interactive_tty=(True if link_mode == "on" else None),
        )
        print(
            render_paths_in_terminal_text(
                rendered_error,
                paths=local_paths_in_text(rendered_error),
                env=rt.env,
                stream=sys.stdout,
                interactive_tty=(True if link_mode == "on" else None),
            )
        )
        return 1

    def _render_final_failure_status(
        self,
        session: StartupSession,
        final_error: str,
        *,
        interactive_tty: bool | None,
    ) -> str:
        return finalization_render_final_failure_status(
            self.runtime,
            session,
            final_error,
            interactive_tty=interactive_tty,
        )

    @staticmethod
    def _failure_context_label(session: StartupSession, final_error: str) -> str | None:
        return finalization_failure_context_label(session, final_error)

    @staticmethod
    def _format_failure_context_label(context: ProjectContextLike) -> str:
        return finalization_format_failure_context_label(context)

    def _record_project_startup(
        self,
        session: StartupSession,
        context: ProjectContextLike,
        result: ProjectStartupResult,
    ) -> None:
        session.requirements_by_project[context.name] = result.requirements
        session.services_by_project[context.name] = result.services
        session.started_context_names.append(context.name)

    def _should_degrade_to_plan_agent_handoff(self, session: StartupSession, *, error: str) -> bool:
        self._validate_plan_agent_handoff(session, phase="local_startup_failure")
        return should_degrade_to_plan_agent_handoff_impl(session, error=error)

    def _validate_plan_agent_handoff(self, session: StartupSession, *, phase: str) -> None:
        if not self._plan_agent_handoff_validation_required(session):
            return
        attach_target = session.plan_agent_attach_target
        if attach_target is None:
            return
        created_worktrees = tuple(session.pending_plan_agent_worktrees)
        worktree = created_worktrees[0] if created_worktrees else None
        validation = validate_plan_agent_attach_target(
            self.runtime,
            attach_target,
            worktree=worktree,
            transport="omx",
            phase=phase,
        )
        if validation.ok:
            return
        self._record_stale_plan_agent_handoff(session, validation_reason="attach_target_stale_after_launch")

    def _plan_agent_handoff_validation_required(self, session: StartupSession) -> bool:
        return plan_agent_handoff_validation_required_impl(session)

    def _record_stale_plan_agent_handoff(self, session: StartupSession, *, validation_reason: str) -> None:
        record_stale_plan_agent_handoff_impl(self.runtime, session, validation_reason=validation_reason)

    @staticmethod
    def _local_startup_failure_reason(error: str) -> str | None:
        return plan_agent_local_startup_failure_reason(error)

    def _record_plan_agent_handoff_local_startup_failure(
        self,
        session: StartupSession,
        *,
        project_name: str,
        error: str,
    ) -> None:
        record_plan_agent_handoff_local_startup_failure_impl(
            self.runtime,
            session,
            project_name=project_name,
            error=error,
        )

    def _emit_plan_agent_launch_state(self, session: StartupSession, launch_result: object) -> None:
        emit_plan_agent_launch_state_impl(self.runtime, session, launch_result)

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
        return configured_service_types_for_mode_impl(self.runtime.config, runtime_mode)

    def _render_project_startup_warnings(
        self,
        *,
        context: ProjectContextLike,
        warnings: list[str],
        route: Route,
        project_spinner_group: object | None,
    ) -> None:
        finalization_render_project_startup_warnings(
            self.runtime,
            context=context,
            warnings=warnings,
            suppress_progress=self._suppress_progress_output(route),
            project_spinner_group=project_spinner_group,
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
        additional_services: tuple[object, ...] = (),
    ) -> set[str]:
        return _restart_service_types_for_project_impl(
            route=route,
            project_name=project_name,
            default_service_types=default_service_types,
            additional_services=additional_services,
        )

    @staticmethod
    def _process_runtime(runtime: object):
        return process_runtime_impl(runtime)
