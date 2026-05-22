from __future__ import annotations

import sys
import threading
from functools import partial
from typing import Callable, cast, Iterable

from envctl_engine.runtime.command_router import MODE_TREE_TOKENS, Route
from envctl_engine.planning.plan_agent.config import resolve_plan_agent_launch_config
from envctl_engine.planning.plan_agent.launch import launch_plan_agent_terminals
from envctl_engine.planning.plan_agent.models import PlanAgentLaunchResult
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
    resolve_plan_dry_run as resolve_plan_dry_run_impl,
    print_restart_port_rebound_summary as print_restart_port_rebound_summary_impl,
    render_plan_agent_degraded_handoff_for_terminal as finalization_render_plan_agent_degraded_handoff_for_terminal,
    render_final_failure_status as finalization_render_final_failure_status,
    render_project_startup_warnings_for_route as finalization_render_project_startup_warnings_for_route,
)
from envctl_engine.startup.execution_preparation import prepare_startup_execution
from envctl_engine.startup.run_reuse_support import (
    prepare_dashboard_stopped_service_restore_with_runtime,
    replace_existing_project_services_for_fresh_start_with_defaults,
)
from envctl_engine.startup.run_reuse_resolution import resolve_startup_run_reuse
from envctl_engine.startup.plan_agent_handoff import (
    emit_plan_agent_launch_state as emit_plan_agent_launch_state_impl,
    launch_plan_agent_terminals_with_spinner as launch_plan_agent_terminals_with_spinner_impl,
    plan_agent_launch_failure_message as plan_agent_launch_failure_message_impl,
    prepare_plan_agent_dependencies_for_launch as prepare_plan_agent_dependencies_for_launch_impl,
    record_plan_agent_handoff_local_startup_failure as record_plan_agent_handoff_local_startup_failure_impl,
    should_degrade_to_validated_plan_agent_handoff,
    should_fail_for_plan_agent_launch_result as should_fail_for_plan_agent_launch_result_impl,
    validate_plan_agent_handoff_with_attach_target,
)
from envctl_engine.startup.post_start_reconcile import reconcile_strict_truth_after_start
from envctl_engine.startup.protocols import ProjectContextLike, StartupRuntime
from envctl_engine.startup.restart_prestop_support import (
    apply_restart_ports_to_contexts,
    handle_restart_prestop,
    process_cwd,
    terminate_restart_orphan_listeners,
)
from envctl_engine.startup.session import ProjectStartupResult, StartupSession
from envctl_engine.startup.session_lifecycle import (
    announce_session_identifiers as announce_session_identifiers_impl,
    create_startup_session,
    emit_startup_phase,
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
    select_start_tree_projects,
    trees_start_selection_required,
)
from envctl_engine.startup.service_bootstrap_domain import (
    configured_service_types_for_mode as configured_service_types_for_mode_impl,
)
from envctl_engine.startup.startup_execution_support import (
    maybe_prewarm_docker as maybe_prewarm_docker_impl,
    print_startup_summary as print_startup_summary_impl,
    requirements_timing_enabled as requirements_timing_enabled_impl,
    start_project_context as start_project_context_impl,
    start_project_services as start_project_services_impl,
    start_requirements_for_project as start_requirements_for_project_impl,
    startup_breakdown_enabled as startup_breakdown_enabled_impl,
)
from envctl_engine.ui.debug_snapshot import emit_startup_plan_handoff_snapshot
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
        session = create_startup_session(self.runtime, route)
        finalize_failure = partial(
            finalize_failed_startup,
            runtime=self.runtime,
            session=session,
            ensure_run_id=partial(ensure_run_id, self.runtime),
            port_allocator=port_allocator_impl,
            emit_phase=partial(emit_startup_phase, self.runtime),
            render_final_failure_status=finalization_render_final_failure_status,
        )
        try:
            def apply_restart_ports(session: StartupSession, contexts: list[ProjectContextLike]) -> None:
                apply_restart_ports_to_contexts(
                    session.restart_state,
                    route=session.effective_route,
                    contexts=contexts,
                    project_name_from_service=self.runtime._project_name_from_service,
                    set_plan_port=self.runtime._set_plan_port,
                )
            for phase in (
                partial(
                    validate_startup_route_contract,
                    self.runtime,
                    emit_phase=partial(emit_startup_phase, self.runtime),
                ),
                self._handle_restart_prestop,
                lambda _: select_startup_contexts(
                    runtime=self.runtime,
                    session=session,
                    trees_start_selection_required=trees_start_selection_required,
                    select_start_tree_projects=select_start_tree_projects,
                    apply_restart_ports=apply_restart_ports,
                    emit_phase=partial(emit_startup_phase, self.runtime),
                    emit_snapshot=partial(emit_startup_plan_handoff_snapshot, self.runtime),
                ),
                partial(resolve_plan_dry_run_impl, self.runtime, print_fn=print),
                self._prepare_and_launch_plan_agent_worktrees,
                self._resolve_run_reuse,
                self._resolve_disabled_startup_mode,
            ):
                code = phase(session)
                if code is not None:
                    return code
            ensure_run_id(self.runtime, session)
            announce_session_identifiers_impl(
                self.runtime,
                session,
                headless_plan_output_only=finalization_headless_plan_output_only,
            )
            prepare_startup_execution(
                session=session,
                maybe_prewarm_docker=lambda *, route, mode: maybe_prewarm_docker_impl(self, route=route, mode=mode),
                emit_phase=partial(emit_startup_phase, self.runtime),
            )
            start_selected_contexts(
                runtime=self.runtime,
                session=session,
                suppress_progress_output=suppress_progress_output,
                resolved_run_id=resolved_run_id,
                record_project_startup=record_project_startup_impl,
                render_project_startup_warnings=partial(
                    finalization_render_project_startup_warnings_for_route,
                    self.runtime,
                    suppress_progress_output=suppress_progress_output,
                ),
                should_degrade_to_plan_agent_handoff=lambda session, error: (
                    should_degrade_to_validated_plan_agent_handoff(
                        self.runtime,
                        session,
                        error=error,
                        validate_attach_target_fn=validate_plan_agent_attach_target,
                    )
                ),
                record_plan_agent_handoff_local_startup_failure=partial(
                    record_plan_agent_handoff_local_startup_failure_impl,
                    self.runtime,
                ),
                spinner_factory=spinner,
                use_spinner_policy_fn=use_spinner_policy,
                resolve_spinner_policy_fn=resolve_spinner_policy,
                emit_spinner_policy_fn=emit_spinner_policy,
                project_spinner_group_factory=_ProjectSpinnerGroup,
            )
            reconcile_strict_truth_after_start(
                runtime=self.runtime,
                session=session,
                build_run_state=build_success_run_state,
                reconcile_state_truth=self.runtime._reconcile_state_truth,
                emit_phase=partial(emit_startup_phase, self.runtime),
            )
            return self._finalize_success(session)
        except RuntimeError as exc:
            return finalize_failure(error=str(exc))
        except Exception as exc:
            return finalize_failure(error=str(exc))

    def _handle_restart_prestop(self, session: StartupSession) -> int | None:
        return handle_restart_prestop(
            runtime=self.runtime,
            session=session,
            suppress_progress_output=suppress_progress_output,
            terminate_restart_orphan_listeners=self._terminate_restart_orphan_listeners,
            spinner_factory=spinner,
            use_spinner_policy_fn=use_spinner_policy,
            resolve_spinner_policy_fn=resolve_spinner_policy,
            emit_spinner_policy_fn=emit_spinner_policy,
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
        process_runtime = process_runtime_impl(rt)
        port_allocator = port_allocator_impl(rt)
        terminate_restart_orphan_listeners(
            state=state,
            selected_services=selected_services,
            aggressive=aggressive,
            backend_port_base=int(rt.config.backend_port_base),
            frontend_port_base=int(rt.config.frontend_port_base),
            port_spacing=int(getattr(rt.config, "port_spacing", 20) or 20),
            listener_pids_for_port=listener_pids_for_port,
            process_cwd=process_cwd,
            terminate_pid=getattr(process_runtime, "terminate", None),
            release_port=port_allocator.release,
        )

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
            ensure_run_id(self.runtime, session)

            def report_progress_fn(route: Route, message: str, *, project: str | None = None) -> None:
                report_progress(
                    self.runtime,
                    route,
                    progress_lock=self._progress_lock,
                    last_progress_message_by_project=self._last_progress_message_by_project,
                    message=message,
                    project=project,
                )

            prepare_plan_agent_dependencies_for_launch_impl(
                rt,
                session,
                created_worktrees=created_worktrees,
                launch_config=launch_config,
                report_progress=report_progress_fn,
                prepare_fn=prepare_project_dependencies,
            )
        launch_result = cast(
            PlanAgentLaunchResult,
            launch_plan_agent_terminals_with_spinner_impl(
                self.runtime,
                route=session.effective_route,
                created_worktrees=created_worktrees,
                launch_config=launch_config,
                suppress_progress_output=suppress_progress_output(session.effective_route),
                launch_fn=launch_plan_agent_terminals,
            ),
        )
        session.plan_agent_launch_result = launch_result
        session.plan_agent_attach_target = launch_result.attach_target
        validate_plan_agent_handoff_with_attach_target(
            self.runtime,
            validate_plan_agent_attach_target,
            session,
            phase="post_launch",
        )
        emit_plan_agent_launch_state_impl(self.runtime, session, launch_result)
        if should_fail_for_plan_agent_launch_result_impl(session, launch_result):
            raise RuntimeError(plan_agent_launch_failure_message_impl(launch_result))
        return None

    def _resolve_disabled_startup_mode(self, session: StartupSession) -> int | None:
        validate_plan_agent_handoff = partial(
            validate_plan_agent_handoff_with_attach_target,
            self.runtime,
            validate_plan_agent_attach_target,
        )
        return resolve_disabled_startup_mode(
            runtime=self.runtime,
            session=session,
            route_is_implicit_start=route_is_implicit_start,
            ensure_run_id=partial(ensure_run_id, self.runtime),
            announce_session_identifiers=partial(
                announce_session_identifiers_impl,
                self.runtime,
                headless_plan_output_only=finalization_headless_plan_output_only,
            ),
            resolved_run_id=resolved_run_id,
            build_planning_dashboard_state=build_planning_dashboard_state,
            configured_service_types_for_mode=lambda runtime_mode: configured_service_types_for_mode_impl(
                self.runtime.config,
                runtime_mode,
            ),
            emit_phase=partial(emit_startup_phase, self.runtime),
            validate_plan_agent_handoff=validate_plan_agent_handoff,
            print_plan_dry_run_preview=lambda session: print_plan_dry_run_preview_impl(
                self.runtime,
                session,
                print_fn=print,
            ),
            headless_plan_output_only=finalization_headless_plan_output_only,
            print_headless_plan_session_summary=lambda session: print_headless_plan_session_summary_impl(
                session,
                validate_plan_agent_handoff=validate_plan_agent_handoff,
                print_fn=print,
            ),
            maybe_attach_plan_agent_terminal=lambda session: maybe_attach_plan_agent_terminal_impl(
                runtime=self.runtime,
                session=session,
                validate_plan_agent_handoff=validate_plan_agent_handoff,
                attach_plan_agent_terminal=attach_plan_agent_terminal,
                print_headless_plan_session_summary=lambda session, *, attach_target: (
                    print_headless_plan_session_summary_impl(
                        session,
                        validate_plan_agent_handoff=validate_plan_agent_handoff,
                        print_fn=print,
                        attach_target=attach_target,
                    )
                ),
            ),
        )

    def _resolve_run_reuse(self, session: StartupSession) -> int | None:
        validate_plan_agent_handoff = partial(
            validate_plan_agent_handoff_with_attach_target,
            self.runtime,
            validate_plan_agent_attach_target,
        )
        return resolve_startup_run_reuse(
            runtime=self.runtime,
            session=session,
            evaluate_run_reuse_fn=evaluate_run_reuse,
            prepare_dashboard_stopped_service_restore=partial(
                prepare_dashboard_stopped_service_restore_with_runtime,
                self.runtime,
                partial(emit_startup_phase, self.runtime),
            ),
            announce_session_identifiers=partial(
                announce_session_identifiers_impl,
                self.runtime,
                headless_plan_output_only=finalization_headless_plan_output_only,
            ),
            emit_phase=partial(emit_startup_phase, self.runtime),
            headless_plan_output_only=finalization_headless_plan_output_only,
            maybe_attach_plan_agent_terminal=lambda session: maybe_attach_plan_agent_terminal_impl(
                runtime=self.runtime,
                session=session,
                validate_plan_agent_handoff=validate_plan_agent_handoff,
                attach_plan_agent_terminal=attach_plan_agent_terminal,
                print_headless_plan_session_summary=lambda session, *, attach_target: (
                    print_headless_plan_session_summary_impl(
                        session,
                        validate_plan_agent_handoff=validate_plan_agent_handoff,
                        print_fn=print,
                        attach_target=attach_target,
                    )
                ),
            ),
            print_headless_plan_session_summary=lambda session: print_headless_plan_session_summary_impl(
                session,
                validate_plan_agent_handoff=validate_plan_agent_handoff,
                print_fn=print,
            ),
            print_plan_dry_run_preview=lambda session: print_plan_dry_run_preview_impl(
                self.runtime,
                session,
                print_fn=print,
            ),
            configured_service_types_for_mode=lambda runtime_mode: configured_service_types_for_mode_impl(
                self.runtime.config,
                runtime_mode,
            ),
            emit_snapshot=partial(emit_startup_plan_handoff_snapshot, self.runtime),
            replace_existing_project_services_for_fresh_start=lambda session, *, candidate_state, reason: (
                replace_existing_project_services_for_fresh_start_with_defaults(
                    runtime=self.runtime,
                    session=session,
                    candidate_state=candidate_state,
                    reason=reason,
                    configured_service_types=set(
                        configured_service_types_for_mode_impl(self.runtime.config, session.runtime_mode)
                    ),
                    additional_services=tuple(getattr(self.runtime.config, "additional_services", ()) or ()),
                    announce_session_identifiers=partial(
                        announce_session_identifiers_impl,
                        self.runtime,
                        headless_plan_output_only=finalization_headless_plan_output_only,
                    ),
                    report_progress=lambda route, message: report_progress(
                        self.runtime,
                        route,
                        progress_lock=self._progress_lock,
                        last_progress_message_by_project=self._last_progress_message_by_project,
                        message=message,
                    ),
                    terminate_restart_orphan_listeners=self._terminate_restart_orphan_listeners,
                )
            ),
        )

    def _finalize_success(self, session: StartupSession) -> int:
        validate_plan_agent_handoff = partial(
            validate_plan_agent_handoff_with_attach_target,
            self.runtime,
            validate_plan_agent_attach_target,
        )

        def finalize_degraded_handoff(session: StartupSession) -> int:
            return finalize_plan_agent_degraded_handoff(
                runtime=self.runtime,
                session=session,
                ensure_run_id=partial(ensure_run_id, self.runtime),
                validate_plan_agent_handoff=validate_plan_agent_handoff,
                build_success_run_state=build_success_run_state,
                emit_phase=partial(emit_startup_phase, self.runtime),
                render_plan_agent_degraded_handoff=lambda session: (
                    finalization_render_plan_agent_degraded_handoff_for_terminal(
                        self.runtime,
                        session,
                        stream=sys.stdout,
                        print_fn=print,
                    )
                ),
                headless_plan_output_only=finalization_headless_plan_output_only,
                maybe_attach_plan_agent_terminal=lambda session: maybe_attach_plan_agent_terminal_impl(
                    runtime=self.runtime,
                    session=session,
                    validate_plan_agent_handoff=validate_plan_agent_handoff,
                    attach_plan_agent_terminal=attach_plan_agent_terminal,
                    print_headless_plan_session_summary=lambda session, *, attach_target: (
                        print_headless_plan_session_summary_impl(
                            session,
                            validate_plan_agent_handoff=validate_plan_agent_handoff,
                            print_fn=print,
                            attach_target=attach_target,
                        )
                    ),
                ),
            )

        return finalize_successful_startup(
            runtime=self.runtime,
            session=session,
            ensure_run_id=partial(ensure_run_id, self.runtime),
            validate_plan_agent_handoff=validate_plan_agent_handoff,
            build_success_run_state=build_success_run_state,
            emit_preserved_service_merge=lambda session: finalization_emit_preserved_service_merge(
                self.runtime,
                session,
            ),
            emit_phase=partial(emit_startup_phase, self.runtime),
            requirements_timing_enabled=lambda route: requirements_timing_enabled_impl(self, route),
            suppress_timing_output=suppress_timing_output,
            print_startup_summary=lambda **kwargs: print_startup_summary_impl(self, **kwargs),
            startup_breakdown_enabled=lambda route: startup_breakdown_enabled_impl(self, route),
            suppress_progress_output=suppress_progress_output,
            print_restart_port_rebound_summary=lambda session: print_restart_port_rebound_summary_impl(
                self.runtime,
                session,
                print_fn=print,
            ),
            emit_snapshot=partial(emit_startup_plan_handoff_snapshot, self.runtime),
            headless_plan_output_only=finalization_headless_plan_output_only,
            print_headless_plan_session_summary=lambda session: print_headless_plan_session_summary_impl(
                session,
                validate_plan_agent_handoff=validate_plan_agent_handoff,
                print_fn=print,
            ),
            maybe_attach_plan_agent_terminal=lambda session: maybe_attach_plan_agent_terminal_impl(
                runtime=self.runtime,
                session=session,
                validate_plan_agent_handoff=validate_plan_agent_handoff,
                attach_plan_agent_terminal=attach_plan_agent_terminal,
                print_headless_plan_session_summary=lambda session, *, attach_target: (
                    print_headless_plan_session_summary_impl(
                        session,
                        validate_plan_agent_handoff=validate_plan_agent_handoff,
                        print_fn=print,
                        attach_target=attach_target,
                    )
                ),
            ),
            finalize_plan_agent_degraded_handoff=finalize_degraded_handoff,
        )

    def start_project_context(
        self,
        *,
        context: ProjectContextLike,
        mode: str,
        route: Route,
        run_id: str,
    ) -> ProjectStartupResult:
        return start_project_context_impl(
            self,
            context=context,
            mode=mode,
            route=route,
            run_id=run_id,
            report_progress_fn=lambda route, message, *, project=None: report_progress(
                self.runtime,
                route,
                progress_lock=self._progress_lock,
                last_progress_message_by_project=self._last_progress_message_by_project,
                message=message,
                project=project,
            ),
        )

    def start_requirements_for_project(
        self,
        context: ProjectContextLike,
        *,
        mode: str,
        route: Route | None = None,
    ) -> RequirementsResult:
        return start_requirements_for_project_impl(
            self,
            context,
            mode=mode,
            route=route,
            report_progress_fn=lambda route, message, *, project=None: report_progress(
                self.runtime,
                route,
                progress_lock=self._progress_lock,
                last_progress_message_by_project=self._last_progress_message_by_project,
                message=message,
                project=project,
            ),
            suppress_timing_output_fn=suppress_timing_output,
        )

    def start_project_services(
        self,
        context: ProjectContextLike,
        *,
        requirements: RequirementsResult,
        run_id: str,
        route: Route | None = None,
    ) -> dict[str, ServiceRecord]:
        return start_project_services_impl(self, context, requirements=requirements, run_id=run_id, route=route)
