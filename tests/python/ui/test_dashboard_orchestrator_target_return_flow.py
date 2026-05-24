from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator

from tests.python.ui.dashboard_orchestrator_test_support import (
    _DashboardOrchestratorTestCase,
    _RuntimeStub,
)


class DashboardOrchestratorTargetReturnFlowTests(_DashboardOrchestratorTestCase):
    def test_interactive_test_failure_does_not_replay_duplicate_summary_after_test_suite_block(self) -> None:
        runtime = _RuntimeStub()
        runtime.dispatch_code = 1
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
        )
        runtime._latest_state = state

        def failing_dispatch(route: Route) -> int:
            runtime.last_dispatched_route = route
            runtime._latest_state = RunState(
                run_id="run-1",
                mode="main",
                services=state.services,
                metadata={
                    "project_test_summaries": {
                        "Main": {
                            "summary_path": "/tmp/runtime/test-results/run_1/Main/failed_tests_summary.txt",
                            "short_summary_path": "/tmp/runtime/run_1/ft_deadbeef00.txt",
                            "summary_excerpt": [
                                "[Repository tests (unittest)]",
                                "tests/python/ui/test_selector.py::test_keyboard_burst",
                                "AssertionError: Regex didn't match: 'RESULT_CANCELLED=False'",
                            ],
                            "status": "failed",
                        }
                    }
                },
            )
            return 1

        runtime.dispatch = failing_dispatch  # type: ignore[assignment]

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertNotIn("Command failed (exit 1).", out.getvalue())
        rendered = strip_ansi(out.getvalue())
        self.assertNotIn("Test failure summary for Main:", rendered)
        self.assertNotIn("/tmp/runtime/run_1/ft_deadbeef00.txt", rendered)
        self.assertEqual(
            runtime.read_prompts,
            ["Press Enter to return to dashboard (manual confirmation required): "],
        )

    def test_interactive_test_success_pauses_before_returning_to_dashboard(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
        )
        runtime._latest_state = state

        should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertEqual(
            runtime.read_prompts,
            ["Press Enter to return to dashboard (manual confirmation required): "],
        )

    def test_interactive_test_interrupt_returns_to_dashboard_without_failure_summary_block(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
        )
        runtime._latest_state = state

        def interrupted_dispatch(route: Route) -> int:
            runtime.last_dispatched_route = route
            raise KeyboardInterrupt

        runtime.dispatch = interrupted_dispatch  # type: ignore[assignment]

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        rendered = out.getvalue()
        self.assertNotIn("Command failed (exit 1).", rendered)
        self.assertNotIn("Test failure summary for Main:", rendered)
        self.assertEqual(
            runtime.read_prompts,
            ["Press Enter to return to dashboard (manual confirmation required): "],
        )
