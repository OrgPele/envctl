from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.state.action_orchestrator import StateActionOrchestrator
from envctl_engine.ui.target_selector import TargetSelection


class _RuntimeStub:
    def __init__(self, state: RunState) -> None:
        self._state = state
        self.env: dict[str, str] = {}
        self.config = SimpleNamespace(raw={})
        self.seen_logs_state: RunState | None = None

    def _try_load_existing_state(self, *, mode: str, strict_mode_match: bool = False):  # noqa: ANN001, ARG002
        return self._state

    @staticmethod
    def _state_lookup_strict_mode_match(_route: Route) -> bool:
        return True

    @staticmethod
    def _reconcile_state_truth(state: RunState) -> list[str]:
        return []

    @staticmethod
    def _requirement_truth_issues(_state: RunState) -> list[dict[str, object]]:
        return []

    @staticmethod
    def _recent_failure_messages(*, max_items: int = 5):  # noqa: ANN001, ARG002
        return []

    def _print_logs(self, state: RunState, **_kwargs):  # noqa: ANN001
        self.seen_logs_state = state

    @staticmethod
    def _project_name_from_service(service_name: str) -> str:
        lowered = service_name.lower()
        if lowered.endswith(" backend"):
            return service_name[:-8].strip()
        if lowered.endswith(" frontend"):
            return service_name[:-9].strip()
        return ""

    @staticmethod
    def _selectors_from_passthrough(_args):  # noqa: ANN001
        return set()

    def _select_grouped_targets(self, **_kwargs):  # noqa: ANN001
        return TargetSelection(cancelled=True)


