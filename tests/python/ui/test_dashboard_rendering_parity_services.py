# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.ui.dashboard_rendering_parity_test_support import *


class DashboardRenderingServicesParityTests(DashboardRenderingParityTestCase):
    def test_dashboard_truncates_long_project_names_and_respects_no_color(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            long_name = "FeatureWithAnExcessivelyLongProjectNameThatShouldTruncate"
            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    f"{long_name} Backend": ServiceRecord(
                        name=f"{long_name} Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8000,
                        actual_port=8001,
                        status="running",
                    ),
                    f"{long_name} Frontend": ServiceRecord(
                        name=f"{long_name} Frontend",
                        type="frontend",
                        cwd=str(repo),
                        requested_port=9000,
                        actual_port=9001,
                        status="running",
                    ),
                },
            )

            buffer = io.StringIO()
            with patch.object(PythonEngineRuntime, "_terminal_size", return_value=(30, 24)):
                with redirect_stdout(buffer):
                    engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            project_line = next(line for line in output.splitlines() if line.strip().startswith(long_name[:3]))
            self.assertIn("...", project_line)
            self.assertLessEqual(len(project_line), 30)
            self.assertNotIn("\x1b[", output)
            self.assertIn("run_id: run-1  session_id: unknown  mode: main", output)

    def test_dashboard_snapshot_reuses_recent_truth_result_for_same_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={})

            state = RunState(run_id="run-1", mode="main")
            calls = {"count": 0}

            def fake_reconcile(_state: RunState) -> list[str]:
                calls["count"] += 1
                return []

            engine._reconcile_state_truth = fake_reconcile  # type: ignore[method-assign]

            with redirect_stdout(io.StringIO()):
                engine._print_dashboard_snapshot(state)
                engine._print_dashboard_snapshot(state)

            self.assertEqual(calls["count"], 1)

    def test_dashboard_snapshot_truth_cache_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                load_config(self._config(repo, runtime)),
                env={"ENVCTL_DASHBOARD_TRUTH_REFRESH_SECONDS": "0"},
            )

            state = RunState(run_id="run-1", mode="main")
            calls = {"count": 0}

            def fake_reconcile(_state: RunState) -> list[str]:
                calls["count"] += 1
                return []

            engine._reconcile_state_truth = fake_reconcile  # type: ignore[method-assign]

            with redirect_stdout(io.StringIO()):
                engine._print_dashboard_snapshot(state)
                engine._print_dashboard_snapshot(state)

            self.assertEqual(calls["count"], 2)

    def test_dashboard_shows_only_configured_service_rows_when_no_services_are_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {
                        "feature-a-1": str(repo),
                    },
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("feature-a-1", output)
            self.assertIn("Configured Services:", output)
            self.assertIn("services: 1 configured | 0 running | 1 not running | 0 issues", output)
            self.assertIn("Backend: not running [Configured]", output)
            self.assertNotIn("Backend: n/a [Unknown]", output)
            self.assertNotIn("workspace backend:", output)
            self.assertNotIn("Frontend:", output)

    def test_dashboard_shows_stopped_service_rows_after_partial_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8000,
                        actual_port=8000,
                        pid=1234,
                        status="running",
                    ),
                },
                metadata={
                    "project_roots": {"Main": str(repo)},
                    "dashboard_stopped_services": [
                        {"name": "Main Frontend", "project": "Main", "type": "frontend"},
                    ],
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("services: 2 total | 1 running | 1 not running | 0 starting/unknown | 0 issues", output)
            self.assertIn("Backend: http://localhost:8000", output)
            self.assertIn("Frontend: not running [Stopped]", output)
            self.assertNotIn("Frontend: n/a [Unknown]", output)

    def test_dashboard_shows_project_configured_missing_backend_for_active_frontend(self) -> None:
        output, _events = self._render_dashboard_for_active_frontend(["backend", "frontend"])

        self.assertIn("services: 2 total | 1 running | 1 not running | 0 starting/unknown | 0 issues", output)
        self.assertIn("Backend: not running [Stopped]", output)
        self.assertIn("Frontend: http://localhost:9000", output)
        self.assertNotIn("Backend: n/a [Unknown]", output)

    def test_dashboard_does_not_show_unconfigured_backend_for_frontend_only_project(self) -> None:
        output, _events = self._render_dashboard_for_active_frontend(["frontend"])

        self.assertIn("services: 1 total | 1 running | 0 starting/unknown | 0 issues", output)
        self.assertNotIn("Backend:", output)
        self.assertIn("Frontend: http://localhost:9000", output)

    def test_dashboard_counts_stopped_and_configured_missing_service_once(self) -> None:
        output, _events = self._render_dashboard_for_active_frontend(
            ["backend", "frontend"],
            stopped_services=[{"name": "Main Backend", "project": "Main", "type": "backend"}],
        )

        self.assertIn("services: 2 total | 1 running | 1 not running | 0 starting/unknown | 0 issues", output)
        self.assertEqual(output.count("Backend: not running [Stopped]"), 1)

    def test_dashboard_emits_configured_missing_services_event(self) -> None:
        _output, events = self._render_dashboard_for_active_frontend(["frontend", "backend"])

        configured_missing_events = [
            payload for event, payload in events if event == "dashboard.configured_missing_services"
        ]
        self.assertEqual(
            configured_missing_events,
            [
                {
                    "run_id": "run-1",
                    "services": {"Main": ["backend"]},
                    "metadata_key": "dashboard_project_configured_services",
                }
            ],
        )

    def test_dashboard_shows_all_stopped_rows_after_entire_worktree_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            state = RunState(
                run_id="run-1",
                mode="main",
                services={},
                metadata={
                    "project_roots": {"Main": str(repo)},
                    "dashboard_stopped_services": [
                        {"name": "Main Backend", "project": "Main", "type": "backend"},
                        {"name": "Main Frontend", "project": "Main", "type": "frontend"},
                    ],
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("services: 2 total | 0 running | 2 not running | 0 starting/unknown | 0 issues", output)
            self.assertIn("Backend: not running [Stopped]", output)
            self.assertIn("Frontend: not running [Stopped]", output)
            self.assertNotIn("n/a [Unknown]", output)

    def test_dashboard_status_rows_use_cross_for_bad_states_and_neutral_for_pending_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8000,
                        actual_port=8000,
                        pid=111,
                        status="stale",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo),
                        requested_port=9000,
                        actual_port=9000,
                        pid=222,
                        status="unreachable",
                    ),
                    "Feature Backend": ServiceRecord(
                        name="Feature Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8100,
                        actual_port=8100,
                        status="starting",
                    ),
                    "Feature Frontend": ServiceRecord(
                        name="Feature Frontend",
                        type="frontend",
                        cwd=str(repo),
                        requested_port=9100,
                        actual_port=9100,
                        status="unknown",
                    ),
                },
                requirements={
                    "Main": RequirementsResult(
                        project="Main",
                        n8n={"enabled": True, "runtime_status": "unreachable", "final": 5678, "success": False},
                        supabase={"enabled": True, "success": False},
                        failures=["n8n unreachable"],
                    ),
                },
                metadata={"project_roots": {"Main": str(repo), "Feature": str(repo)}},
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("✗ Backend: n/a", output)
            self.assertIn("[Stale]", output)
            self.assertIn("✗ Frontend: http://localhost:9000", output)
            self.assertIn("[Unreachable]", output)
            self.assertIn("• Backend: http://localhost:8100", output)
            self.assertIn("[Starting]", output)
            self.assertIn("• Frontend: n/a", output)
            self.assertIn("[Unknown]", output)
            self.assertIn("✗ n8n: n/a [Unreachable]", output)
            self.assertIn("✗ supabase: n/a [Unhealthy]", output)
            self.assertNotIn("! Backend:", output)
            self.assertNotIn("! Frontend:", output)
            self.assertNotIn("! n8n:", output)

    def test_dashboard_neutral_status_severity_does_not_use_error_color(self) -> None:
        self.assertEqual(
            _dashboard_color_for_severity("neutral", ok_color="green", warn_color="yellow", bad_color="red"),
            "yellow",
        )

    def test_dashboard_renders_additional_service_rows_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            state = RunState(
                run_id="run-additional-services",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        requested_port=8000,
                        actual_port=8000,
                        pid=1111,
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo / "frontend"),
                        requested_port=9000,
                        actual_port=9000,
                        pid=2222,
                        status="running",
                    ),
                    "Main Voice Runtime": ServiceRecord(
                        name="Main Voice Runtime",
                        type="voice-runtime",
                        cwd=str(repo / "voice-runtime"),
                        requested_port=8010,
                        actual_port=8012,
                        pid=3333,
                        status="running",
                        log_path=str(runtime / "voice.log"),
                        public_url="https://voice.example.test",
                        health_url="https://voice.example.test/readyz",
                        project="Main",
                        service_slug="voice-runtime",
                    ),
                    "Main Worker": ServiceRecord(
                        name="Main Worker",
                        type="worker",
                        cwd=str(repo / "worker"),
                        pid=4444,
                        status="running",
                        listener_expected=False,
                        project="Main",
                        service_slug="worker",
                    ),
                },
                metadata={
                    "project_roots": {"Main": str(repo)},
                    "dashboard_project_configured_services": {
                        "Main": ["backend", "frontend", "voice-runtime", "worker", "webhook-relay"],
                    },
                    "dashboard_stopped_services": [
                        {"name": "Main Webhook Relay", "project": "Main", "type": "webhook-relay"},
                    ],
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertLess(output.index("Backend:"), output.index("Frontend:"))
            self.assertLess(output.index("Frontend:"), output.index("Voice Runtime"))
            self.assertIn("Voice Runtime", output)
            self.assertIn("voice-runtime", output)
            self.assertIn("http://localhost:8012", output)
            self.assertIn("https://voice.example.test", output)
            self.assertIn("https://voice.example.test/readyz", output)
            self.assertIn("voice.log", output)
            self.assertIn("Worker", output)
            self.assertIn("non-listener", output)
            self.assertIn("Webhook Relay", output)
            self.assertIn("webhook-relay", output)
            self.assertIn("[Stopped]", output)
            self.assertIn("services: 5 total | 4 running | 1 not running", output)
