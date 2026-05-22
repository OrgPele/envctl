from __future__ import annotations

from types import SimpleNamespace
import unittest

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.post_start_reconcile import reconcile_strict_truth_after_start
from envctl_engine.startup.session import StartupSession
from envctl_engine.state.models import RequirementsResult, ServiceRecord


class PostStartReconcileTests(unittest.TestCase):
    @staticmethod
    def _session() -> StartupSession:
        route = Route(command="start", mode="main", raw_args=[], passthrough_args=[], projects=[], flags={})
        session = StartupSession(
            requested_route=route,
            effective_route=route,
            requested_command="start",
            runtime_mode="main",
            run_id="run-1",
        )
        session.requirements_by_project["Main"] = RequirementsResult(project="Main")
        session.services_by_project["Main"] = {
            "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd="/repo/backend")
        }
        return session

    def test_reconcile_strict_truth_skips_non_strict_mode(self) -> None:
        session = self._session()
        runtime = SimpleNamespace(config=SimpleNamespace(runtime_truth_mode="auto"))
        calls: list[str] = []

        reconcile_strict_truth_after_start(
            runtime=runtime,
            session=session,
            build_run_state=lambda runtime, session: calls.append("build"),
            reconcile_state_truth=lambda state: calls.append("reconcile"),
            emit_phase=lambda session, phase, started_at, **extra: calls.append("phase"),
        )

        self.assertEqual(calls, [])

    def test_reconcile_strict_truth_records_degraded_plan_agent_handoff_skip(self) -> None:
        session = self._session()
        session.plan_agent_handoff_degraded = True
        events: list[tuple[str, dict[str, object]]] = []
        phases: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(
            config=SimpleNamespace(runtime_truth_mode="strict"),
            _emit=lambda event, **payload: events.append((event, dict(payload))),
        )

        reconcile_strict_truth_after_start(
            runtime=runtime,
            session=session,
            build_run_state=lambda runtime, session: self.fail("should not build run state"),
            reconcile_state_truth=lambda state: self.fail("should not reconcile state"),
            emit_phase=lambda session, phase, started_at, **extra: phases.append((phase, dict(extra))),
        )

        self.assertEqual(phases[0][0], "post_start_reconcile")
        self.assertEqual(phases[0][1], {"status": "skipped_degraded_handoff", "missing_count": 0})
        self.assertEqual(events[0][0], "state.reconcile")
        self.assertEqual(events[0][1]["reason"], "plan_agent_handoff_degraded")
        self.assertTrue(events[0][1]["skipped"])

    def test_reconcile_strict_truth_marks_failure_and_raises_for_missing_services(self) -> None:
        session = self._session()
        events: list[tuple[str, dict[str, object]]] = []
        phases: list[tuple[str, dict[str, object]]] = []
        run_state = SimpleNamespace(run_id="run-1")
        runtime = SimpleNamespace(
            config=SimpleNamespace(runtime_truth_mode="strict"),
            _emit=lambda event, **payload: events.append((event, dict(payload))),
        )

        with self.assertRaisesRegex(RuntimeError, "service truth degraded after startup: Main Backend"):
            reconcile_strict_truth_after_start(
                runtime=runtime,
                session=session,
                build_run_state=lambda runtime, session: run_state,
                reconcile_state_truth=lambda state: ["Main Backend", "Main Backend"],
                emit_phase=lambda session, phase, started_at, **extra: phases.append((phase, dict(extra))),
            )

        self.assertTrue(session.strict_truth_failed)
        self.assertEqual(phases[0][1], {"status": "degraded", "missing_count": 2})
        self.assertEqual(events[0][1]["missing_services"], ["Main Backend", "Main Backend"])


if __name__ == "__main__":
    unittest.main()
