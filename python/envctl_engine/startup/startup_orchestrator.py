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
from envctl_engine.runtime.engine_runtime_startup_support import evaluate_run_reuse
from envctl_engine.state.models import RequirementsResult, ServiceRecord
from envctl_engine.startup.dependency_bootstrap import prepare_project_dependencies
from envctl_engine.startup.disabled_startup_resolution import resolve_disabled_startup_mode
from envctl_engine.startup.context_selection import select_startup_contexts
from envctl_engine.startup.finalization import (
    build_planning_dashboard_state,
    build_success_run_state,
    emit_preserved_service_merge as finalization_emit_preserved_service_merge,
    finalize_failed_startup,
    finalize_plan_agent_degraded_handoff,
    finalize_successful_startup,
    headless_plan_output_only as finalization_headless_plan_output_only,
    maybe_attach_plan_agent_terminal as maybe_attach_plan_agent_terminal_impl,
    print_headless_plan_session_summary as print_headless_plan_session_summary_impl,
    print_plan_dry_run_preview as print_plan_dry_run_preview_impl,
    print_restart_port_rebound_summary as print_restart_port_rebound_summary_impl,
    render_plan_agent_degraded_handoff_for_terminal as finalization_render_plan_agent_degraded_handoff_for_terminal,
    render_final_failure_status as finalization_render_final_failure_status,
    render_project_startup_warnings_for_route as finalization_render_project_startup_warnings_for_route,
)
from envctl_engine.startup.execution_preparation import prepare_startup_execution
from envctl_engine.startup.run_reuse_support import (
    dashboard_stopped_service_entries as dashboard_stopped_service_entries_impl,
    fresh_start_replacement_services as fresh_start_replacement_services_impl,
    metadata_without_dashboard_stopped_services as metadata_without_dashboard_stopped_services_impl,
    prepare_dashboard_stopped_service_restore as prepare_dashboard_stopped_service_restore_impl,
    replace_existing_project_services_for_fresh_start as replace_existing_project_services_for_fresh_start_impl,
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
    handle_restart_prestop,
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
from envctl_engine.startup.selected_context_startup import (
    record_project_startup as record_project_startup_impl,
    start_selected_contexts,
)
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
            headless_plan_output_only=finalization_headless_plan_output_only,
        )

    def _validate_route_contract(self, session: StartupSession) -> int | None:
        return validate_startup_route_contract(self.runtime, session, emit_phase=self._emit_phase)

    def _handle_restart_prestop(self, session: StartupSession) -> int | None:
        return handle_restart_prestop(
            runtime=self.runtime,
            session=session,
            suppress_progress_output=self._suppress_progress_output,
            terminate_restart_orphan_listeners=self._terminate_restart_orphan_listeners,
            spinner_factory=spinner,
            use_spinner_policy_fn=use_spinner_policy,
            resolve_spinner_policy_fn=resolve_spinner_policy,
            emit_spinner_policy_fn=emit_spinner_policy,
        )

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
        print_plan_dry_run_preview_impl(self.runtime, session, print_fn=print)
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
        return resolve_disabled_startup_mode(
            runtime=self.runtime,
            session=session,
            route_is_implicit_start=route_is_implicit_start,
            ensure_run_id=self._ensure_run_id,
            announce_session_identifiers=self._announce_session_identifiers,
            resolved_run_id=self._resolved_run_id,
            build_planning_dashboard_state=build_planning_dashboard_state,
            configured_service_types_for_mode=self._configured_service_types_for_mode,
            emit_phase=self._emit_phase,
            validate_plan_agent_handoff=self._validate_plan_agent_handoff,
            print_plan_dry_run_preview=lambda session: print_plan_dry_run_preview_impl(
                self.runtime,
                session,
                print_fn=print,
            ),
            headless_plan_output_only=finalization_headless_plan_output_only,
            print_headless_plan_session_summary=self._print_headless_plan_session_summary,
            maybe_attach_plan_agent_terminal=self._maybe_attach_plan_agent_terminal,
        )

    def _resolve_run_reuse(self, session: StartupSession) -> int | None:
        return resolve_startup_run_reuse(
            runtime=self.runtime,
            session=session,
            evaluate_run_reuse_fn=evaluate_run_reuse,
            prepare_dashboard_stopped_service_restore=self._prepare_dashboard_stopped_service_restore,
            announce_session_identifiers=self._announce_session_identifiers,
            emit_phase=self._emit_phase,
            headless_plan_output_only=finalization_headless_plan_output_only,
            maybe_attach_plan_agent_terminal=self._maybe_attach_plan_agent_terminal,
            print_headless_plan_session_summary=self._print_headless_plan_session_summary,
            print_plan_dry_run_preview=lambda session: print_plan_dry_run_preview_impl(
                self.runtime,
                session,
                print_fn=print,
            ),
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
        replace_existing_project_services_for_fresh_start_impl(
            runtime=self.runtime,
            session=session,
            candidate_state=candidate_state,
            reason=reason,
            fresh_start_replacement_services=self._fresh_start_replacement_services,
            announce_session_identifiers=self._announce_session_identifiers,
            report_progress=self._report_progress,
            terminate_restart_orphan_listeners=self._terminate_restart_orphan_listeners,
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
        return prepare_dashboard_stopped_service_restore_impl(
            runtime=self.runtime,
            session=session,
            candidate_state=candidate_state,
            reuse_started=reuse_started,
            decision_kind=decision_kind,
            emit_phase=self._emit_phase,
        )

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
        prepare_startup_execution(
            session=session,
            maybe_prewarm_docker=self._maybe_prewarm_docker,
            emit_phase=self._emit_phase,
        )

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
        return finalize_successful_startup(
            runtime=self.runtime,
            session=session,
            ensure_run_id=self._ensure_run_id,
            validate_plan_agent_handoff=self._validate_plan_agent_handoff,
            build_success_run_state=build_success_run_state,
            emit_preserved_service_merge=lambda session: finalization_emit_preserved_service_merge(
                self.runtime,
                session,
            ),
            emit_phase=self._emit_phase,
            requirements_timing_enabled=lambda route: requirements_timing_enabled_impl(self, route),
            suppress_timing_output=self._suppress_timing_output,
            print_startup_summary=lambda **kwargs: print_startup_summary_impl(self, **kwargs),
            startup_breakdown_enabled=lambda route: startup_breakdown_enabled_impl(self, route),
            suppress_progress_output=self._suppress_progress_output,
            print_restart_port_rebound_summary=lambda session: print_restart_port_rebound_summary_impl(
                self.runtime,
                session,
                print_fn=print,
            ),
            emit_snapshot=self._emit_snapshot,
            headless_plan_output_only=finalization_headless_plan_output_only,
            print_headless_plan_session_summary=self._print_headless_plan_session_summary,
            maybe_attach_plan_agent_terminal=self._maybe_attach_plan_agent_terminal,
            finalize_plan_agent_degraded_handoff=self._finalize_plan_agent_degraded_handoff,
        )

    def _maybe_attach_plan_agent_terminal(self, session: StartupSession) -> int | None:
        return maybe_attach_plan_agent_terminal_impl(
            runtime=self.runtime,
            session=session,
            validate_plan_agent_handoff=self._validate_plan_agent_handoff,
            attach_plan_agent_terminal=attach_plan_agent_terminal,
            print_headless_plan_session_summary=self._print_headless_plan_session_summary,
        )

    def _finalize_plan_agent_degraded_handoff(self, session: StartupSession) -> int:
        return finalize_plan_agent_degraded_handoff(
            runtime=self.runtime,
            session=session,
            ensure_run_id=self._ensure_run_id,
            validate_plan_agent_handoff=self._validate_plan_agent_handoff,
            build_success_run_state=build_success_run_state,
            emit_phase=self._emit_phase,
            render_plan_agent_degraded_handoff=self._render_plan_agent_degraded_handoff,
            headless_plan_output_only=finalization_headless_plan_output_only,
            maybe_attach_plan_agent_terminal=self._maybe_attach_plan_agent_terminal,
        )

    def _print_headless_plan_session_summary(
        self,
        session: StartupSession,
        *,
        attach_target: object | None = None,
    ) -> None:
        print_headless_plan_session_summary_impl(
            session,
            validate_plan_agent_handoff=self._validate_plan_agent_handoff,
            print_fn=print,
            attach_target=attach_target,
        )

    def _render_plan_agent_degraded_handoff(self, session: StartupSession) -> None:
        finalization_render_plan_agent_degraded_handoff_for_terminal(
            self.runtime,
            session,
            stream=sys.stdout,
            print_fn=print,
        )

    def _finalize_failure(self, session: StartupSession, error: str) -> int:
        return finalize_failed_startup(
            runtime=self.runtime,
            session=session,
            error=error,
            ensure_run_id=self._ensure_run_id,
            port_allocator=port_allocator_impl,
            emit_phase=self._emit_phase,
            render_final_failure_status=finalization_render_final_failure_status,
        )

    def _record_project_startup(
        self,
        session: StartupSession,
        context: ProjectContextLike,
        result: ProjectStartupResult,
    ) -> None:
        record_project_startup_impl(session, context, result)

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
        finalization_render_project_startup_warnings_for_route(
            self.runtime,
            context=context,
            warnings=warnings,
            route=route,
            project_spinner_group=project_spinner_group,
            suppress_progress_output=self._suppress_progress_output,
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
