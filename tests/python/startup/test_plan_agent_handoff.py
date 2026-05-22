from __future__ import annotations

from types import SimpleNamespace
import unittest

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.startup.plan_agent_handoff import (
    emit_plan_agent_launch_state,
    local_startup_failure_reason,
    plan_agent_launch_failure_message,
    record_plan_agent_handoff_local_startup_failure,
    should_fail_for_plan_agent_launch_result,
)
from envctl_engine.startup.session import StartupSession


def _session(*, args: list[str] | None = None) -> StartupSession:
    route = parse_route(args or ["plan", "--tmux"], env={})
    return StartupSession(
        requested_route=route,
        effective_route=route,
        requested_command="plan",
        runtime_mode="trees",
        run_id="run-handoff",
    )


class PlanAgentHandoffTests(unittest.TestCase):
    def test_local_startup_failure_reason_classifies_missing_start_command(self) -> None:
        self.assertEqual(
            local_startup_failure_reason("missing_service_start_command: backend"),
            "missing_service_start_command",
        )
        self.assertIsNone(local_startup_failure_reason("database unavailable"))

    def test_record_local_startup_failure_marks_session_and_emits_handoff_events(self) -> None:
        session = _session(args=["plan", "--omx", "--ultragoal"])
        session.plan_agent_attach_target = SimpleNamespace(session_name="envctl-plan")
        session.plan_agent_launch_result = SimpleNamespace(status="launched")
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))

        record_plan_agent_handoff_local_startup_failure(
            runtime,
            session,
            project_name="feature-a-1",
            error="missing_service_start_command: backend",
        )

        self.assertTrue(session.plan_agent_handoff_degraded)
        self.assertEqual(len(session.local_startup_failures), 1)
        self.assertEqual(session.local_startup_failures[0].reason, "missing_service_start_command")
        self.assertEqual(
            session.warnings,
            [
                "Implementation session is running, but local app startup failed for "
                "feature-a-1: missing_service_start_command: backend"
            ],
        )
        self.assertEqual(
            events,
            [
                (
                    "startup.project.warning",
                    {
                        "project": "feature-a-1",
                        "warning": session.warnings[0],
                        "reason": "plan_agent_handoff_local_startup_failed",
                        "implementation_session_running": True,
                        "local_startup_failed": True,
                        "session_name": "envctl-plan",
                    },
                ),
                (
                    "startup.plan_agent_handoff.degraded",
                    {
                        "project": "feature-a-1",
                        "error": "missing_service_start_command: backend",
                        "reason": "missing_service_start_command",
                        "implementation_session_running": True,
                        "session_name": "envctl-plan",
                        "route_transport": "omx",
                        "omx_workflow": "ultragoal",
                        "launch_status": "launched",
                    },
                ),
            ],
        )

    def test_record_local_startup_failure_defaults_unknown_reason_and_cmux_transport(self) -> None:
        session = _session(args=["plan"])
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))

        record_plan_agent_handoff_local_startup_failure(
            runtime,
            session,
            project_name="feature-a-1",
            error="frontend unavailable",
        )

        self.assertEqual(session.local_startup_failures[0].reason, "local_startup_failed")
        self.assertEqual(events[-1][1]["route_transport"], "cmux")
        self.assertIsNone(events[-1][1]["omx_workflow"])

    def test_emit_plan_agent_launch_state_summarizes_launch_outcomes(self) -> None:
        session = _session(args=["plan", "--tmux"])
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))
        launch_result = SimpleNamespace(
            status="partial",
            reason="one_failed",
            attach_target=SimpleNamespace(session_name="envctl-plan"),
            outcomes=(
                SimpleNamespace(status="launched", worktree_name="feature-a-1"),
                SimpleNamespace(status="failed", worktree_name="feature-a-2"),
                SimpleNamespace(status="skipped", worktree_name="feature-a-3"),
                SimpleNamespace(status="failed", worktree_name=""),
            ),
        )
        session.plan_agent_launch_result = launch_result

        emit_plan_agent_launch_state(runtime, session, launch_result)

        self.assertEqual(
            events,
            [
                (
                    "startup.plan_agent_launch_state",
                    {
                        "command": "plan",
                        "mode": "trees",
                        "status": "partial",
                        "reason": "one_failed",
                        "launched_worktrees": ["feature-a-1"],
                        "failed_worktrees": ["feature-a-2"],
                        "session_name": "envctl-plan",
                        "implementation_session_running": True,
                    },
                )
            ],
        )

    def test_should_fail_for_plan_agent_launch_result_requires_plan_request_and_no_attach(self) -> None:
        failed_result = SimpleNamespace(status="failed", attach_target=None, outcomes=())

        session = _session(args=["plan", "--tmux"])
        session.plan_agent_launch_requested = True
        self.assertTrue(should_fail_for_plan_agent_launch_result(session, failed_result))

        session.plan_agent_attach_target = SimpleNamespace(session_name="envctl-plan")
        self.assertFalse(should_fail_for_plan_agent_launch_result(session, failed_result))

        no_launch_session = _session(args=["plan", "--tmux"])
        self.assertFalse(should_fail_for_plan_agent_launch_result(no_launch_session, failed_result))

        start_session = _session(args=["--trees"])
        start_session.plan_agent_launch_requested = True
        self.assertFalse(should_fail_for_plan_agent_launch_result(start_session, failed_result))

    def test_plan_agent_launch_failure_message_prefers_outcome_details(self) -> None:
        launch_result = SimpleNamespace(
            status="failed",
            reason="transport_failed",
            outcomes=(
                SimpleNamespace(worktree_name="feature-a-1", reason="missing cmux"),
                SimpleNamespace(worktree_name="feature-a-2", reason=""),
                SimpleNamespace(worktree_name="", reason="timeout"),
                SimpleNamespace(worktree_name="feature-a-3", reason="bad env"),
                SimpleNamespace(worktree_name="feature-a-4", reason="hidden fourth"),
            ),
        )

        self.assertEqual(
            plan_agent_launch_failure_message(launch_result),
            "Plan agent session failed to start: feature-a-1: missing cmux; timeout; feature-a-3: bad env",
        )

    def test_plan_agent_launch_failure_message_falls_back_to_result_reason(self) -> None:
        launch_result = SimpleNamespace(status="failed", reason="missing_executables", outcomes=())

        self.assertEqual(
            plan_agent_launch_failure_message(launch_result),
            "Plan agent session failed to start: missing_executables",
        )


if __name__ == "__main__":
    unittest.main()
