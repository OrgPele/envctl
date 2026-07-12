from __future__ import annotations

from functools import partial
from typing import Any

from envctl_engine.planning.plan_agent.launch import launch_plan_agent_terminals
from envctl_engine.planning.plan_agent.omx_transport import validate_plan_agent_attach_target
from envctl_engine.planning.plan_agent.tmux_transport import attach_plan_agent_terminal
from envctl_engine.runtime.lifecycle_operation_lease import release_lifecycle_operation
from envctl_engine.startup.context_selection import select_startup_contexts
from envctl_engine.startup.dependency_bootstrap import prepare_project_dependencies
from envctl_engine.startup.disabled_startup_resolution import resolve_disabled_startup_mode_with_runtime
from envctl_engine.startup.execution_preparation import prepare_startup_execution_with_runtime
from envctl_engine.startup.finalization import (
    build_success_run_state,
    finalize_failed_startup,
    finalize_successful_startup_with_runtime,
    headless_plan_output_only,
    render_final_failure_status,
    render_project_startup_warnings_for_route,
    resolve_plan_dry_run,
)
from envctl_engine.startup.plan_agent_handoff import (
    launch_plan_agent_terminals_with_spinner,
    prepare_and_launch_plan_agent_worktrees,
    prepare_plan_agent_dependencies_for_launch,
    record_plan_agent_handoff_local_startup_failure,
    should_degrade_to_validated_plan_agent_handoff,
    validate_plan_agent_handoff_with_attach_target,
)
from envctl_engine.startup.post_start_reconcile import reconcile_strict_truth_after_start
from envctl_engine.startup.restart_prestop_support import (
    apply_restart_ports_to_contexts,
    handle_restart_prestop,
    terminate_restart_orphan_listeners_with_runtime,
)
from envctl_engine.startup.run_reuse_resolution import resolve_startup_run_reuse_with_runtime
from envctl_engine.startup.selected_context_startup import start_selected_contexts_with_runtime
from envctl_engine.startup.session import StartupSession
from envctl_engine.startup.session_lifecycle import (
    announce_session_identifiers,
    create_startup_session,
    emit_startup_phase,
    ensure_run_id,
    resolved_run_id,
    validate_startup_route_contract,
)
from envctl_engine.startup.startup_progress import report_progress, suppress_progress_output
from envctl_engine.startup.startup_selection_support import (
    port_allocator,
    select_start_tree_projects,
    trees_start_selection_required,
)
from envctl_engine.ui.debug_snapshot import emit_startup_plan_handoff_snapshot
from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy


def execute_startup_lifecycle(orchestrator: Any, route: Any) -> int:
    runtime = orchestrator.runtime
    session = create_startup_session(runtime, route)
    finalize_failure = partial(
        finalize_failed_startup,
        runtime=runtime,
        session=session,
        ensure_run_id=partial(ensure_run_id, runtime),
        port_allocator=port_allocator,
        emit_phase=partial(emit_startup_phase, runtime),
        render_final_failure_status=render_final_failure_status,
    )
    try:
        terminate_restart_orphans = partial(terminate_restart_orphan_listeners_with_runtime, runtime)
        for phase in _pre_start_phases(
            orchestrator=orchestrator,
            session=session,
            terminate_restart_orphans=terminate_restart_orphans,
        ):
            code = phase(session)
            if code is not None:
                return code
        _execute_selected_startup(orchestrator=orchestrator, session=session)
        reconcile_strict_truth_after_start(
            runtime=runtime,
            session=session,
            build_run_state=build_success_run_state,
            reconcile_state_truth=runtime._reconcile_state_truth,
            emit_phase=partial(emit_startup_phase, runtime),
        )
        return finalize_successful_startup_with_runtime(
            runtime,
            session,
            validate_plan_agent_handoff=partial(
                validate_plan_agent_handoff_with_attach_target,
                runtime,
                validate_plan_agent_attach_target,
            ),
        )
    except RuntimeError as exc:
        return _finalize_startup_exception(
            runtime=runtime,
            session=session,
            error=exc,
            finalize_failure=finalize_failure,
        )
    except Exception as exc:
        return _finalize_startup_exception(
            runtime=runtime,
            session=session,
            error=exc,
            finalize_failure=finalize_failure,
        )
    except BaseException as exc:  # noqa: BLE001 - cancellation still requires failure finalization
        try:
            _finalize_startup_exception(
                runtime=runtime,
                session=session,
                error=exc,
                finalize_failure=finalize_failure,
            )
        except BaseException as finalization_error:  # noqa: BLE001
            if finalization_error is not exc:
                try:
                    exc.add_note(f"startup cancellation finalization also failed: {finalization_error}")
                except Exception:  # noqa: BLE001
                    pass
        raise


