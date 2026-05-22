from __future__ import annotations

from collections.abc import Callable
import time
from typing import Any, cast

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.engine_runtime_startup_support import evaluate_run_reuse, mark_run_reused
from envctl_engine.runtime.runtime_context import resolve_state_repository
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.startup.finalization import (
    build_planning_dashboard_state,
    headless_plan_output_only,
    maybe_attach_plan_agent_terminal,
    print_headless_plan_session_summary,
    print_plan_dry_run_preview,
)
from envctl_engine.startup.plan_agent_handoff import validate_plan_agent_handoff_with_attach_target
from envctl_engine.startup.run_reuse_support import (
    RunReuseDecision,
    prepare_dashboard_stopped_service_restore_with_runtime,
    replace_existing_project_services_for_fresh_start_with_defaults,
    run_reuse_debug_orch_groups,
)
from envctl_engine.startup.session import StartupSession
from envctl_engine.startup.session_lifecycle import announce_session_identifiers, emit_startup_phase
from envctl_engine.startup.service_bootstrap_domain import configured_service_types_for_mode
from envctl_engine.startup.startup_progress import report_progress
from envctl_engine.ui.debug_snapshot import emit_startup_plan_handoff_snapshot


def resolve_startup_run_reuse(
    *,
    runtime: Any,
    session: StartupSession,
    evaluate_run_reuse_fn: Callable[..., RunReuseDecision],
    prepare_dashboard_stopped_service_restore: Callable[..., bool],
    announce_session_identifiers: Callable[[StartupSession], None],
    emit_phase: Callable[..., None],
    headless_plan_output_only: Callable[[StartupSession], bool],
    maybe_attach_plan_agent_terminal: Callable[[StartupSession], int | None],
    print_headless_plan_session_summary: Callable[[StartupSession], None],
    print_plan_dry_run_preview: Callable[[StartupSession], None],
    configured_service_types_for_mode: Callable[[str], set[str]],
    emit_snapshot: Callable[..., None],
    replace_existing_project_services_for_fresh_start: Callable[..., None],
    print_fn: Callable[[str], None] = print,
) -> int | None:
    route = session.effective_route
    runtime_mode = session.runtime_mode
    requested_command = session.requested_command
    debug_orch_groups = run_reuse_debug_orch_groups(runtime, requested_command=requested_command)
    if requested_command != "restart":
        reuse_started = time.monotonic()
        decision = evaluate_run_reuse_fn(
            runtime,
            runtime_mode=runtime_mode,
            route=route,
            contexts=cast(list[object], session.selected_contexts),
        )
        candidate_state = decision.candidate_state
        candidate_run_id = candidate_state.run_id if candidate_state is not None else None
        runtime._emit(
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
        if (
            decision.decision_kind in {"resume_exact", "resume_subset"}
            and candidate_state is not None
            and prepare_dashboard_stopped_service_restore(
                session,
                candidate_state=candidate_state,
                reuse_started=reuse_started,
                decision_kind=decision.decision_kind,
            )
        ):
            return None
        if decision.decision_kind in {"resume_exact", "resume_subset"} and candidate_state is not None:
            return _resume_matching_run(
                runtime=runtime,
                session=session,
                route=route,
                runtime_mode=runtime_mode,
                decision=decision,
                candidate_state=candidate_state,
                reuse_started=reuse_started,
                announce_session_identifiers=announce_session_identifiers,
                emit_phase=emit_phase,
                headless_plan_output_only=headless_plan_output_only,
                maybe_attach_plan_agent_terminal=maybe_attach_plan_agent_terminal,
                replace_existing_project_services_for_fresh_start=replace_existing_project_services_for_fresh_start,
            )
        if decision.decision_kind == "reuse_expand" and candidate_state is not None:
            session.run_id = None
            session.preserved_services = dict(candidate_state.services)
            session.preserved_requirements = dict(candidate_state.requirements)
            session.base_metadata = mark_run_reused(candidate_state.metadata, reason="reuse_expand")
            state_project_names = {
                str(project.get("name", "")).strip().casefold()
                for project in decision.state_projects
                if str(project.get("name", "")).strip()
            }
            if state_project_names:
                session.contexts_to_start = [
                    context
                    for context in session.selected_contexts
                    if str(getattr(context, "name", "")).strip().casefold() not in state_project_names
                ]
            emit_phase(
                session,
                "auto_resume_evaluate",
                reuse_started,
                status="expand",
                match_mode="expand",
                state_project_count=len(decision.state_projects),
                selected_project_count=len(session.selected_contexts),
            )
            runtime._emit(
                "state.run_reuse.applied",
                run_id=candidate_state.run_id,
                mode=runtime_mode,
                command=route.command,
                decision_kind=decision.decision_kind,
                reason=decision.reason,
                preserved_services=sorted(session.preserved_services),
            )
        elif decision.decision_kind == "resume_dashboard_exact" and candidate_state is not None:
            return _resume_dashboard_run(
                runtime=runtime,
                session=session,
                route=route,
                runtime_mode=runtime_mode,
                decision=decision,
                candidate_state=candidate_state,
                reuse_started=reuse_started,
                announce_session_identifiers=announce_session_identifiers,
                emit_phase=emit_phase,
                headless_plan_output_only=headless_plan_output_only,
                maybe_attach_plan_agent_terminal=maybe_attach_plan_agent_terminal,
                print_headless_plan_session_summary=print_headless_plan_session_summary,
                print_plan_dry_run_preview=print_plan_dry_run_preview,
                configured_service_types_for_mode=configured_service_types_for_mode,
                print_fn=print_fn,
            )
        else:
            emit_phase(
                session,
                "auto_resume_evaluate",
                reuse_started,
                status="skipped" if candidate_state is not None else "none",
                reason=decision.reason if candidate_state is not None else None,
                state_project_count=len(decision.state_projects),
                selected_project_count=len(session.selected_contexts),
            )
            if candidate_state is not None:
                runtime._emit(
                    "state.auto_resume.skipped",
                    reason=decision.reason,
                    state_projects=[project["name"] for project in decision.state_projects],
                    selected_projects=[project["name"] for project in decision.selected_projects],
                    mode=runtime_mode,
                    command=route.command,
                )
                runtime._emit(
                    "state.run_reuse.skipped",
                    run_id=candidate_state.run_id,
                    reason=decision.reason,
                    mode=runtime_mode,
                    command=route.command,
                    mismatch_details=decision.mismatch_details,
                )
                replace_existing_project_services_for_fresh_start(
                    session,
                    candidate_state=candidate_state,
                    reason=decision.reason,
                )

    if route.command == "plan" and bool(route.flags.get("planning_prs")):
        runtime._emit("planning.projects.start", projects=[context.name for context in session.selected_contexts])
        code = runtime._run_pr_action(route, session.selected_contexts)
        runtime._emit(
            "planning.projects.finish", code=code, projects=[context.name for context in session.selected_contexts]
        )
        if code == 0:
            print_fn("Planning PR mode complete; skipping service startup.")
        return code

    emit_snapshot(
        session,
        "startup_branch_enter",
        command=requested_command,
        mode=runtime_mode,
        orch_group=sorted(debug_orch_groups) or None,
    )
    return None


def resolve_startup_run_reuse_with_runtime(
    runtime: Any,
    session: StartupSession,
    *,
    terminate_restart_orphan_listeners: Callable[..., None],
    validate_attach_target_fn: Callable[..., Any],
    attach_plan_agent_terminal: Callable[..., Any],
    progress_lock: Any,
    last_progress_message_by_project: dict[str, str],
    print_fn: Callable[[str], None] = print,
) -> int | None:
    def validate_plan_agent_handoff(session: StartupSession, *, phase: str) -> None:
        validate_plan_agent_handoff_with_attach_target(
            runtime,
            validate_attach_target_fn,
            session,
            phase=phase,
        )

    def report_progress_fn(route: Route, message: str) -> None:
        report_progress(
            runtime,
            route,
            progress_lock=progress_lock,
            last_progress_message_by_project=last_progress_message_by_project,
            message=message,
        )

    return resolve_startup_run_reuse(
        runtime=runtime,
        session=session,
        evaluate_run_reuse_fn=evaluate_run_reuse,
        prepare_dashboard_stopped_service_restore=partial_prepare_dashboard_stopped_restore(runtime),
        announce_session_identifiers=lambda session: announce_session_identifiers(
            runtime,
            session,
            headless_plan_output_only=headless_plan_output_only,
        ),
        emit_phase=lambda *args, **kwargs: emit_startup_phase(runtime, *args, **kwargs),
        headless_plan_output_only=headless_plan_output_only,
        maybe_attach_plan_agent_terminal=lambda session: maybe_attach_plan_agent_terminal(
            runtime=runtime,
            session=session,
            validate_plan_agent_handoff=validate_plan_agent_handoff,
            attach_plan_agent_terminal=attach_plan_agent_terminal,
            print_headless_plan_session_summary=lambda session, *, attach_target: (
                print_headless_plan_session_summary(
                    session,
                    validate_plan_agent_handoff=validate_plan_agent_handoff,
                    print_fn=print_fn,
                    attach_target=attach_target,
                )
            ),
        ),
        print_headless_plan_session_summary=lambda session: print_headless_plan_session_summary(
            session,
            validate_plan_agent_handoff=validate_plan_agent_handoff,
            print_fn=print_fn,
        ),
        print_plan_dry_run_preview=lambda session: print_plan_dry_run_preview(
            runtime,
            session,
            print_fn=print_fn,
        ),
        configured_service_types_for_mode=lambda runtime_mode: set(
            configured_service_types_for_mode(runtime.config, runtime_mode)
        ),
        emit_snapshot=lambda *args, **kwargs: emit_startup_plan_handoff_snapshot(runtime, *args, **kwargs),
        replace_existing_project_services_for_fresh_start=lambda session, *, candidate_state, reason: (
            replace_existing_project_services_for_fresh_start_with_defaults(
                runtime=runtime,
                session=session,
                candidate_state=candidate_state,
                reason=reason,
                configured_service_types=set(configured_service_types_for_mode(runtime.config, session.runtime_mode)),
                additional_services=tuple(getattr(runtime.config, "additional_services", ()) or ()),
                announce_session_identifiers=lambda session: announce_session_identifiers(
                    runtime,
                    session,
                    headless_plan_output_only=headless_plan_output_only,
                ),
                report_progress=report_progress_fn,
                terminate_restart_orphan_listeners=terminate_restart_orphan_listeners,
            )
        ),
        print_fn=print_fn,
    )


def partial_prepare_dashboard_stopped_restore(runtime: Any) -> Callable[..., bool]:
    return lambda *args, **kwargs: prepare_dashboard_stopped_service_restore_with_runtime(
        runtime,
        lambda *phase_args, **phase_kwargs: emit_startup_phase(runtime, *phase_args, **phase_kwargs),
        *args,
        **kwargs,
    )


def _resume_matching_run(
    *,
    runtime: Any,
    session: StartupSession,
    route: Route,
    runtime_mode: str,
    decision: RunReuseDecision,
    candidate_state: Any,
    reuse_started: float,
    announce_session_identifiers: Callable[[StartupSession], None],
    emit_phase: Callable[..., None],
    headless_plan_output_only: Callable[[StartupSession], bool],
    maybe_attach_plan_agent_terminal: Callable[[StartupSession], int | None],
    replace_existing_project_services_for_fresh_start: Callable[..., None],
) -> int | None:
    previous_run_id = session.run_id
    previous_identifiers_announced = session.identifiers_announced
    session.run_id = candidate_state.run_id
    announce_session_identifiers(session)
    emit_phase(
        session,
        "auto_resume_evaluate",
        reuse_started,
        status="resume",
        match_mode="exact" if decision.decision_kind == "resume_exact" else "subset",
        state_project_count=len(decision.state_projects),
        selected_project_count=len(session.selected_contexts),
    )
    runtime._emit(
        "state.auto_resume",
        run_id=candidate_state.run_id,
        mode=runtime_mode,
        command=route.command,
        match_mode="exact" if decision.decision_kind == "resume_exact" else "subset",
        selected_projects=[project["name"] for project in decision.selected_projects],
    )
    runtime._emit(
        "state.run_reuse.applied",
        run_id=candidate_state.run_id,
        mode=runtime_mode,
        command=route.command,
        decision_kind=decision.decision_kind,
        reason=decision.reason,
    )
    attach_plan_agent_after_resume = (
        route.command == "plan"
        and not headless_plan_output_only(session)
        and session.plan_agent_attach_target is not None
    )
    resume_flags = {
        **route.flags,
        "_resume_source_command": route.command,
        "_run_reuse_reason": decision.decision_kind,
    }
    if attach_plan_agent_after_resume:
        resume_flags["batch"] = True
    resume_route = Route(
        command="resume",
        mode=runtime_mode,
        raw_args=route.raw_args,
        passthrough_args=route.passthrough_args,
        projects=route.projects,
        flags=resume_flags,
    )
    resume_code = runtime._resume(resume_route)
    if int(resume_code) == 0:
        if attach_plan_agent_after_resume:
            attach_code = maybe_attach_plan_agent_terminal(session)
            if attach_code is not None:
                return attach_code
        return 0
    session.run_id = previous_run_id
    session.identifiers_announced = previous_identifiers_announced
    runtime._emit(
        "state.auto_resume.skipped",
        reason="resume_failed",
        resume_code=int(resume_code),
        state_projects=[project["name"] for project in decision.state_projects],
        selected_projects=[project["name"] for project in decision.selected_projects],
        mode=runtime_mode,
        command=route.command,
    )
    runtime._emit(
        "state.run_reuse.skipped",
        run_id=candidate_state.run_id,
        reason="resume_failed",
        resume_code=int(resume_code),
        mode=runtime_mode,
        command=route.command,
    )
    replace_existing_project_services_for_fresh_start(
        session,
        candidate_state=candidate_state,
        reason=decision.reason,
    )
    return None


def _resume_dashboard_run(
    *,
    runtime: Any,
    session: StartupSession,
    route: Route,
    runtime_mode: str,
    decision: RunReuseDecision,
    candidate_state: Any,
    reuse_started: float,
    announce_session_identifiers: Callable[[StartupSession], None],
    emit_phase: Callable[..., None],
    headless_plan_output_only: Callable[[StartupSession], bool],
    maybe_attach_plan_agent_terminal: Callable[[StartupSession], int | None],
    print_headless_plan_session_summary: Callable[[StartupSession], None],
    print_plan_dry_run_preview: Callable[[StartupSession], None],
    configured_service_types_for_mode: Callable[[str], set[str]],
    print_fn: Callable[[str], None],
) -> int | None:
    session.run_id = candidate_state.run_id
    announce_session_identifiers(session)
    candidate_state.metadata = build_planning_dashboard_state(
        runtime,
        route=route,
        runtime_mode=session.runtime_mode,
        run_id=candidate_state.run_id,
        project_contexts=session.selected_contexts,
        configured_service_types=configured_service_types_for_mode(session.runtime_mode),
        base_metadata=mark_run_reused(candidate_state.metadata, reason="resume_dashboard_exact"),
    ).metadata
    resolve_state_repository(runtime).save_resume_state(
        state=candidate_state,
        emit=runtime._emit,
        runtime_map_builder=cast(Callable[[object], dict[str, object]], build_runtime_map),
    )
    emit_phase(
        session,
        "auto_resume_evaluate",
        reuse_started,
        status="dashboard_resume",
        match_mode="exact",
        state_project_count=len(decision.state_projects),
        selected_project_count=len(session.selected_contexts),
    )
    runtime._emit(
        "state.run_reuse.applied",
        run_id=candidate_state.run_id,
        mode=runtime_mode,
        command=route.command,
        decision_kind=decision.decision_kind,
        reason=decision.reason,
    )
    runtime._emit(
        "state.dashboard_resume",
        run_id=candidate_state.run_id,
        mode=runtime_mode,
        command=route.command,
    )
    if headless_plan_output_only(session):
        print_headless_plan_session_summary(session)
        return 0
    enter_interactive_dashboard = runtime._should_enter_post_start_interactive(route)
    if route.command == "plan":
        print_plan_dry_run_preview(session)
        print_fn(
            "Planning mode complete; skipping service startup because "
            f"envctl runs are disabled for {session.runtime_mode}."
        )
        attach_code = maybe_attach_plan_agent_terminal(session)
        if attach_code is not None:
            return attach_code
    elif not enter_interactive_dashboard:
        print_fn(
            f"envctl runs are disabled for {session.runtime_mode}; " "opening dashboard without starting services."
        )
    if enter_interactive_dashboard:
        return runtime._run_interactive_dashboard_loop(candidate_state)
    return 0
