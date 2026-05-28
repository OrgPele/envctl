from __future__ import annotations

from types import SimpleNamespace
import unittest
from pathlib import Path

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.disabled_startup_resolution import (
    resolve_disabled_startup_mode,
    resolve_disabled_startup_mode_with_runtime,
)
from envctl_engine.startup.session import StartupSession


def _session(route: Route) -> StartupSession:
    return StartupSession(
        requested_route=route,
        effective_route=route,
        requested_command=route.command,
        runtime_mode=route.mode,
        run_id="run-1",
        selected_contexts=[SimpleNamespace(name="Main")],
    )


class _Config:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.runtime_scope_id = "scope-test"

    def startup_enabled_for_mode(self, mode: str) -> bool:
        self.checked_mode = mode
        return self.enabled

    def service_enabled_for_mode(self, mode: str, service: str) -> bool:
        return service in {"backend", "frontend"}


class _RuntimeStub:
    def __init__(self, *, enabled: bool) -> None:
        self.config = _Config(enabled)
        self.writes: list[tuple[object, list[object], list[str]]] = []
        self.dashboard_entries: list[object] = []

    def _write_artifacts(self, state: object, contexts: list[object], *, errors: list[str]) -> None:
        self.writes.append((state, list(contexts), list(errors)))

    def _should_enter_post_start_interactive(self, route: Route) -> bool:
        return False

    def _run_interactive_dashboard_loop(self, state: object) -> int:
        self.dashboard_entries.append(state)
        return 0

    def _new_run_id(self) -> str:
        return "run-runtime-bound"

    def _emit(self, event: str, **payload: object) -> None:
        self.last_event = (event, payload)

    def _current_session_id(self) -> str:
        return "session-runtime-bound"

    def _run_dir_path(self, run_id: str) -> Path:
        return Path("/tmp") / run_id


class DisabledStartupResolutionTests(unittest.TestCase):
    def test_returns_none_when_mode_runs_are_enabled(self) -> None:
        route = Route(command="start", mode="main", raw_args=[], passthrough_args=[], projects=[], flags={})
        runtime = _RuntimeStub(enabled=True)

        result = resolve_disabled_startup_mode(
            runtime=runtime,
            session=_session(route),
            route_is_implicit_start=lambda route: True,
            ensure_run_id=lambda session: None,
            announce_session_identifiers=lambda session: None,
            resolved_run_id=lambda session: "run-1",
            build_planning_dashboard_state=lambda *args, **kwargs: SimpleNamespace(metadata={}),
            configured_service_types_for_mode=lambda mode: set(),
            emit_phase=lambda *args, **kwargs: None,
            validate_plan_agent_handoff=lambda session, *, phase: None,
            print_plan_dry_run_preview=lambda session: None,
            headless_plan_output_only=lambda session: False,
            print_headless_plan_session_summary=lambda session: None,
            maybe_attach_plan_agent_terminal=lambda session: None,
        )

        self.assertIsNone(result)
        self.assertEqual(runtime.writes, [])

    def test_plan_disabled_mode_writes_dashboard_state_and_prints_plan_message(self) -> None:
        route = Route(command="plan", mode="trees", raw_args=[], passthrough_args=[], projects=[], flags={})
        runtime = _RuntimeStub(enabled=False)
        session = _session(route)
        rendered: list[str] = []
        phases: list[tuple[str, dict[str, object]]] = []
        handoff_phases: list[str] = []
        previews: list[StartupSession] = []

        result = resolve_disabled_startup_mode(
            runtime=runtime,
            session=session,
            route_is_implicit_start=lambda route: False,
            ensure_run_id=lambda session: None,
            announce_session_identifiers=lambda session: None,
            resolved_run_id=lambda session: "run-1",
            build_planning_dashboard_state=lambda *args, **kwargs: SimpleNamespace(metadata={"dashboard_runs_disabled": True}),
            configured_service_types_for_mode=lambda mode: {"backend", "frontend"},
            emit_phase=lambda session, phase, started_at, **extra: phases.append((phase, dict(extra))),
            validate_plan_agent_handoff=lambda session, *, phase: handoff_phases.append(phase),
            print_plan_dry_run_preview=lambda session: previews.append(session),
            headless_plan_output_only=lambda session: False,
            print_headless_plan_session_summary=lambda session: None,
            maybe_attach_plan_agent_terminal=lambda session: None,
            print_fn=rendered.append,
        )

        self.assertEqual(result, 0)
        self.assertTrue(session.disabled_startup_mode)
        self.assertEqual(len(runtime.writes), 1)
        self.assertEqual(phases, [("artifacts_write", {"status": "ok"})])
        self.assertEqual(handoff_phases, ["disabled_startup_finalization"])
        self.assertEqual(previews, [session])
        self.assertEqual(
            rendered,
            [
                "Planning mode complete; skipping service startup because envctl runs are disabled for trees.",
                "envctl runs are disabled for trees; opening dashboard without starting services.",
            ],
        )

    def test_import_disabled_mode_writes_dashboard_state_without_starting_services(self) -> None:
        route = Route(command="import", mode="trees", raw_args=[], passthrough_args=[], projects=[], flags={})
        runtime = _RuntimeStub(enabled=False)
        session = _session(route)
        rendered: list[str] = []
        phases: list[tuple[str, dict[str, object]]] = []

        result = resolve_disabled_startup_mode(
            runtime=runtime,
            session=session,
            route_is_implicit_start=lambda route: False,
            ensure_run_id=lambda session: None,
            announce_session_identifiers=lambda session: None,
            resolved_run_id=lambda session: "run-1",
            build_planning_dashboard_state=lambda *args, **kwargs: SimpleNamespace(metadata={"dashboard_runs_disabled": True}),
            configured_service_types_for_mode=lambda mode: {"backend", "frontend"},
            emit_phase=lambda session, phase, started_at, **extra: phases.append((phase, dict(extra))),
            validate_plan_agent_handoff=lambda session, *, phase: None,
            print_plan_dry_run_preview=lambda session: None,
            headless_plan_output_only=lambda session: False,
            print_headless_plan_session_summary=lambda session: None,
            maybe_attach_plan_agent_terminal=lambda session: None,
            print_fn=rendered.append,
        )

        self.assertEqual(result, 0)
        self.assertTrue(session.disabled_startup_mode)
        self.assertEqual(len(runtime.writes), 1)
        self.assertEqual(phases, [("artifacts_write", {"status": "ok"})])
        self.assertEqual(rendered, ["envctl runs are disabled for trees; opening dashboard without starting services."])

    def test_runtime_bound_disabled_startup_helper_writes_dashboard_state(self) -> None:
        route = Route(command="plan", mode="trees", raw_args=[], passthrough_args=[], projects=[], flags={})
        runtime = _RuntimeStub(enabled=False)
        session = _session(route)
        rendered: list[str] = []

        result = resolve_disabled_startup_mode_with_runtime(
            runtime,
            session,
            validate_attach_target_fn=lambda *args, **kwargs: None,
            attach_plan_agent_terminal=lambda *args, **kwargs: None,
            print_fn=rendered.append,
        )

        self.assertEqual(result, 0)
        self.assertTrue(session.disabled_startup_mode)
        self.assertEqual(len(runtime.writes), 1)
        state = runtime.writes[0][0]
        self.assertEqual(state.run_id, "run-1")
        self.assertTrue(state.metadata["dashboard_runs_disabled"])
        self.assertEqual(rendered[-1], "envctl runs are disabled for trees; opening dashboard without starting services.")


if __name__ == "__main__":
    unittest.main()
