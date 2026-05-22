from __future__ import annotations

import unittest

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.session_lifecycle import (
    announce_session_identifiers,
    create_startup_session,
    validate_startup_route_contract,
)


class _RuntimeStub:
    def __init__(self) -> None:
        self.env: dict[str, str] = {}
        self.events: list[dict[str, object]] = [{"event": "existing"}]
        self.reset_warnings = False
        self.new_run_ids = 0
        self.hook_contract_issue = ""
        self.readiness = True
        self.validated: list[tuple[str, Route]] = []

    def _effective_start_mode(self, route: Route) -> str:
        return route.mode

    def _reset_project_startup_warnings(self) -> None:
        self.reset_warnings = True

    def _new_run_id(self) -> str:
        self.new_run_ids += 1
        return f"run-{self.new_run_ids}"

    def _current_session_id(self) -> str:
        return "session-1"

    def _startup_hook_contract_issue(self) -> str:
        return self.hook_contract_issue

    def _validate_mode_toggles(self, mode: str, *, route: Route) -> None:
        self.validated.append((mode, route))

    def _enforce_runtime_readiness_contract(self, *, scope: str) -> bool:
        self.readiness_scope = scope
        return self.readiness


class StartupSessionLifecycleTests(unittest.TestCase):
    def test_create_startup_session_records_route_mode_event_index_and_resets_warnings(self) -> None:
        route = Route(command="start", mode="main", raw_args=[], passthrough_args=[], projects=[], flags={})
        runtime = _RuntimeStub()

        session = create_startup_session(runtime, route)

        self.assertEqual(session.requested_route, route)
        self.assertEqual(session.effective_route, route)
        self.assertEqual(session.requested_command, "start")
        self.assertEqual(session.runtime_mode, "main")
        self.assertEqual(session.startup_event_index, 1)
        self.assertTrue(runtime.reset_warnings)

    def test_announce_session_identifiers_prints_once_when_not_headless_summary_only(self) -> None:
        route = Route(command="start", mode="main", raw_args=[], passthrough_args=[], projects=[], flags={})
        runtime = _RuntimeStub()
        session = create_startup_session(runtime, route)
        rendered: list[str] = []

        announce_session_identifiers(
            runtime,
            session,
            headless_plan_output_only=lambda session: False,
            print_fn=rendered.append,
        )
        announce_session_identifiers(
            runtime,
            session,
            headless_plan_output_only=lambda session: False,
            print_fn=rendered.append,
        )

        self.assertEqual(session.run_id, "run-1")
        self.assertTrue(session.identifiers_announced)
        self.assertEqual(rendered, ["run_id: run-1", "session_id: session-1"])
        self.assertEqual(runtime.new_run_ids, 1)

    def test_validate_startup_route_contract_blocks_failed_runtime_readiness_gate(self) -> None:
        route = Route(command="start", mode="main", raw_args=[], passthrough_args=[], projects=[], flags={})
        runtime = _RuntimeStub()
        runtime.readiness = False
        session = create_startup_session(runtime, route)
        phases: list[tuple[str, dict[str, object]]] = []
        rendered: list[str] = []

        result = validate_startup_route_contract(
            runtime,
            session,
            emit_phase=lambda session, phase, started_at, **extra: phases.append((phase, dict(extra))),
            print_fn=rendered.append,
        )

        self.assertEqual(result, 1)
        self.assertEqual(phases, [("runtime_readiness_gate", {"status": "blocked"})])
        self.assertEqual(rendered, ["Startup blocked: strict runtime readiness gate is incomplete."])


if __name__ == "__main__":
    unittest.main()
