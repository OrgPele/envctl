from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import time
from typing import Any, cast

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.engine_runtime_startup_support import evaluate_run_reuse, mark_run_reused
from envctl_engine.startup.finalization import (
    headless_plan_output_only,
    maybe_attach_plan_agent_terminal,
    print_headless_plan_session_summary,
    print_plan_dry_run_preview,
)
from envctl_engine.startup.plan_agent_handoff import validate_plan_agent_handoff_with_attach_target
from envctl_engine.startup.run_reuse_dashboard_restore import prepare_dashboard_stopped_service_restore_with_runtime
from envctl_engine.startup.run_reuse_decision import (
    RunReuseDecision,
    run_reuse_debug_orch_groups,
)
from envctl_engine.startup.run_reuse_fresh_start import replace_existing_project_services_for_fresh_start_with_defaults
from envctl_engine.startup.run_reuse_resume import StartupRunReuseResumeHandler
from envctl_engine.startup.session import StartupSession, metadata_with_state_sources
from envctl_engine.startup.session_lifecycle import announce_session_identifiers, emit_startup_phase
from envctl_engine.startup.service_bootstrap_domain import configured_service_types_for_mode
from envctl_engine.startup.startup_progress import report_progress
from envctl_engine.ui.debug_snapshot import emit_startup_plan_handoff_snapshot


