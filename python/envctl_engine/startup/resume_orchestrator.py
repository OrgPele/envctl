from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.ui.spinner import spinner, spinner_enabled, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy

from envctl_engine.shared.parsing import parse_bool
from envctl_engine.startup.resume_progress import ResumeProjectSpinnerGroup
from envctl_engine.startup.resume_restore_support import (
    _state_repository as _state_repository_impl,
    apply_ports_to_context as apply_ports_to_context_impl,
    context_for_project as context_for_project_impl,
    project_root as project_root_impl,
    restore_missing as restore_missing_impl,
)


_ResumeProjectSpinnerGroup = ResumeProjectSpinnerGroup


class ResumeOrchestrator:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def execute(self, route: Route) -> int:
        rt = self.runtime
        state_repository = _state_repository_impl(rt)
        hook_contract_issue = rt._startup_hook_contract_issue()  # type: ignore[attr-defined]
        if hook_contract_issue:
            print(hook_contract_issue)
            return 1

        def emit_phase(phase: str, started_at: float, **extra: object) -> None:
            rt._emit(
                "resume.phase",
                mode=route.mode,
                phase=phase,
                duration_ms=round((time.monotonic() - started_at) * 1000.0, 2),
                **extra,
            )

        state_load_started = time.monotonic()
        state = rt._try_load_existing_state(  # type: ignore[attr-defined]
            mode=route.mode,
            strict_mode_match=rt._state_lookup_strict_mode_match(route),  # type: ignore[attr-defined]
        )
        emit_phase("state_load", state_load_started, found=state is not None)
        if state is None:
            print("No previous state found to resume.")
            return 1

        bind_debug_run_id = getattr(rt, "_bind_debug_run_id", None)
        if callable(bind_debug_run_id):
            bind_debug_run_id(state.run_id)

        legacy_resume = bool(state.metadata.get("legacy_state"))
        strict_resume = rt.config.runtime_truth_mode == "strict"  # type: ignore[attr-defined]
        if not rt._enforce_runtime_readiness_contract(scope="resume", strict_required=strict_resume):  # type: ignore[attr-defined]
            print("Resume blocked: strict runtime readiness gate is incomplete.")
            return 1

        try:
            rt._validate_mode_toggles(state.mode, route=route)  # type: ignore[attr-defined]
        except RuntimeError as exc:
            print(str(exc))
            return 1

        rt._emit("state.resume", run_id=state.run_id)  # type: ignore[attr-defined]
        original_truth_mode = rt.config.runtime_truth_mode  # type: ignore[attr-defined]
        reconcile_started = time.monotonic()
        if legacy_resume:
            rt._sanitize_legacy_resume_state(state)  # type: ignore[attr-defined]
            rt.config.runtime_truth_mode = "strict"  # type: ignore[attr-defined]
        try:
            missing_services = rt._reconcile_state_truth(state)  # type: ignore[attr-defined]
        finally:
            rt.config.runtime_truth_mode = original_truth_mode  # type: ignore[attr-defined]
        emit_phase(
            "pre_restore_reconcile",
            reconcile_started,
            missing_count=len(missing_services),
            legacy_state=legacy_resume,
        )
        restore_errors: list[str] = []
        restore_enabled = self.restore_enabled(route)
        if legacy_resume and restore_enabled:
            rt._emit(  # type: ignore[attr-defined]
                "resume.restore.skip",
                run_id=state.run_id,
                reason="legacy_state",
                missing_count=len(missing_services),
                missing_services=missing_services,
            )
            restore_enabled = False
        if missing_services and restore_enabled:
            rt._emit(  # type: ignore[attr-defined]
                "resume.restore.start",
                run_id=state.run_id,
                missing_count=len(missing_services),
                missing_services=missing_services,
            )
            restore_started = time.monotonic()
            restore_errors = self.restore_missing(state, missing_services, route=route)
            emit_phase(
                "restore_missing",
                restore_started,
                status="error" if restore_errors else "ok",
                project_count=len(
                    {
                        rt._project_name_from_service(name)
                        for name in missing_services
                        if rt._project_name_from_service(name)
                    }
                ),  # type: ignore[attr-defined]
                error_count=len(restore_errors),
            )
            if legacy_resume:
                rt.config.runtime_truth_mode = "strict"  # type: ignore[attr-defined]
            try:
                missing_services = rt._reconcile_state_truth(state)  # type: ignore[attr-defined]
            finally:
                rt.config.runtime_truth_mode = original_truth_mode  # type: ignore[attr-defined]
            rt._emit(  # type: ignore[attr-defined]
                "resume.restore.finish",
                run_id=state.run_id,
                restored_ok=not restore_errors,
                errors=restore_errors,
            )
        rt._emit(  # type: ignore[attr-defined]
            "state.reconcile",
            run_id=state.run_id,
            source="resume",
            missing_count=len(missing_services),
            missing_services=missing_services,
        )
        save_started = time.monotonic()
        runtime_map = state_repository.save_resume_state(  # type: ignore[attr-defined]
            state=state,
            emit=rt._emit,
            runtime_map_builder=build_runtime_map,
        )
        emit_phase(
            "save_resume_state",
            save_started,
            project_count=len(runtime_map.get("projection", {})) if isinstance(runtime_map, dict) else 0,
        )
        enter_interactive = bool(rt._should_enter_resume_interactive(route))  # type: ignore[attr-defined]

        if not enter_interactive:
            current_session_id = getattr(rt, "_current_session_id", None)
            session_id = current_session_id() if callable(current_session_id) else None
            session_id_text = str(session_id).strip() if isinstance(session_id, str) else ""
            if not session_id_text:
                session_id_text = "unknown"
            print(f"Resumed run_id={state.run_id} session_id={session_id_text}")
            projection = runtime_map.get("projection", {})
            projection_map = projection if isinstance(projection, dict) else {}
            for project, urls in projection_map.items():
                backend_url = urls.get("backend_url")
                frontend_url = urls.get("frontend_url")
                print(f"{project}: backend={backend_url} frontend={frontend_url}")
        if missing_services:
            print("Warning: stale services detected during resume: " + ", ".join(missing_services))
        if restore_errors:
            print("Warning: resume restore encountered errors: " + "; ".join(restore_errors))
        if not rt._state_has_resumable_services(state):  # type: ignore[attr-defined]
            rt._emit(  # type: ignore[attr-defined]
                "resume.empty_state",
                run_id=state.run_id,
                reason="no_resumable_services",
            )
            print("No active services to resume.")
            return 1
        if enter_interactive:
            return rt._run_interactive_dashboard_loop(state)  # type: ignore[attr-defined]
        return 0

    def restore_enabled(self, route: Route) -> bool:
        rt = self.runtime
        if bool(route.flags.get("skip_startup")):
            return False
        raw = rt.env.get("ENVCTL_RESUME_RESTART_MISSING") or rt.config.raw.get("ENVCTL_RESUME_RESTART_MISSING")  # type: ignore[attr-defined]
        default_enabled = True
        return parse_bool(raw, default_enabled)

    def restore_missing(
        self,
        state: RunState,
        missing_services: list[str],
        *,
        route: Route | None = None,
    ) -> list[str]:
        return restore_missing_impl(
            self,
            state,
            missing_services,
            route=route,
            spinner_factory=spinner,
            spinner_enabled_fn=spinner_enabled,
            use_spinner_policy_fn=use_spinner_policy,
            emit_spinner_policy_fn=emit_spinner_policy,
            resolve_spinner_policy_fn=resolve_spinner_policy,
            project_spinner_group_cls=_ResumeProjectSpinnerGroup,
        )

    def context_for_project(self, state: RunState, project: str) -> object | None:
        return context_for_project_impl(self, state, project)

    def project_root(self, state: RunState, project: str) -> Path | None:
        return project_root_impl(self, state, project)

    def apply_ports_to_context(self, context: object, state: RunState) -> None:
        return apply_ports_to_context_impl(self, context, state)
