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
from envctl_engine.runtime.engine_runtime_runtime_support import normalize_log_line
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.state.action_orchestrator import StateActionOrchestrator
from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.ui.target_selector import TargetSelection


class _RuntimeStub:
    def __init__(self, state: RunState) -> None:
        self._state = state
        self.env: dict[str, str] = {}
        self.config = SimpleNamespace(raw={})
        self.events: list[dict[str, object]] = []
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

    @staticmethod
    def _normalize_log_line(line: str, *, no_color: bool) -> str:
        return normalize_log_line(line, no_color=no_color)

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append({"event": event, **payload})


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

    def test_logs_service_filter_accepts_additional_service_slug_and_display_forms(self) -> None:
        state = RunState(
            run_id="run-generic-service",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd="/tmp/main"),
                "Main Voice Runtime": ServiceRecord(
                    name="Main Voice Runtime",
                    type="voice-runtime",
                    cwd="/tmp/main/voice-runtime",
                    project="Main",
                    service_slug="voice-runtime",
                ),
            },
        )
        for selector in ("voice-runtime", "service:voice-runtime", "Voice Runtime", "Main Voice Runtime"):
            with self.subTest(selector=selector):
                runtime = _RuntimeStub(state)
                orchestrator = StateActionOrchestrator(runtime)
                route = Route(command="logs", mode="main", flags={"services": [selector]})

                code = orchestrator.execute(route)

                self.assertEqual(code, 0)
                self.assertIsNotNone(runtime.seen_logs_state)
                assert runtime.seen_logs_state is not None
                self.assertEqual(set(runtime.seen_logs_state.services), {"Main Voice Runtime"})

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

    def test_health_uses_cross_for_bad_statuses_and_counts_by_severity(self) -> None:
        state = RunState(
            run_id="run-bad",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend", type="backend", cwd="/tmp/main", status="failed", actual_port=8000
                ),
                "Main Frontend": ServiceRecord(
                    name="Main Frontend", type="frontend", cwd="/tmp/main", status="unknown", actual_port=9000
                ),
                "Main Worker": ServiceRecord(
                    name="Main Worker", type="worker", cwd="/tmp/main", status="running", actual_port=9100
                ),
            },
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    n8n={"enabled": True, "runtime_status": "unreachable", "final": 5678, "success": False},
                    failures=["n8n unreachable"],
                )
            },
        )
        runtime = _RuntimeStub(state)
        orchestrator = StateActionOrchestrator(runtime)

        route = Route(command="health", mode="main")
        output = StringIO()
        with redirect_stdout(output):
            code = orchestrator.execute(route)

        rendered = strip_ansi(output.getvalue())
        self.assertEqual(code, 1)
        self.assertIn("status: healthy/running=1 starting/simulated=1 issues=2", rendered)
        self.assertIn("✗ Backend", rendered)
        self.assertIn("• Frontend", rendered)
        self.assertIn("✓ Main Worker", rendered)
        self.assertIn("✗ n8n", rendered)
        self.assertNotIn("! Backend", rendered)
        self.assertNotIn("! n8n", rendered)

    def test_state_actions_emit_spinner_lifecycle_events_after_target_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "backend.log"
            log_path.write_text("line1\nWARNING cache warmup failed\n", encoding="utf-8")
            commands = ("logs", "clear-logs", "health", "errors")
            for command in commands:
                with self.subTest(command=command):
                    state = RunState(
                        run_id=f"run-{command}",
                        mode="main",
                        services={
                            "Main Backend": ServiceRecord(
                                name="Main Backend",
                                type="backend",
                                cwd="/tmp/main",
                                status="running",
                                log_path=str(log_path),
                            )
                        },
                    )
                    runtime = _RuntimeStub(state)
                    orchestrator = StateActionOrchestrator(runtime)
                    route = Route(command=command, mode="main", flags={"all": True, "logs_tail": 10})
                    with redirect_stdout(StringIO()):
                        orchestrator.execute(route)

                    action_events = [event for event in runtime.events if event.get("event") == "state.action.start"]
                    finish_events = [event for event in runtime.events if event.get("event") == "state.action.finish"]
                    self.assertEqual(len(action_events), 1, msg=runtime.events)
                    self.assertEqual(len(finish_events), 1, msg=runtime.events)
                    self.assertEqual(action_events[0]["command"], command)
                    self.assertEqual(action_events[0]["run_id"], f"run-{command}")
                    self.assertEqual(action_events[0]["service_count"], 1)
                    self.assertEqual(action_events[0]["mode"], "main")
                    self.assertEqual(finish_events[0]["command"], command)
                    self.assertIn(finish_events[0]["code"], {0, 1})
                    reconcile_indexes = [
                        index for index, event in enumerate(runtime.events) if event.get("event") == "state.reconcile"
                    ]
                    if reconcile_indexes:
                        start_index = next(
                            index
                            for index, event in enumerate(runtime.events)
                            if event.get("event") == "state.action.start"
                        )
                        self.assertLess(start_index, reconcile_indexes[0], msg=runtime.events)

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

    def test_clear_logs_renders_clickable_paths_when_forced_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "backend.log"
            log_path.write_text("line1\nline2\n", encoding="utf-8")
            state = RunState(
                run_id="run-2a",
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
            runtime.env["ENVCTL_UI_HYPERLINK_MODE"] = "on"
            orchestrator = StateActionOrchestrator(runtime)
            route = Route(command="clear-logs", mode="main")

            output = StringIO()
            with (
                redirect_stdout(output),
                patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True),
            ):
                code = orchestrator.execute(route)

            self.assertEqual(code, 0)
            rendered = output.getvalue()
            self.assertIn("\x1b]8;;file://", rendered)
            self.assertIn(f"Main Backend: log cleared at {log_path}", strip_ansi(rendered))

    def test_clear_logs_preserves_visible_failure_path_text_when_open_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "backend.log"
            log_path.write_text("line1\n", encoding="utf-8")
            state = RunState(
                run_id="run-2b",
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
            runtime.env["ENVCTL_UI_HYPERLINK_MODE"] = "on"
            orchestrator = StateActionOrchestrator(runtime)
            route = Route(command="clear-logs", mode="main")

            output = StringIO()
            with (
                redirect_stdout(output),
                patch("pathlib.Path.open", side_effect=OSError("permission denied")),
                patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True),
            ):
                code = orchestrator.execute(route)

            self.assertEqual(code, 1)
            rendered = output.getvalue()
            self.assertIn("\x1b]8;;file://", rendered)
            self.assertIn(
                f"Main Backend: failed to clear log at {log_path} (permission denied)",
                strip_ansi(rendered),
            )

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
            metadata={"dependency_mode": "shared", "shared_dependencies": True},
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
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["overall"], "healthy")
        self.assertFalse(payload["blocking"])
        self.assertTrue(payload["critical_services_healthy"])
        self.assertEqual(payload["dependency_mode"], "shared")
        self.assertTrue(payload["shared_dependencies"])
        self.assertTrue(payload["healthy"])
        self.assertEqual(payload["run_id"], "run-1")
        self.assertEqual(payload["services"][0]["name"], "Main Backend")
        self.assertEqual(payload["dependencies"][0]["component"], "redis")

    def test_health_project_missing_json_fails_closed_without_active_rows(self) -> None:
        state = RunState(
            run_id="run-wrong-project",
            mode="trees",
            services={
                "Active Backend": ServiceRecord(
                    name="Active Backend",
                    type="backend",
                    cwd="/tmp/active",
                    project="active",
                    status="running",
                    actual_port=8001,
                )
            },
        )
        runtime = _RuntimeStub(state)
        orchestrator = StateActionOrchestrator(runtime)
        route = Route(command="health", mode="trees", projects=["missing"], flags={"json": True})

        output = StringIO()
        with redirect_stdout(output):
            code = orchestrator.execute(route)

        self.assertEqual(code, 1)
        payload = json.loads(output.getvalue())
        self.assertEqual(
            payload,
            {
                "ok": False,
                "error": "requested_project_not_running",
                "requested_project": "missing",
                "active_projects": ["active"],
            },
        )
        self.assertNotIn("services", payload)
        self.assertIn(
            {
                "event": "state.project_resolution.failed",
                "command": "health",
                "requested_project": "missing",
                "active_projects": ["active"],
                "run_id": "run-wrong-project",
            },
            runtime.events,
        )

    def test_health_project_active_json_filters_services_and_dependencies(self) -> None:
        state = RunState(
            run_id="run-filter",
            mode="trees",
            services={
                "Alpha Backend": ServiceRecord(
                    name="Alpha Backend", type="backend", cwd="/tmp/a", project="Alpha", status="running"
                ),
                "Beta Backend": ServiceRecord(
                    name="Beta Backend", type="backend", cwd="/tmp/b", project="Beta", status="running"
                ),
            },
            requirements={
                "Alpha": RequirementsResult(project="Alpha", redis={"enabled": True, "success": True}),
                "Beta": RequirementsResult(project="Beta", redis={"enabled": True, "success": True}),
            },
        )
        runtime = _RuntimeStub(state)
        orchestrator = StateActionOrchestrator(runtime)
        route = Route(command="health", mode="trees", projects=["alpha"], flags={"json": True})

        output = StringIO()
        with redirect_stdout(output):
            code = orchestrator.execute(route)

        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual([service["project"] for service in payload["services"]], ["Alpha"])
        self.assertEqual([dependency["project"] for dependency in payload["dependencies"]], ["Alpha"])

    def test_health_optional_degraded_service_is_non_blocking_unless_strict(self) -> None:
        state = RunState(
            run_id="run-optional",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend", type="backend", cwd="/tmp/main", status="running", critical=True
                ),
                "Main Voice Runtime": ServiceRecord(
                    name="Main Voice Runtime",
                    type="voice-runtime",
                    cwd="/tmp/main/voice",
                    status="failed",
                    service_slug="voice-runtime",
                    critical=False,
                    degraded=True,
                    failure_detail="startup failed",
                ),
            },
        )
        runtime = _RuntimeStub(state)
        orchestrator = StateActionOrchestrator(runtime)

        output = StringIO()
        with redirect_stdout(output):
            code = orchestrator.execute(Route(command="health", mode="main", flags={"json": True}))

        payload = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["overall"], "degraded")
        self.assertFalse(payload["blocking"])
        self.assertTrue(payload["critical_services_healthy"])
        self.assertEqual(payload["optional_failures"], ["voice-runtime"])
        self.assertEqual(payload["critical_failures"], [])

        strict_output = StringIO()
        with redirect_stdout(strict_output):
            strict_code = orchestrator.execute(Route(command="health", mode="main", flags={"json": True, "strict": True}))

        strict_payload = json.loads(strict_output.getvalue())
        self.assertEqual(strict_code, 1)
        self.assertTrue(strict_payload["ok"])
        self.assertFalse(strict_payload["blocking"])
        self.assertTrue(strict_payload["strict_blocking"])

    def test_health_critical_failure_is_blocking(self) -> None:
        state = RunState(
            run_id="run-critical",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend", type="backend", cwd="/tmp/main", status="failed", critical=True
                )
            },
        )
        runtime = _RuntimeStub(state)
        runtime._reconcile_state_truth = lambda _state: ["Main Backend"]  # type: ignore[method-assign]
        orchestrator = StateActionOrchestrator(runtime)

        output = StringIO()
        with redirect_stdout(output):
            code = orchestrator.execute(Route(command="health", mode="main", flags={"json": True}))

        payload = json.loads(output.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["overall"], "unhealthy")
        self.assertTrue(payload["blocking"])
        self.assertFalse(payload["critical_services_healthy"])
        self.assertEqual(payload["critical_failures"], ["Main Backend"])

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


    def test_errors_reports_warning_lines_from_running_service_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "backend.log"
            log_path.write_text(
                "timestamp=2026-04-27T20:20:53 level=INFO message=ok\n"
                "timestamp=2026-04-27T20:20:54 level=WARNING event=public_content.seed.failed "
                "error_type=ModuleNotFoundError error_message=No module named 'frontmatter'\n",
                encoding="utf-8",
            )
            state = RunState(
                run_id="run-6",
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
            runtime.env["ENVCTL_UI_COLOR_MODE"] = "on"
            orchestrator = StateActionOrchestrator(runtime)

            route = Route(command="errors", mode="main", flags={"interactive_command": True})
            output = StringIO()
            with redirect_stdout(output):
                code = orchestrator.execute(route)

            rendered = output.getvalue()
            self.assertEqual(code, 1)
            self.assertNotIn("No known service errors", rendered)
            self.assertIn("Main Backend: log issues", strip_ansi(rendered))
            self.assertIn("level=WARNING", strip_ansi(rendered))
            self.assertIn("No module named 'frontmatter'", strip_ansi(rendered))
            self.assertIn("\x1b[", rendered)

    def test_errors_json_includes_warning_lines_from_running_service_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "backend.log"
            log_path.write_text(
                "INFO all good\n"
                "WARNING cache warmup failed with ModuleNotFoundError\n",
                encoding="utf-8",
            )
            state = RunState(
                run_id="run-7",
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

            route = Route(command="errors", mode="main", flags={"json": True})
            output = StringIO()
            with redirect_stdout(output):
                code = orchestrator.execute(route)

            payload = json.loads(output.getvalue())
            self.assertEqual(code, 1)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["log_issues"][0]["service"], "Main Backend")
            self.assertIn("WARNING cache warmup failed", payload["log_issues"][0]["lines"][0])

    def test_errors_highlights_failure_keywords_for_interactive_output(self) -> None:
        state = RunState(
            run_id="run-5",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd="/tmp/main",
                    status="failed",
                    log_path="/tmp/backend.log",
                ),
            },
        )
        runtime = _RuntimeStub(state)
        runtime.env["ENVCTL_UI_COLOR_MODE"] = "on"
        orchestrator = StateActionOrchestrator(runtime)

        route = Route(command="errors", mode="main", flags={"interactive_command": True})
        output = StringIO()
        with redirect_stdout(output):
            code = orchestrator.execute(route)

        rendered = output.getvalue()
        self.assertEqual(code, 1)
        self.assertIn("\x1b[", rendered)
        self.assertIn("Main Backend: status=failed", strip_ansi(rendered))


if __name__ == "__main__":
    unittest.main()
