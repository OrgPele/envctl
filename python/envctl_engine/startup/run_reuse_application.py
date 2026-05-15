from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Callable, cast

from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.services import service_project_name, service_slug_from_record
from envctl_engine.startup.execution_plan import RunReuseApplicationResult
from envctl_engine.startup.run_reuse_support import RunReuseDecision, mark_run_reused
from envctl_engine.startup.session import StartupSession


def apply_run_reuse_decision(
    orchestrator: object,
    session: StartupSession,
    decision: RunReuseDecision,
    *,
    reuse_started: float,
    mark_run_reused_fn: Callable[..., dict[str, object]] | None = None,
) -> RunReuseApplicationResult:
    mark_reused = mark_run_reused_fn or mark_run_reused
    rt = orchestrator.runtime
    route = session.effective_route
    runtime_mode = session.runtime_mode
    candidate_state = decision.candidate_state
    if candidate_state is None:
        orchestrator._emit_phase(
            session,
            "auto_resume_evaluate",
            reuse_started,
            status="none",
            reason=None,
            state_project_count=len(decision.state_projects),
            selected_project_count=len(session.selected_contexts),
        )
        return RunReuseApplicationResult(status="continue_fresh", contexts_to_start=tuple(session.contexts_to_start))

    if (
        decision.decision_kind in {"resume_exact", "resume_subset"}
        and _prepare_dashboard_stopped_service_restore(
            orchestrator,
            session,
            candidate_state=candidate_state,
            reuse_started=reuse_started,
            decision_kind=decision.decision_kind,
            mark_run_reused_fn=mark_reused,
        )
    ):
        return RunReuseApplicationResult(
            status="continue",
            updated_route=session.effective_route,
            preserved_services=dict(session.preserved_services),
            preserved_requirements=dict(session.preserved_requirements),
            contexts_to_start=tuple(session.contexts_to_start),
            base_metadata=dict(session.base_metadata),
            reuse_decision_kind="restore_stopped_services",
        )

    if decision.decision_kind in {"resume_exact", "resume_subset"}:
        previous_run_id = session.run_id
        previous_identifiers_announced = session.identifiers_announced
        session.run_id = candidate_state.run_id
        orchestrator._announce_session_identifiers(session)
        match_mode = "exact" if decision.decision_kind == "resume_exact" else "subset"
        orchestrator._emit_phase(
            session,
            "auto_resume_evaluate",
            reuse_started,
            status="resume",
            match_mode=match_mode,
            state_project_count=len(decision.state_projects),
            selected_project_count=len(session.selected_contexts),
        )
        rt._emit(
            "state.auto_resume",
            run_id=candidate_state.run_id,
            mode=runtime_mode,
            command=route.command,
            match_mode=match_mode,
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
        attach_plan_agent_after_resume = (
            route.command == "plan"
            and not orchestrator._headless_plan_output_only(session)
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
        resume_code = rt._resume(resume_route)
        if int(resume_code) == 0:
            if attach_plan_agent_after_resume:
                attach_code = orchestrator._maybe_attach_plan_agent_terminal(session)
                if attach_code is not None:
                    return RunReuseApplicationResult(status="stopped", return_code=attach_code)
            return RunReuseApplicationResult(status="stopped", return_code=0, updated_route=resume_route)
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
        return RunReuseApplicationResult(status="continue_fresh", contexts_to_start=tuple(session.contexts_to_start))

    if decision.decision_kind == "reuse_expand":
        missing_services = rt._reconcile_state_truth(candidate_state)
        if not missing_services:
            session.base_metadata = mark_reused(candidate_state.metadata, reason="reuse_expand")
            session.resumed_context_names = [
                str(project["name"]) for project in decision.state_projects if project.get("name") is not None
            ]
            session.preserved_services = dict(candidate_state.services)
            session.preserved_requirements = dict(candidate_state.requirements)
            resumed_names = {name.lower() for name in session.resumed_context_names}
            session.contexts_to_start = [
                context
                for context in session.selected_contexts
                if str(context.name).strip().lower() not in resumed_names
            ]
            orchestrator._emit_phase(
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
            return RunReuseApplicationResult(
                status="continue",
                preserved_services=dict(session.preserved_services),
                preserved_requirements=dict(session.preserved_requirements),
                contexts_to_start=tuple(session.contexts_to_start),
                resumed_context_names=tuple(session.resumed_context_names),
                base_metadata=dict(session.base_metadata),
                reuse_decision_kind=decision.decision_kind,
            )
        orchestrator._emit_phase(
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
        return RunReuseApplicationResult(status="continue_fresh", contexts_to_start=tuple(session.contexts_to_start))

    if decision.decision_kind == "resume_dashboard_exact":
        return RunReuseApplicationResult(
            status="dashboard_resume",
            contexts_to_start=tuple(session.contexts_to_start),
            reuse_decision_kind=decision.decision_kind,
        )

    orchestrator._emit_phase(
        session,
        "auto_resume_evaluate",
        reuse_started,
        status="skipped",
        reason=decision.reason,
        state_project_count=len(decision.state_projects),
        selected_project_count=len(session.selected_contexts),
    )
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
    _replace_existing_project_services_for_fresh_start(
        orchestrator,
        session,
        candidate_state=candidate_state,
        reason=decision.reason,
    )
    return RunReuseApplicationResult(status="continue_fresh", contexts_to_start=tuple(session.contexts_to_start))


def resolve_run_reuse_for_session(
    orchestrator: object,
    session: StartupSession,
    *,
    evaluate_run_reuse_fn: Callable[..., object],
    mark_run_reused_fn: Callable[..., dict[str, object]],
    build_planning_dashboard_state_fn: Callable[..., object],
    resolve_state_repository_fn: Callable[[object], object],
    build_runtime_map_fn: Callable[[object], dict[str, object]],
) -> int | None:
    rt = orchestrator.runtime
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
            evaluate_run_reuse_fn(
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
        result = apply_run_reuse_decision(
            orchestrator,
            session,
            decision,
            reuse_started=reuse_started,
            mark_run_reused_fn=mark_run_reused_fn,
        )
        if result.return_code is not None:
            return result.return_code
        if result.status == "dashboard_resume" and candidate_state is not None:
            return _complete_dashboard_resume(
                orchestrator,
                session,
                decision=decision,
                candidate_state=candidate_state,
                reuse_started=reuse_started,
                mark_run_reused_fn=mark_run_reused_fn,
                build_planning_dashboard_state_fn=build_planning_dashboard_state_fn,
                resolve_state_repository_fn=resolve_state_repository_fn,
                build_runtime_map_fn=build_runtime_map_fn,
            )

    route = session.effective_route
    if route.command == "plan" and bool(route.flags.get("planning_prs")):
        rt._emit("planning.projects.start", projects=[context.name for context in session.selected_contexts])
        code = rt._run_pr_action(route, session.selected_contexts)
        rt._emit(
            "planning.projects.finish",
            code=code,
            projects=[context.name for context in session.selected_contexts],
        )
        if code == 0:
            print("Planning PR mode complete; skipping service startup.")
        return code

    orchestrator._emit_snapshot(
        session,
        "startup_branch_enter",
        command=requested_command,
        mode=runtime_mode,
        orch_group=sorted(debug_orch_groups) or None,
    )
    return None


def _complete_dashboard_resume(
    orchestrator: object,
    session: StartupSession,
    *,
    decision: RunReuseDecision,
    candidate_state: object,
    reuse_started: float,
    mark_run_reused_fn: Callable[..., dict[str, object]],
    build_planning_dashboard_state_fn: Callable[..., object],
    resolve_state_repository_fn: Callable[[object], object],
    build_runtime_map_fn: Callable[[object], dict[str, object]],
) -> int | None:
    rt = orchestrator.runtime
    route = session.effective_route
    runtime_mode = session.runtime_mode
    session.run_id = candidate_state.run_id
    orchestrator._announce_session_identifiers(session)
    candidate_state.metadata = build_planning_dashboard_state_fn(
        rt,
        route=route,
        runtime_mode=session.runtime_mode,
        run_id=candidate_state.run_id,
        project_contexts=session.selected_contexts,
        configured_service_types=orchestrator._configured_service_types_for_mode(session.runtime_mode),
        base_metadata=mark_run_reused_fn(candidate_state.metadata, reason="resume_dashboard_exact"),
    ).metadata
    resolve_state_repository_fn(rt).save_resume_state(
        state=candidate_state,
        emit=rt._emit,
        runtime_map_builder=cast(Callable[[object], dict[str, object]], build_runtime_map_fn),
    )
    orchestrator._emit_phase(
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
    if orchestrator._headless_plan_output_only(session):
        orchestrator._print_headless_plan_session_summary(session)
        return 0
    enter_interactive_dashboard = rt._should_enter_post_start_interactive(route)
    if route.command == "plan":
        orchestrator._print_plan_dry_run_preview(session)
        print(
            "Planning mode complete; skipping service startup because "
            f"envctl runs are disabled for {session.runtime_mode}."
        )
        attach_code = orchestrator._maybe_attach_plan_agent_terminal(session)
        if attach_code is not None:
            return attach_code
    elif not enter_interactive_dashboard:
        print(
            f"envctl runs are disabled for {session.runtime_mode}; "
            "opening dashboard without starting services."
        )
    if enter_interactive_dashboard:
        return rt._run_interactive_dashboard_loop(candidate_state)
    return 0


def _replace_existing_project_services_for_fresh_start(
    orchestrator: object,
    session: StartupSession,
    *,
    candidate_state: object,
    reason: str,
) -> None:
    if reason != "startup_fingerprint_mismatch":
        return
    route = session.effective_route
    if route.flags.get("runtime_scope") == "dependencies":
        return
    selected_services = _fresh_start_replacement_services(
        orchestrator,
        session,
        candidate_state=candidate_state,
    )
    if not selected_services:
        return
    rt = orchestrator.runtime
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
    orchestrator._terminate_restart_orphan_listeners(
        state=candidate_state,
        selected_services=selected_services,
        aggressive=True,
    )


def _fresh_start_replacement_services(
    orchestrator: object,
    session: StartupSession,
    *,
    candidate_state: object,
) -> set[str]:
    route = session.effective_route
    target_projects = {str(context.name).strip().lower() for context in session.selected_contexts}
    target_projects.discard("")
    if not target_projects:
        return set()
    configured_types = set(orchestrator._configured_service_types_for_mode(session.runtime_mode))
    additional_services = tuple(getattr(orchestrator.runtime.config, "additional_services", ()) or ())
    selected_by_project = {
        str(context.name).strip().lower(): orchestrator._restart_service_types_for_project(
            route=route,
            project_name=str(context.name),
            default_service_types=configured_types,
            additional_services=additional_services,
        )
        for context in session.selected_contexts
        if str(context.name).strip()
    }
    selected: set[str] = set()
    for service_name, service in candidate_state.services.items():
        project = service_project_name(service) or orchestrator.runtime._project_name_from_service(service_name)
        project_key = str(project).strip().lower()
        if project_key not in target_projects:
            continue
        service_type = service_slug_from_record(service)
        if service_type and service_type in selected_by_project.get(project_key, set()):
            selected.add(service_name)
    return selected


def _prepare_dashboard_stopped_service_restore(
    orchestrator: object,
    session: StartupSession,
    *,
    candidate_state: object,
    reuse_started: float,
    decision_kind: str,
    mark_run_reused_fn: Callable[..., dict[str, object]],
) -> bool:
    active_service_names = set(candidate_state.services)
    stopped_entries = [
        entry
        for entry in _dashboard_stopped_service_entries(candidate_state)
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
    session.base_metadata = _metadata_without_dashboard_stopped_services(
        mark_run_reused_fn(candidate_state.metadata, reason="restore_stopped_services"),
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
    orchestrator._emit_phase(
        session,
        "auto_resume_evaluate",
        reuse_started,
        status="restore_stopped_services",
        match_mode="exact" if decision_kind == "resume_exact" else "subset",
        stopped_service_count=len(stopped_service_names),
        target_projects=target_project_names,
    )
    orchestrator.runtime._emit(
        "state.auto_resume.restore_stopped_services",
        run_id=candidate_state.run_id,
        mode=session.runtime_mode,
        command=route.command,
        projects=target_project_names,
        services=stopped_service_names,
    )
    orchestrator.runtime._emit(
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


def _dashboard_stopped_service_entries(state: object) -> list[dict[str, str]]:
    raw = getattr(state, "metadata", {}).get("dashboard_stopped_services")
    if not isinstance(raw, list):
        return []
    entries: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        project = str(item.get("project", "") or "").strip()
        service_type = str(item.get("type", "") or "").strip().lower()
        name = str(item.get("name", "") or "").strip()
        if not project or service_type not in {"backend", "frontend"}:
            continue
        entries.append(
            {
                "project": project,
                "type": service_type,
                "name": name or f"{project} {service_type.title()}",
            }
        )
    return entries


def _metadata_without_dashboard_stopped_services(
    metadata: Mapping[str, object],
    *,
    restored_service_names: set[str],
) -> dict[str, object]:
    updated = dict(metadata)
    raw = updated.get("dashboard_stopped_services")
    if not isinstance(raw, list):
        return updated
    remaining: list[object] = []
    for item in raw:
        if not isinstance(item, Mapping):
            remaining.append(item)
            continue
        name = str(item.get("name", "") or "").strip()
        if name in restored_service_names:
            continue
        remaining.append(dict(item))
    if remaining:
        updated["dashboard_stopped_services"] = remaining
    else:
        updated.pop("dashboard_stopped_services", None)
    return updated
