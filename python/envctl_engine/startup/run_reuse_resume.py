from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.engine_runtime_startup_support import mark_run_reused
from envctl_engine.runtime.lifecycle_operation_lease import (
    lifecycle_operation_active,
    release_lifecycle_operation,
)
from envctl_engine.runtime.runtime_context import resolve_state_repository
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.startup.finalization import build_planning_dashboard_state
from envctl_engine.startup.run_reuse_decision import RunReuseDecision
from envctl_engine.startup.session import StartupSession


@dataclass(frozen=True, slots=True)
class StartupRunReuseResumeHandler:
    runtime: Any
    session: StartupSession
    route: Route
    runtime_mode: str
    decision: RunReuseDecision
    candidate_state: Any
    reuse_started: float
    announce_session_identifiers: Callable[[StartupSession], None]
    emit_phase: Callable[..., None]
    headless_plan_output_only: Callable[[StartupSession], bool]
    maybe_attach_plan_agent_terminal: Callable[[StartupSession], int | None]
    print_headless_plan_session_summary: Callable[[StartupSession], None]
    print_plan_dry_run_preview: Callable[[StartupSession], None]
    configured_service_types_for_mode: Callable[[str], list[str]]
    replace_existing_project_services_for_fresh_start: Callable[..., None]
    print_fn: Callable[[str], None] = print

    def resume_matching_run(self) -> int | None:
        previous_run_id = self.session.run_id
        previous_identifiers_announced = self.session.identifiers_announced
        self.session.run_id = self.candidate_state.run_id
        self.announce_session_identifiers(self.session)
        self._emit_resume_match_phase()
        self._emit_resume_match_events()

        lifecycle_lease_was_active = lifecycle_operation_active(self.runtime)
        resume_code = self.runtime._resume(self._resume_route())
        if int(resume_code) == 0:
            return self._resume_success_result()
        lifecycle_lease_was_released = lifecycle_lease_was_active and not lifecycle_operation_active(self.runtime)
        self._handle_resume_failure(
            resume_code=int(resume_code),
            previous_run_id=previous_run_id,
            previous_identifiers_announced=previous_identifiers_announced,
            allow_fresh_fallback=not lifecycle_lease_was_released,
        )
        return int(resume_code) if lifecycle_lease_was_released else None

    def resume_dashboard_run(self) -> int | None:
        self.session.run_id = self.candidate_state.run_id
        self.announce_session_identifiers(self.session)
        self._persist_dashboard_resume_metadata()
        self._emit_dashboard_resume_events()
        release_lifecycle_operation(self.runtime)

        if self.headless_plan_output_only(self.session):
            self.print_headless_plan_session_summary(self.session)
            return 0
        enter_interactive_dashboard = self.runtime._should_enter_post_start_interactive(self.route)
        if self.route.command == "plan":
            attach_code = self._render_plan_dashboard_resume()
            if attach_code is not None:
                return attach_code
        elif not enter_interactive_dashboard:
            self.print_fn(
                f"envctl runs are disabled for {self.session.runtime_mode}; "
                "opening dashboard without starting services."
            )
        if enter_interactive_dashboard:
            return self.runtime._run_interactive_dashboard_loop(self.candidate_state)
        return 0

    @property
    def _match_mode(self) -> str:
        return "exact" if self.decision.decision_kind == "resume_exact" else "subset"

    @property
    def _selected_project_names(self) -> list[object]:
        return [project["name"] for project in self.decision.selected_projects]

    @property
    def _state_project_names(self) -> list[object]:
        return [project["name"] for project in self.decision.state_projects]

    def _emit_resume_match_phase(self) -> None:
        self.emit_phase(
            self.session,
            "auto_resume_evaluate",
            self.reuse_started,
            status="resume",
            match_mode=self._match_mode,
            state_project_count=len(self.decision.state_projects),
            selected_project_count=len(self.session.selected_contexts),
        )

    def _emit_resume_match_events(self) -> None:
        self.runtime._emit(
            "state.auto_resume",
            run_id=self.candidate_state.run_id,
            mode=self.runtime_mode,
            command=self.route.command,
            match_mode=self._match_mode,
            selected_projects=self._selected_project_names,
        )
        self.runtime._emit(
            "state.run_reuse.applied",
            run_id=self.candidate_state.run_id,
            mode=self.runtime_mode,
            command=self.route.command,
            decision_kind=self.decision.decision_kind,
            reason=self.decision.reason,
        )

    def _resume_route(self) -> Route:
        resume_flags = {
            **self.route.flags,
            "_resume_source_command": self.route.command,
            "_run_reuse_reason": self.decision.decision_kind,
            "_state_project_names": [str(name) for name in self._selected_project_names],
        }
        if self._attach_plan_agent_after_resume():
            resume_flags["batch"] = True
        return Route(
            command="resume",
            mode=self.runtime_mode,
            raw_args=self.route.raw_args,
            passthrough_args=self.route.passthrough_args,
            projects=self.route.projects,
            flags=resume_flags,
        )

    def _attach_plan_agent_after_resume(self) -> bool:
        return (
            self.route.command == "plan"
            and not self.headless_plan_output_only(self.session)
            and self.session.plan_agent_attach_target is not None
        )

    def _resume_success_result(self) -> int | None:
        if not self._attach_plan_agent_after_resume():
            return 0
        attach_code = self.maybe_attach_plan_agent_terminal(self.session)
        return attach_code if attach_code is not None else 0

    def _handle_resume_failure(
        self,
        *,
        resume_code: int,
        previous_run_id: str | None,
        previous_identifiers_announced: bool,
        allow_fresh_fallback: bool = True,
    ) -> None:
        self.session.run_id = previous_run_id
        self.session.identifiers_announced = previous_identifiers_announced
        self.runtime._emit(
            "state.auto_resume.skipped",
            reason="resume_failed",
            resume_code=resume_code,
            state_projects=self._state_project_names,
            selected_projects=self._selected_project_names,
            mode=self.runtime_mode,
            command=self.route.command,
        )
        self.runtime._emit(
            "state.run_reuse.skipped",
            run_id=self.candidate_state.run_id,
            reason="resume_failed",
            resume_code=resume_code,
            mode=self.runtime_mode,
            command=self.route.command,
        )
        if allow_fresh_fallback:
            self.replace_existing_project_services_for_fresh_start(
                self.session,
                candidate_state=self.candidate_state,
                reason=self.decision.reason,
            )

    def _persist_dashboard_resume_metadata(self) -> None:
        self.candidate_state.metadata = build_planning_dashboard_state(
            self.runtime,
            route=self.route,
            runtime_mode=self.session.runtime_mode,
            run_id=self.candidate_state.run_id,
            project_contexts=self.session.selected_contexts,
            configured_service_types=self.configured_service_types_for_mode(self.session.runtime_mode),
            base_metadata=mark_run_reused(self.candidate_state.metadata, reason="resume_dashboard_exact"),
        ).metadata
        resolve_state_repository(self.runtime).save_resume_state(
            state=self.candidate_state,
            emit=self.runtime._emit,
            runtime_map_builder=cast(Callable[[object], dict[str, object]], build_runtime_map),
        )

    def _emit_dashboard_resume_events(self) -> None:
        self.emit_phase(
            self.session,
            "auto_resume_evaluate",
            self.reuse_started,
            status="dashboard_resume",
            match_mode="exact",
            state_project_count=len(self.decision.state_projects),
            selected_project_count=len(self.session.selected_contexts),
        )
        self.runtime._emit(
            "state.run_reuse.applied",
            run_id=self.candidate_state.run_id,
            mode=self.runtime_mode,
            command=self.route.command,
            decision_kind=self.decision.decision_kind,
            reason=self.decision.reason,
        )
        self.runtime._emit(
            "state.dashboard_resume",
            run_id=self.candidate_state.run_id,
            mode=self.runtime_mode,
            command=self.route.command,
        )

    def _render_plan_dashboard_resume(self) -> int | None:
        self.print_plan_dry_run_preview(self.session)
        self.print_fn(
            "Planning mode complete; skipping service startup because "
            f"envctl runs are disabled for {self.session.runtime_mode}."
        )
        attach_code = self.maybe_attach_plan_agent_terminal(self.session)
        return attach_code if attach_code is not None else None
