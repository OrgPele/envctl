from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator
from envctl_engine.ui.target_selector import TargetSelection

from tests.python.ui.dashboard_orchestrator_test_support import (
    _DashboardOrchestratorTestCase,
    _RuntimeStub,
    _TtyStringIO,
)


class DashboardOrchestratorFailureDetailsTests(_DashboardOrchestratorTestCase):
    def test_test_failure_details_render_hyperlinked_summary_path(self) -> None:
        runtime = _RuntimeStub()
        runtime.env["ENVCTL_UI_HYPERLINK_MODE"] = "on"
        orchestrator = DashboardOrchestrator(runtime)
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_path = Path(tmpdir) / "failed_tests_summary.txt"
            summary_path.write_text("summary\n", encoding="utf-8")
            state = RunState(
                run_id="run-1",
                mode="main",
                metadata={
                    "project_test_summaries": {
                        "Main": {
                            "short_summary_path": str(summary_path),
                            "status": "failed",
                        }
                    }
                },
            )

            out = _TtyStringIO()
            with redirect_stdout(out):
                printed = orchestrator._print_test_failure_details(
                    Route(command="test", mode="main", raw_args=["test"], passthrough_args=[], projects=["Main"], flags={}),
                    state,
                )

        self.assertTrue(printed)
        self.assertIn("\x1b]8;;file://", out.getvalue())
        self.assertIn(str(summary_path), strip_ansi(out.getvalue()))

    def test_interactive_errors_pauses_before_returning_to_dashboard(self) -> None:
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

        should_continue, next_state = orchestrator._run_interactive_command("e", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertIsNotNone(runtime.last_dispatched_route)
        self.assertEqual(runtime.last_dispatched_route.command, "errors")
        self.assertEqual(
            runtime.read_prompts,
            ["Press Enter to return to dashboard (manual confirmation required): "],
        )

    def test_interactive_migrate_failure_prints_summary_and_failure_log_path(self) -> None:
        runtime = _RuntimeStub()
        runtime.dispatch_code = 1
        runtime.env["ENVCTL_UI_HYPERLINK_MODE"] = "on"
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
                    "project_action_reports": {
                        "Main": {
                            "migrate": {
                                "status": "failed",
                                "summary": (
                                    "alembic.util.exc.CommandError: migration failed\n"
                                    "hint: envctl migrate loads backend env from backend/.env by default.\n"
                                    "hint: BACKEND_ENV_FILE_OVERRIDE or MAIN_ENV_FILE_PATH can redirect the env file.\n"
                                ),
                                "report_path": "/tmp/runtime/Main_migrate.txt",
                            }
                        }
                    }
                },
            )
            return 1

        runtime.dispatch = failing_dispatch  # type: ignore[assignment]

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command("m", state, runtime)

        rendered = out.getvalue()
        visible = strip_ansi(rendered)
        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertIn("migrate failed for Main: alembic.util.exc.CommandError: migration failed", visible)
        self.assertEqual(
            visible.count("hint: envctl migrate loads backend env from backend/.env by default."),
            1,
        )
        self.assertIn(
            "hint: BACKEND_ENV_FILE_OVERRIDE or MAIN_ENV_FILE_PATH can redirect the env file.",
            visible,
        )
        self.assertIn(
            "migrate failure log for Main:\n/tmp/runtime/Main_migrate.txt",
            visible,
        )
        self.assertIn("\x1b]8;;file://", rendered)
        self.assertNotIn("Command failed (exit 1).", rendered)

    def test_interactive_migrate_success_prints_result_summary_for_all_targets(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["feature-a-1", "feature-b-1"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-migrate-success",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "feature-b-1 Backend": ServiceRecord(
                    name="feature-b-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=101,
                    requested_port=8001,
                    actual_port=8001,
                    status="running",
                ),
            },
        )
        runtime._latest_state = state

        def successful_dispatch(route: Route) -> int:
            runtime.last_dispatched_route = route
            runtime._latest_state = RunState(
                run_id="run-migrate-success",
                mode="trees",
                services=state.services,
                metadata={
                    "project_action_reports": {
                        "feature-a-1": {"migrate": {"status": "success"}},
                        "feature-b-1": {"migrate": {"status": "success"}},
                    }
                },
            )
            return 0

        runtime.dispatch = successful_dispatch  # type: ignore[assignment]

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command("m", state, runtime)

        rendered = out.getvalue()
        visible = strip_ansi(rendered)
        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-migrate-success")
        self.assertIn("✓ migrate succeeded for feature-a-1", visible)
        self.assertIn("✓ migrate succeeded for feature-b-1", visible)