@dataclass(frozen=True, slots=True)
class StartupRunReuseResolver:
    runtime: Any
    session: StartupSession
    evaluate_run_reuse_fn: Callable[..., RunReuseDecision]
    prepare_dashboard_stopped_service_restore: Callable[..., bool]
    announce_session_identifiers: Callable[[StartupSession], None]
    emit_phase: Callable[..., None]
    headless_plan_output_only: Callable[[StartupSession], bool]
    maybe_attach_plan_agent_terminal: Callable[[StartupSession], int | None]
    print_headless_plan_session_summary: Callable[[StartupSession], None]
    print_plan_dry_run_preview: Callable[[StartupSession], None]
    configured_service_types_for_mode: Callable[[str], list[str]]
    emit_snapshot: Callable[..., None]
    replace_existing_project_services_for_fresh_start: Callable[..., None]
    print_fn: Callable[[str], None] = print
    monotonic_fn: Callable[[], float] = time.monotonic

    @property
    def route(self) -> Route:
        return self.session.effective_route

    @property
    def runtime_mode(self) -> str:
        return self.session.runtime_mode

    @property
    def requested_command(self) -> str:
        return self.session.requested_command

    def resolve(self) -> int | None:
        debug_orch_groups = run_reuse_debug_orch_groups(
            self.runtime,
            requested_command=self.requested_command,
        )
        if self.requested_command != "restart":
            result = self._resolve_auto_reuse()
            if result is not None:
                return result
        planning_pr_result = self._run_planning_prs_if_requested()
        if planning_pr_result is not None:
            return planning_pr_result
        self._emit_startup_branch_snapshot(debug_orch_groups)
        return None

    def _resolve_auto_reuse(self) -> int | None:
        reuse_started = self.monotonic_fn()
        decision = self.evaluate_run_reuse_fn(
            self.runtime,
            runtime_mode=self.runtime_mode,
            route=self.route,
            contexts=cast(list[object], self.session.selected_contexts),
        )
        self._emit_reuse_evaluation(decision)
        candidate_state = decision.candidate_state
        if candidate_state is None:
            self._handle_no_reuse(decision=decision, reuse_started=reuse_started)
            return None
        if self._prepare_dashboard_stopped_restore(decision=decision, reuse_started=reuse_started):
            return None
        if decision.decision_kind in {"resume_exact", "resume_subset"}:
            return self._resume_matching_run(
                decision=decision,
                candidate_state=candidate_state,
                reuse_started=reuse_started,
            )
        if decision.decision_kind == "reuse_expand":
            self._apply_reuse_expand(decision=decision, candidate_state=candidate_state, reuse_started=reuse_started)
            return None
        if decision.decision_kind == "resume_dashboard_exact":
            return self._resume_dashboard_run(
                decision=decision,
                candidate_state=candidate_state,
                reuse_started=reuse_started,
            )
        self._handle_no_reuse(decision=decision, reuse_started=reuse_started)
        return None

    def _emit_reuse_evaluation(self, decision: RunReuseDecision) -> None:
        candidate_state = decision.candidate_state
        self._best_effort_diagnostic(
            lambda: self.runtime._emit(
                "state.run_reuse.evaluate",
                run_id=candidate_state.run_id if candidate_state is not None else None,
                mode=self.runtime_mode,
                command=self.route.command,
                decision_kind=decision.decision_kind,
                reason=decision.reason,
                selected_projects=decision.selected_projects,
                state_projects=decision.state_projects,
                weak_identity=decision.weak_identity,
                mismatch_details=decision.mismatch_details,
            )
        )

    def _prepare_dashboard_stopped_restore(self, *, decision: RunReuseDecision, reuse_started: float) -> bool:
        return (
            decision.decision_kind in {"resume_exact", "resume_subset"}
            and decision.candidate_state is not None
            and self.prepare_dashboard_stopped_service_restore(
                self.session,
                candidate_state=decision.candidate_state,
                reuse_started=reuse_started,
                decision_kind=decision.decision_kind,
            )
        )

    def _apply_reuse_expand(self, *, decision: RunReuseDecision, candidate_state: Any, reuse_started: float) -> None:
        self.session.run_id = None
        self.session.preserved_services = dict(candidate_state.services)
        self.session.preserved_requirements = dict(candidate_state.requirements)
        self.session.base_metadata = metadata_with_state_sources(
            mark_run_reused(candidate_state.metadata, reason="reuse_expand"),
            candidate_state,
        )
        state_project_names = {
            str(project.get("name", "")).strip().casefold()
            for project in decision.state_projects
            if str(project.get("name", "")).strip()
        }
        if state_project_names:
            self.session.contexts_to_start = [
                context
                for context in self.session.selected_contexts
                if str(getattr(context, "name", "")).strip().casefold() not in state_project_names
            ]
        self._best_effort_diagnostic(
            lambda: self.emit_phase(
                self.session,
                "auto_resume_evaluate",
                reuse_started,
                status="expand",
                match_mode="expand",
                state_project_count=len(decision.state_projects),
                selected_project_count=len(self.session.selected_contexts),
            )
        )
        self._best_effort_diagnostic(
            lambda: self.runtime._emit(
                "state.run_reuse.applied",
                run_id=candidate_state.run_id,
                mode=self.runtime_mode,
                command=self.route.command,
                decision_kind=decision.decision_kind,
                reason=decision.reason,
                preserved_services=sorted(self.session.preserved_services),
            )
        )

    def _handle_no_reuse(self, *, decision: RunReuseDecision, reuse_started: float) -> None:
        candidate_state = decision.candidate_state
        self._best_effort_diagnostic(
            lambda: self.emit_phase(
                self.session,
                "auto_resume_evaluate",
                reuse_started,
                status="skipped" if candidate_state is not None else "none",
                reason=decision.reason if candidate_state is not None else None,
                state_project_count=len(decision.state_projects),
                selected_project_count=len(self.session.selected_contexts),
            )
        )
        if candidate_state is None:
            return
        self._best_effort_diagnostic(
            lambda: self.runtime._emit(
                "state.auto_resume.skipped",
                reason=decision.reason,
                state_projects=[project["name"] for project in decision.state_projects],
                selected_projects=[project["name"] for project in decision.selected_projects],
                mode=self.runtime_mode,
                command=self.route.command,
            )
        )
        self._best_effort_diagnostic(
            lambda: self.runtime._emit(
                "state.run_reuse.skipped",
                run_id=candidate_state.run_id,
                reason=decision.reason,
                mode=self.runtime_mode,
                command=self.route.command,
                mismatch_details=decision.mismatch_details,
            )
        )
        self.replace_existing_project_services_for_fresh_start(
            self.session,
            candidate_state=candidate_state,
            reason=decision.reason,
        )

    def _run_planning_prs_if_requested(self) -> int | None:
        if self.route.command != "plan" or not bool(self.route.flags.get("planning_prs")):
            return None
        self.runtime._emit(
            "planning.projects.start",
            projects=[context.name for context in self.session.selected_contexts],
        )
        code = self.runtime._run_pr_action(self.route, self.session.selected_contexts)
        self.runtime._emit(
            "planning.projects.finish",
            code=code,
            projects=[context.name for context in self.session.selected_contexts],
        )
        if code == 0:
            self.print_fn("Planning PR mode complete; skipping service startup.")
        return code

    def _emit_startup_branch_snapshot(self, debug_orch_groups: set[str]) -> None:
        self._best_effort_diagnostic(
            lambda: self.emit_snapshot(
                self.session,
                "startup_branch_enter",
                command=self.requested_command,
                mode=self.runtime_mode,
                orch_group=sorted(debug_orch_groups) or None,
            )
        )

    @staticmethod
    def _best_effort_diagnostic(callback: Callable[[], object]) -> None:
        try:
            callback()
        except Exception:  # noqa: BLE001
            pass

    def _resume_matching_run(
        self,
        *,
        decision: RunReuseDecision,
        candidate_state: Any,
        reuse_started: float,
    ) -> int | None:
        return self._resume_handler(
            decision=decision,
            candidate_state=candidate_state,
            reuse_started=reuse_started,
        ).resume_matching_run()

    def _resume_dashboard_run(
        self,
        *,
        decision: RunReuseDecision,
        candidate_state: Any,
        reuse_started: float,
    ) -> int | None:
        return self._resume_handler(
            decision=decision,
            candidate_state=candidate_state,
            reuse_started=reuse_started,
        ).resume_dashboard_run()

    def _resume_handler(
        self,
        *,
        decision: RunReuseDecision,
        candidate_state: Any,
        reuse_started: float,
    ) -> StartupRunReuseResumeHandler:
        return StartupRunReuseResumeHandler(
            runtime=self.runtime,
            session=self.session,
            route=self.route,
            runtime_mode=self.runtime_mode,
            decision=decision,
            candidate_state=candidate_state,
            reuse_started=reuse_started,
            announce_session_identifiers=self.announce_session_identifiers,
            emit_phase=self.emit_phase,
            headless_plan_output_only=self.headless_plan_output_only,
            maybe_attach_plan_agent_terminal=self.maybe_attach_plan_agent_terminal,
            print_headless_plan_session_summary=self.print_headless_plan_session_summary,
            print_plan_dry_run_preview=self.print_plan_dry_run_preview,
            configured_service_types_for_mode=self.configured_service_types_for_mode,
            replace_existing_project_services_for_fresh_start=self.replace_existing_project_services_for_fresh_start,
            print_fn=self.print_fn,
        )


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
    configured_service_types_for_mode: Callable[[str], list[str]],
    emit_snapshot: Callable[..., None],
    replace_existing_project_services_for_fresh_start: Callable[..., None],
    print_fn: Callable[[str], None] = print,
) -> int | None:
    return StartupRunReuseResolver(
        runtime=runtime,
        session=session,
        evaluate_run_reuse_fn=evaluate_run_reuse_fn,
        prepare_dashboard_stopped_service_restore=prepare_dashboard_stopped_service_restore,
        announce_session_identifiers=announce_session_identifiers,
        emit_phase=emit_phase,
        headless_plan_output_only=headless_plan_output_only,
        maybe_attach_plan_agent_terminal=maybe_attach_plan_agent_terminal,
        print_headless_plan_session_summary=print_headless_plan_session_summary,
        print_plan_dry_run_preview=print_plan_dry_run_preview,
        configured_service_types_for_mode=configured_service_types_for_mode,
        emit_snapshot=emit_snapshot,
        replace_existing_project_services_for_fresh_start=replace_existing_project_services_for_fresh_start,
        print_fn=print_fn,
    ).resolve()


def resolve_startup_run_reuse_with_runtime(
    runtime: Any,
    session: StartupSession,
    *,
    terminate_restart_orphan_listeners: Callable[..., set[int]],
    validate_attach_target_fn: Callable[..., Any],
    attach_plan_agent_terminal: Callable[..., Any],
    progress_lock: Any,
    last_progress_message_by_project: dict[str | None, str],
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
            print_headless_plan_session_summary=lambda session, *, attach_target: print_headless_plan_session_summary(
                session,
                validate_plan_agent_handoff=validate_plan_agent_handoff,
                print_fn=print_fn,
                attach_target=attach_target,
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
        configured_service_types_for_mode=lambda runtime_mode: list(
            configured_service_types_for_mode(runtime.config, runtime_mode)
        ),
        emit_snapshot=lambda *args, **kwargs: emit_startup_plan_handoff_snapshot(runtime, *args, **kwargs),
        replace_existing_project_services_for_fresh_start=lambda session, *, candidate_state, reason: (
            replace_existing_project_services_for_fresh_start_with_defaults(
                runtime=runtime,
                session=session,
                candidate_state=candidate_state,
                reason=reason,
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