class StateActionOrchestratorLogsTests(unittest.TestCase):
    def test_runtime_facade_routes_state_dependencies(self) -> None:
        state = RunState(run_id="run-0", mode="main")
        runtime = _RuntimeStub(state)
        orchestrator = StateActionOrchestrator(runtime)

        loaded = orchestrator.runtime.load_state(Route(command="health", mode="main"))

        self.assertIs(loaded, state)
        self.assertEqual(orchestrator.runtime.project_name_from_service("Main Backend"), "Main")

    def test_logs_selection_filters_services(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "alpha backend": ServiceRecord(name="alpha backend", type="backend", cwd="/tmp/a"),
                "alpha frontend": ServiceRecord(name="alpha frontend", type="frontend", cwd="/tmp/a"),
                "beta backend": ServiceRecord(name="beta backend", type="backend", cwd="/tmp/b"),
            },
        )
        runtime = _RuntimeStub(state)
        orchestrator = StateActionOrchestrator(runtime)
        route = Route(command="logs", mode="trees", flags={"interactive_command": True})

        selection = TargetSelection(project_names=["alpha"])
        with (
            patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True),
            patch(
                "envctl_engine.state.action_orchestrator.RuntimeTerminalUI.flush_pending_interactive_input"
            ) as flush_mock,
            patch.object(runtime, "_select_grouped_targets", return_value=selection),
        ):
            code = orchestrator.execute(route)

        self.assertEqual(code, 0)
        flush_mock.assert_not_called()
        self.assertIsNotNone(runtime.seen_logs_state)
        self.assertIsNotNone(runtime.seen_logs_state)
        self.assertEqual(
            set(runtime.seen_logs_state.services.keys()),
            {"alpha backend", "alpha frontend"},
        )

    def test_health_prints_enabled_dependency_statuses(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend", type="backend", cwd="/tmp/main", status="running", actual_port=8000
                ),
                "Main Frontend": ServiceRecord(
                    name="Main Frontend", type="frontend", cwd="/tmp/main", status="running", actual_port=9000
                ),
            },
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    db={"enabled": True, "runtime_status": "healthy", "final": 5432, "success": True},
                    redis={"enabled": True, "runtime_status": "healthy", "final": 6380, "success": True},
                    n8n={"enabled": True, "runtime_status": "healthy", "final": 5678, "success": True},
                    supabase={"enabled": False, "runtime_status": "disabled", "final": 5432, "success": False},
                    failures=[],
                )
            },
        )
        runtime = _RuntimeStub(state)
        orchestrator = StateActionOrchestrator(runtime)

        route = Route(command="health", mode="main")
        output = StringIO()
        with redirect_stdout(output):
            code = orchestrator.execute(route)

        rendered = output.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("Health Check", rendered)
        self.assertIn("status: healthy/running=5 starting/simulated=0 issues=0", rendered)
        self.assertIn("Main\n  Services (2)\n", rendered)
        self.assertIn("  Dependencies (3)\n", rendered)
        self.assertIn("postgres", rendered)
        self.assertIn("redis", rendered)
        self.assertIn("n8n", rendered)
        self.assertIn("status=healthy", rendered)
        self.assertIn("port=5432", rendered)
        self.assertIn("port=6380", rendered)
        self.assertIn("port=5678", rendered)
        self.assertNotIn("Main supabase:", rendered)

    def test_clear_logs_truncates_service_log_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "backend.log"
            log_path.write_text("line1\nline2\n", encoding="utf-8")
            state = RunState(
                run_id="run-2",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd="/tmp/main",
                        status="running",
                        log_path=str(log_path),
                    ),
                },
            )
            runtime = _RuntimeStub(state)
            orchestrator = StateActionOrchestrator(runtime)
            route = Route(command="clear-logs", mode="main")

            output = StringIO()
            with redirect_stdout(output):
                code = orchestrator.execute(route)

            self.assertEqual(code, 0)
            self.assertEqual(log_path.read_text(encoding="utf-8"), "")
            rendered = output.getvalue()
            self.assertIn("log cleared at", rendered)
            self.assertIn("Log clear summary: cleared=1", rendered)

    def test_logs_supports_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "backend.log"
            log_path.write_text("line1\nline2\nline3\n", encoding="utf-8")
            state = RunState(
                run_id="run-3",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd="/tmp/main",
                        status="running",
                        log_path=str(log_path),
                    ),
                },
            )
            runtime = _RuntimeStub(state)
            orchestrator = StateActionOrchestrator(runtime)
            route = Route(command="logs", mode="main", flags={"json": True, "logs_tail": 2})

            output = StringIO()
            with redirect_stdout(output):
                code = orchestrator.execute(route)

            payload = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["tail"], 2)
            self.assertEqual(payload["services"][0]["name"], "Main Backend")
            self.assertEqual(payload["services"][0]["tail_lines"], ["line2", "line3"])

    def test_clear_logs_supports_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "backend.log"
            log_path.write_text("line1\n", encoding="utf-8")
            state = RunState(
                run_id="run-4",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd="/tmp/main",
                        status="running",
                        log_path=str(log_path),
                    ),
                },
            )
            runtime = _RuntimeStub(state)
            orchestrator = StateActionOrchestrator(runtime)
            route = Route(command="clear-logs", mode="main", flags={"json": True})

            output = StringIO()
            with redirect_stdout(output):
                code = orchestrator.execute(route)

            payload = json.loads(output.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["summary"]["cleared"], 1)
            self.assertEqual(payload["services"][0]["status"], "cleared")

    def test_health_supports_json_output(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend", type="backend", cwd="/tmp/main", status="running", actual_port=8000
                ),
            },
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    redis={"enabled": True, "runtime_status": "healthy", "final": 6380, "success": True},
                    failures=[],
                )
            },
        )
        runtime = _RuntimeStub(state)
        orchestrator = StateActionOrchestrator(runtime)

        route = Route(command="health", mode="main", flags={"json": True})
        output = StringIO()
        with redirect_stdout(output):
            code = orchestrator.execute(route)

        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(payload["healthy"])
        self.assertEqual(payload["run_id"], "run-1")
        self.assertEqual(payload["services"][0]["name"], "Main Backend")
        self.assertEqual(payload["dependencies"][0]["component"], "redis")

    def test_errors_supports_json_output(self) -> None:
        state = RunState(
            run_id="run-2",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend", type="backend", cwd="/tmp/main", status="failed", log_path="/tmp/backend.log"
                ),
            },
        )
        runtime = _RuntimeStub(state)
        orchestrator = StateActionOrchestrator(runtime)

        route = Route(command="errors", mode="main", flags={"json": True})
        output = StringIO()
        with redirect_stdout(output):
            code = orchestrator.execute(route)

        payload = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["failed_services"][0]["name"], "Main Backend")
        self.assertEqual(payload["failed_services"][0]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