def _finalize_startup_exception(
    *,
    runtime: Any,
    session: StartupSession,
    error: BaseException,
    finalize_failure: Any,
) -> int:
    if not session.authority_committed:
        return int(finalize_failure(error=str(error)))
    # The durable active revision is already committed. Presentation, terminal
    # attachment, or dashboard failures after this boundary must not terminate
    # its services or rewrite it as a failed startup.
    release_lifecycle_operation(runtime)
    try:
        runtime._emit(
            "startup.post_commit_error",
            run_id=session.run_id,
            error=str(error),
        )
    except Exception:  # noqa: BLE001
        pass
    print(f"Startup state is active, but post-start handling failed: {error}")
    return 1


def _pre_start_phases(
    *, orchestrator: Any, session: StartupSession, terminate_restart_orphans: Any
) -> tuple[Any, ...]:
    runtime = orchestrator.runtime

    def apply_restart_ports(session: StartupSession, contexts: list[Any]) -> None:
        apply_restart_ports_to_contexts(
            session.restart_state,
            route=session.effective_route,
            contexts=contexts,
            project_name_from_service=runtime._project_name_from_service,
            set_plan_port=runtime._set_plan_port,
        )

    return (
        partial(validate_startup_route_contract, runtime, emit_phase=partial(emit_startup_phase, runtime)),
        lambda _: handle_restart_prestop(
            runtime=runtime,
            session=session,
            suppress_progress_output=suppress_progress_output,
            terminate_restart_orphan_listeners=terminate_restart_orphans,
            spinner_factory=spinner,
            use_spinner_policy_fn=use_spinner_policy,
            resolve_spinner_policy_fn=resolve_spinner_policy,
            emit_spinner_policy_fn=emit_spinner_policy,
        ),
        lambda _: select_startup_contexts(
            runtime=runtime,
            session=session,
            trees_start_selection_required=trees_start_selection_required,
            select_start_tree_projects=select_start_tree_projects,
            apply_restart_ports=apply_restart_ports,
            emit_phase=partial(emit_startup_phase, runtime),
            emit_snapshot=partial(emit_startup_plan_handoff_snapshot, runtime),
        ),
        partial(resolve_plan_dry_run, runtime, print_fn=print),
        lambda _: prepare_and_launch_plan_agent_worktrees(
            runtime,
            session,
            ensure_run_id=partial(ensure_run_id, runtime),
            report_progress=lambda route, message, *, project=None: report_progress(
                runtime,
                route,
                progress_lock=orchestrator._progress_lock,
                last_progress_message_by_project=orchestrator._last_progress_message_by_project,
                message=message,
                project=project,
            ),
            prepare_dependencies_for_launch=prepare_plan_agent_dependencies_for_launch,
            prepare_fn=prepare_project_dependencies,
            launch_with_spinner=launch_plan_agent_terminals_with_spinner,
            launch_fn=launch_plan_agent_terminals,
            suppress_progress_output=suppress_progress_output,
            validate_attach_target_fn=validate_plan_agent_attach_target,
        ),
        lambda _: resolve_startup_run_reuse_with_runtime(
            runtime,
            session,
            terminate_restart_orphan_listeners=terminate_restart_orphans,
            validate_attach_target_fn=validate_plan_agent_attach_target,
            attach_plan_agent_terminal=attach_plan_agent_terminal,
            progress_lock=orchestrator._progress_lock,
            last_progress_message_by_project=orchestrator._last_progress_message_by_project,
        ),
        lambda _: resolve_disabled_startup_mode_with_runtime(
            runtime,
            session,
            validate_attach_target_fn=validate_plan_agent_attach_target,
            attach_plan_agent_terminal=attach_plan_agent_terminal,
        ),
    )


def _execute_selected_startup(*, orchestrator: Any, session: StartupSession) -> None:
    runtime = orchestrator.runtime
    ensure_run_id(runtime, session)
    announce_session_identifiers(runtime, session, headless_plan_output_only=headless_plan_output_only)
    prepare_startup_execution_with_runtime(runtime, session)
    start_selected_contexts_with_runtime(
        runtime,
        session=session,
        suppress_progress_output=suppress_progress_output,
        resolved_run_id=resolved_run_id,
        render_project_startup_warnings=partial(
            render_project_startup_warnings_for_route,
            runtime,
            suppress_progress_output=suppress_progress_output,
        ),
        should_degrade_to_plan_agent_handoff=lambda session, error: should_degrade_to_validated_plan_agent_handoff(
            runtime,
            session,
            error=error,
            validate_attach_target_fn=validate_plan_agent_attach_target,
        ),
        record_plan_agent_handoff_local_startup_failure=partial(
            record_plan_agent_handoff_local_startup_failure,
            runtime,
        ),
        spinner_factory=spinner,
        use_spinner_policy_fn=use_spinner_policy,
        resolve_spinner_policy_fn=resolve_spinner_policy,
        emit_spinner_policy_fn=emit_spinner_policy,
        project_spinner_group_factory=orchestrator.project_spinner_group_factory,
    )
