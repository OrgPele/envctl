# ruff: noqa: F401
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator
from envctl_engine.ui.dashboard.pr_flow import PrFlowResult
from envctl_engine.ui.target_selector import TargetSelection

from tests.python.ui.dashboard_orchestrator_test_support import (
    _DashboardOrchestratorTestCase,
    _RuntimeStub,
    _TtyStringIO,
)


class DashboardOrchestratorPrFlowFailureDetailsTests(_DashboardOrchestratorTestCase):
    def test_project_action_failure_details_render_hyperlinked_report_path(self) -> None:
        runtime = _RuntimeStub()
        runtime.env["ENVCTL_UI_HYPERLINK_MODE"] = "on"
        orchestrator = DashboardOrchestrator(runtime)
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "failure.log"
            report_path.write_text("report\n", encoding="utf-8")
            state = RunState(
                run_id="run-1",
                mode="main",
                metadata={
                    "project_action_reports": {
                        "Main": {
                            "review": {
                                "status": "failed",
                                "summary": "review failed\nhint: open the log",
                                "report_path": str(report_path),
                            }
                        }
                    }
                },
            )

            out = _TtyStringIO()
            with redirect_stdout(out):
                printed = orchestrator._print_project_action_failure_details(
                    Route(
                        command="review",
                        mode="main",
                        raw_args=["review"],
                        passthrough_args=[],
                        projects=["Main"],
                        flags={},
                    ),
                    state,
                )

        self.assertTrue(printed)
        self.assertIn("\x1b]8;;file://", out.getvalue())
        self.assertIn(str(report_path), strip_ansi(out.getvalue()))

    def test_project_action_failure_details_print_migrate_results_in_route_order_with_deduped_hints(self) -> None:
        runtime = _RuntimeStub()
        runtime.env["ENVCTL_UI_HYPERLINK_MODE"] = "on"
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-migrate-results",
            mode="trees",
            metadata={
                "project_action_reports": {
                    "feature-a-1": {
                        "migrate": {
                            "status": "success",
                        }
                    },
                    "feature-b-1": {
                        "migrate": {
                            "status": "failed",
                            "headline": "alembic.util.exc.CommandError: migration failed",
                            "summary": (
                                "Traceback (most recent call last):\n"
                                "alembic.util.exc.CommandError: migration failed\n"
                                "hint: envctl migrate loads backend env from backend/.env by default.\n"
                                "hint: envctl migrate loads backend env from backend/.env by default.\n"
                                "hint: BACKEND_ENV_FILE_OVERRIDE or MAIN_ENV_FILE_PATH can redirect the env file.\n"
                            ),
                            "report_path": "/tmp/runtime/feature-b-1_migrate.txt",
                        }
                    },
                }
            },
        )

        out = _TtyStringIO()
        with redirect_stdout(out):
            printed = orchestrator._print_project_action_failure_details(
                Route(
                    command="migrate",
                    mode="trees",
                    raw_args=["migrate"],
                    passthrough_args=[],
                    projects=["feature-a-1", "feature-b-1"],
                    flags={},
                ),
                state,
            )

        self.assertTrue(printed)
        rendered = strip_ansi(out.getvalue())
        self.assertLess(
            rendered.index("✓ migrate succeeded for feature-a-1"),
            rendered.index("✗ migrate failed for feature-b-1: alembic.util.exc.CommandError: migration failed"),
        )
        self.assertEqual(
            rendered.count("hint: envctl migrate loads backend env from backend/.env by default."),
            1,
        )
        self.assertIn(
            "hint: BACKEND_ENV_FILE_OVERRIDE or MAIN_ENV_FILE_PATH can redirect the env file.",
            rendered,
        )
        self.assertIn(
            "migrate failure log for feature-b-1:\n/tmp/runtime/feature-b-1_migrate.txt",
            rendered,
        )

    def test_project_action_failure_details_print_migrate_results_for_all_selection_using_state_projects(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-migrate-all-selection",
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
            metadata={
                "project_action_reports": {
                    "feature-a-1": {"migrate": {"status": "success"}},
                    "feature-b-1": {
                        "migrate": {
                            "status": "failed",
                            "headline": "pydantic_core._pydantic_core.ValidationError: missing env",
                            "summary": (
                                "pydantic_core._pydantic_core.ValidationError: missing env\n"
                                "hint: envctl migrate loads backend env from backend/.env by default.\n"
                            ),
                            "report_path": "/tmp/runtime/feature-b-1_migrate.txt",
                        }
                    },
                }
            },
        )

        out = StringIO()
        with redirect_stdout(out):
            printed = orchestrator._print_project_action_failure_details(
                Route(
                    command="migrate",
                    mode="trees",
                    raw_args=["migrate", "--all"],
                    passthrough_args=[],
                    projects=[],
                    flags={"all": True},
                ),
                state,
            )

        rendered = strip_ansi(out.getvalue())
        self.assertTrue(printed)
        self.assertIn("✓ migrate succeeded for feature-a-1", rendered)
        self.assertIn(
            "✗ migrate failed for feature-b-1: pydantic_core._pydantic_core.ValidationError: missing env",
            rendered,
        )
        self.assertIn("migrate failure log for feature-b-1:\n/tmp/runtime/feature-b-1_migrate.txt", rendered)

    def test_project_action_failure_details_compact_multi_failure_logs_and_hints(self) -> None:
        runtime = _RuntimeStub()
        runtime.env["ENVCTL_UI_COLOR_MODE"] = "on"
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-migrate-compact-failures",
            mode="trees",
            metadata={
                "project_action_reports": {
                    "feature-a-1": {
                        "migrate": {
                            "status": "failed",
                            "headline": "ConnectionResetError: [Errno 54] Connection reset by peer",
                            "summary": (
                                "ConnectionResetError: [Errno 54] Connection reset by peer\n"
                                "hint: backend env source: default | /tmp/runtime/backend-a.env\n"
                                "hint: backend connection was reset while applying migrations.\n"
                            ),
                            "report_path": "/tmp/runtime/run-compact/feature-a-1_migrate.txt",
                        }
                    },
                    "feature-b-1": {
                        "migrate": {
                            "status": "failed",
                            "headline": "ConnectionResetError: [Errno 54] Connection reset by peer",
                            "summary": (
                                "ConnectionResetError: [Errno 54] Connection reset by peer\n"
                                "hint: backend env source: default | /tmp/runtime/backend-b.env\n"
                                "hint: backend connection was reset while applying migrations.\n"
                            ),
                            "report_path": "/tmp/runtime/run-compact/feature-b-1_migrate.txt",
                        }
                    },
                }
            },
        )

        out = _TtyStringIO()
        with redirect_stdout(out):
            printed = orchestrator._print_project_action_failure_details(
                Route(
                    command="migrate",
                    mode="trees",
                    raw_args=["migrate"],
                    passthrough_args=[],
                    projects=["feature-a-1", "feature-b-1"],
                    flags={},
                ),
                state,
            )

        raw_rendered = out.getvalue()
        self.assertIn("\x1b[1;31m✗\x1b[0m", raw_rendered)
        self.assertIn("\x1b[1;34mfeature-a-1\x1b[0m", raw_rendered)
        self.assertIn("\x1b[1;35mfeature-b-1\x1b[0m", raw_rendered)
        rendered = strip_ansi(raw_rendered)
        self.assertTrue(printed)
        self.assertIn("✗ migrate failed for feature-a-1: ConnectionResetError: [Errno 54] Connection reset by peer", rendered)
        self.assertIn("✗ migrate failed for feature-b-1: ConnectionResetError: [Errno 54] Connection reset by peer", rendered)
        self.assertEqual(rendered.count("hint: backend connection was reset while applying migrations."), 1)
        self.assertNotIn("hint: backend env source:", rendered)
        self.assertIn("migrate failure logs:", rendered)
        self.assertIn("/tmp/runtime/run-compact", rendered)
        self.assertIn("- feature-a-1: feature-a-1_migrate.txt", rendered)
        self.assertIn("- feature-b-1: feature-b-1_migrate.txt", rendered)
        self.assertNotIn("migrate failure log for feature-a-1:", rendered)
        self.assertNotIn("migrate failure log for feature-b-1:", rendered)
