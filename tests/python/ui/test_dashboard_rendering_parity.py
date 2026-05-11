from __future__ import annotations

import hashlib
import io
import json
import re
import threading
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.config import load_config
from envctl_engine.requirements.common import build_container_name
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.ui.dashboard.rendering import _dashboard_color_for_severity


class _TtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


class DashboardRenderingParityTests(unittest.TestCase):
    def _config(self, repo: Path, runtime: Path) -> dict[str, str]:
        return {
            "RUN_REPO_ROOT": str(repo),
            "RUN_SH_RUNTIME_DIR": str(runtime),
            "ENVCTL_DEFAULT_MODE": "main",
        }

    def _render_dashboard_for_active_frontend(
        self,
        configured_services: list[str],
        *,
        stopped_services: list[dict[str, str]] | None = None,
    ) -> tuple[str, list[tuple[str, dict[str, object]]]]:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]
            emitted: list[tuple[str, dict[str, object]]] = []
            engine._emit = lambda event, **payload: emitted.append((event, payload))  # type: ignore[method-assign]

            metadata: dict[str, object] = {
                "project_roots": {"Main": str(repo)},
                "dashboard_project_configured_services": {"Main": configured_services},
            }
            if stopped_services is not None:
                metadata["dashboard_stopped_services"] = stopped_services
            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo),
                        requested_port=9000,
                        actual_port=9000,
                        pid=2222,
                        status="running",
                    ),
                },
                metadata=metadata,
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            return buffer.getvalue(), emitted

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

    def test_dashboard_visual_host_rewrites_dashboard_urls_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                load_config(self._config(repo, runtime)),
                env={"NO_COLOR": "1", "ENVCTL_UI_VISUAL_HOST": "192.0.2.42"},
            )
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            state = RunState(
                run_id="run-visual-host",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8000,
                        actual_port=8000,
                        pid=111,
                        status="running",
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
                },
                requirements={
                    "Main": RequirementsResult(
                        project="Main",
                        redis={"enabled": True, "runtime_status": "healthy", "final": 6380, "success": True},
                        n8n={"enabled": True, "runtime_status": "healthy", "final": 5678, "success": True},
                    ),
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Backend: http://192.0.2.42:8000", output)
            self.assertIn("Frontend: http://192.0.2.42:9000", output)
            self.assertIn("redis: http://192.0.2.42:6380 [Healthy]", output)
            self.assertIn("n8n: http://192.0.2.42:5678 [Healthy]", output)
            self.assertNotIn("http://localhost:8000", output)
            self.assertNotIn("http://localhost:9000", output)
            self.assertNotIn("http://localhost:6380", output)
            self.assertNotIn("http://localhost:5678", output)

            runtime_projection = cast(dict[str, dict[str, object]], build_runtime_map(state)["projection"])
            self.assertEqual(runtime_projection["Main"]["backend_url"], "http://localhost:8000")
            self.assertIsNone(runtime_projection["Main"]["frontend_url"])

    def test_dashboard_groups_shared_tree_dependencies_once_after_project_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                load_config(self._config(repo, runtime)),
                env={"NO_COLOR": "1", "ENVCTL_UI_VISUAL_HOST": "192.0.2.42"},
            )
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            shared_requirements = RequirementsResult(
                project="Main",
                redis={"enabled": True, "runtime_status": "healthy", "final": 6380, "success": True},
                supabase={"enabled": True, "runtime_status": "healthy", "final": 54321, "success": True},
                n8n={"enabled": True, "runtime_status": "healthy", "final": 5678, "success": True},
            )
            state = RunState(
                run_id="run-shared-deps",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8101,
                        actual_port=8101,
                        pid=111,
                        status="running",
                    ),
                    "feature-b-1 Frontend": ServiceRecord(
                        name="feature-b-1 Frontend",
                        type="frontend",
                        cwd=str(repo),
                        requested_port=9102,
                        actual_port=9102,
                        pid=222,
                        status="running",
                    ),
                },
                requirements={
                    "feature-a-1": shared_requirements,
                    "feature-b-1": shared_requirements,
                },
                metadata={
                    "project_roots": {
                        "feature-a-1": str(repo / "trees" / "feature-a" / "1"),
                        "feature-b-1": str(repo / "trees" / "feature-b" / "1"),
                    },
                    "dashboard_dependency_scope": "shared",
                    "dashboard_shared_dependency_project": "Main",
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Shared dependencies:", output)
            self.assertEqual(output.count("redis:"), 1)
            self.assertEqual(output.count("supabase:"), 1)
            self.assertEqual(output.count("n8n:"), 1)
            self.assertIn("redis: http://192.0.2.42:6380 [Healthy]", output)
            self.assertIn("supabase: http://192.0.2.42:54321 [Healthy]", output)
            self.assertIn("n8n: http://192.0.2.42:5678 [Healthy]", output)
            self.assertLess(output.index("feature-b-1"), output.index("Shared dependencies:"))

    def test_dashboard_shared_dependencies_survive_truth_reconcile_after_app_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            worktree = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            worktree.mkdir(parents=True, exist_ok=True)
            redis_container = build_container_name(prefix="envctl-redis", project_root=repo, project_name="Main")
            n8n_container = build_container_name(prefix="envctl-n8n", project_root=repo, project_name="Main")

            class _Runner:
                def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                    _ = cwd, env, timeout
                    args = tuple(cmd)
                    if args[:4] == ("docker", "ps", "-a", "--filter"):
                        name_filter = next((str(part) for part in args if str(part).startswith("name=")), "")
                        container_name = name_filter.removeprefix("name=^/").removesuffix("$")
                        if container_name in {redis_container, n8n_container}:
                            return SimpleNamespace(returncode=0, stdout=f"{container_name}\n", stderr="")
                        return SimpleNamespace(returncode=0, stdout="", stderr="")
                    if args[:2] == ("docker", "port"):
                        container = str(args[2])
                        if container == redis_container:
                            return SimpleNamespace(returncode=0, stdout="6379/tcp -> 0.0.0.0:6485\n", stderr="")
                        if container == n8n_container:
                            return SimpleNamespace(returncode=0, stdout="5678/tcp -> 0.0.0.0:5784\n", stderr="")
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

                def wait_for_port(self, port, timeout):  # noqa: ANN001
                    _ = timeout
                    return port in {6485, 5784}

            engine = PythonEngineRuntime(
                load_config(self._config(repo, runtime_dir)),
                env={"NO_COLOR": "1", "ENVCTL_UI_VISUAL_HOST": "192.0.2.42"},
            )
            engine.process_runner = _Runner()  # type: ignore[assignment]
            engine._service_truth_status = lambda service: service.status  # type: ignore[method-assign]

            state = RunState(
                run_id="run-shared-deps-after-restart",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(worktree / "backend"),
                        requested_port=8101,
                        actual_port=8101,
                        pid=111,
                        status="running",
                    ),
                    "feature-a-1 Frontend": ServiceRecord(
                        name="feature-a-1 Frontend",
                        type="frontend",
                        cwd=str(worktree / "frontend"),
                        requested_port=9101,
                        actual_port=9101,
                        pid=222,
                        status="running",
                    ),
                },
                requirements={
                    "feature-a-1": RequirementsResult(
                        project="Main",
                        redis={"enabled": True, "success": True, "final": 6485},
                        n8n={"enabled": True, "success": True, "final": 5784},
                        supabase={"enabled": True, "success": False},
                        failures=["supabase unavailable"],
                    ),
                },
                metadata={
                    "project_roots": {"feature-a-1": str(worktree), "Main": str(repo)},
                    "dashboard_dependency_scope": "shared",
                    "dashboard_shared_dependency_project": "Main",
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Shared dependencies:", output)
            self.assertIn("redis: http://192.0.2.42:6485 [Healthy]", output)
            self.assertIn("n8n: http://192.0.2.42:5784 [Healthy]", output)
            self.assertIn("supabase: n/a [Unhealthy]", output)
            self.assertNotIn("redis: n/a [Unreachable]", output)
            self.assertNotIn("n8n: n/a [Unreachable]", output)

    def test_dashboard_infers_shared_tree_dependencies_for_legacy_run_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                load_config(self._config(repo, runtime)),
                env={"NO_COLOR": "1", "ENVCTL_UI_VISUAL_HOST": "192.0.2.42"},
            )
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            shared_requirements = RequirementsResult(
                project="",
                redis={"enabled": True, "runtime_status": "healthy", "final": 6380, "success": True},
                supabase={"enabled": True, "runtime_status": "healthy", "final": 54321, "success": True},
                n8n={"enabled": True, "runtime_status": "healthy", "final": 5678, "success": True},
            )
            state = RunState(
                run_id="run-legacy-shared-deps",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8101,
                        actual_port=8101,
                        pid=111,
                        status="running",
                    ),
                    "feature-b-1 Frontend": ServiceRecord(
                        name="feature-b-1 Frontend",
                        type="frontend",
                        cwd=str(repo),
                        requested_port=9102,
                        actual_port=9102,
                        pid=222,
                        status="running",
                    ),
                },
                requirements={
                    "feature-a-1": shared_requirements,
                    "feature-b-1": shared_requirements,
                },
                metadata={
                    "project_roots": {
                        "feature-a-1": str(repo / "trees" / "feature-a" / "1"),
                        "feature-b-1": str(repo / "trees" / "feature-b" / "1"),
                    },
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Shared dependencies:", output)
            self.assertEqual(output.count("redis:"), 1)
            self.assertEqual(output.count("supabase:"), 1)
            self.assertEqual(output.count("n8n:"), 1)
            self.assertIn("redis: http://192.0.2.42:6380 [Healthy]", output)
            self.assertIn("supabase: http://192.0.2.42:54321 [Healthy]", output)
            self.assertIn("n8n: http://192.0.2.42:5678 [Healthy]", output)
            self.assertLess(output.index("feature-b-1"), output.index("Shared dependencies:"))

    def test_dashboard_keeps_isolated_tree_dependencies_under_each_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            state = RunState(
                run_id="run-isolated-deps",
                mode="trees",
                services={},
                requirements={
                    "feature-a-1": RequirementsResult(
                        project="feature-a-1",
                        redis={"enabled": True, "runtime_status": "healthy", "final": 6381, "success": True},
                    ),
                    "feature-b-1": RequirementsResult(
                        project="feature-b-1",
                        redis={"enabled": True, "runtime_status": "healthy", "final": 6382, "success": True},
                    ),
                },
                metadata={
                    "project_roots": {
                        "feature-a-1": str(repo / "trees" / "feature-a" / "1"),
                        "feature-b-1": str(repo / "trees" / "feature-b" / "1"),
                    },
                    "dashboard_dependency_scope": "isolated",
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertNotIn("Shared dependencies:", output)
            self.assertEqual(output.count("redis:"), 2)
            self.assertIn("redis: http://localhost:6381 [Healthy]", output)
            self.assertIn("redis: http://localhost:6382 [Healthy]", output)

    def test_dashboard_visual_host_blank_value_uses_public_host_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                load_config(self._config(repo, runtime)),
                env={"NO_COLOR": "1", "ENVCTL_PUBLIC_HOST": "203.0.113.10", "ENVCTL_UI_VISUAL_HOST": "   "},
            )
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            state = RunState(
                run_id="run-visual-host-default",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8000,
                        actual_port=8000,
                        pid=111,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Backend: http://203.0.113.10:8000", output)
            self.assertNotIn("http://   :8000", output)

    def test_dashboard_visual_host_defaults_to_public_host_from_envctl_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".envctl").write_text("ENVCTL_PUBLIC_HOST=203.0.113.10\n", encoding="utf-8")
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            state = RunState(
                run_id="run-public-host-envctl",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8000,
                        actual_port=8000,
                        pid=111,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Backend: http://203.0.113.10:8000", output)

    def test_dashboard_visual_host_can_be_loaded_from_envctl_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".envctl").write_text("ENVCTL_UI_VISUAL_HOST=198.51.100.7\n", encoding="utf-8")
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]

            state = RunState(
                run_id="run-visual-host-envctl",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8000,
                        actual_port=8000,
                        pid=111,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Backend: http://198.51.100.7:8000", output)
            self.assertNotIn("Backend: http://localhost:8000", output)

    def test_dashboard_neutral_status_severity_does_not_use_error_color(self) -> None:
        self.assertEqual(
            _dashboard_color_for_severity("neutral", ok_color="green", warn_color="yellow", bad_color="red"),
            "yellow",
        )

    def test_dashboard_renders_matching_ai_session_inline_for_active_project(self) -> None:
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
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo),
                        requested_port=9000,
                        actual_port=9004,
                        pid=1234,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )

            buffer = io.StringIO()
            with (
                patch(
                    "envctl_engine.runtime.session_management.list_tmux_sessions",
                    return_value=[
                        {
                            "name": "omx-supportopia-main",
                            "windows": "sh",
                            "paths": str(repo),
                            "attach": "tmux attach-session -t omx-supportopia-main",
                            "kill": "tmux kill-session -t omx-supportopia-main",
                        }
                    ],
                ),
                patch(
                    "envctl_engine.ui.dashboard.rendering._dashboard_current_tmux_target",
                    return_value=("", ""),
                ),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Frontend: http://localhost:9004", output)
            self.assertIn("AI session: tmux attach-session -t omx-supportopia-main (detached)", output)
            self.assertNotIn("Run AI:", output)
            self.assertLess(output.index("Frontend:"), output.index("AI session:"))

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

    def test_dashboard_renders_run_ai_row_when_launch_command_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "features_feature_a" / "1"
            provenance_dir = project_root / ".envctl-state"
            plan_path = repo / "todo" / "plans" / "features" / "feature-a.md"
            provenance_dir.mkdir(parents=True, exist_ok=True)
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan\n", encoding="utf-8")
            (provenance_dir / "worktree-provenance.json").write_text(
                '{"plan_file": "features/feature-a.md"}',
                encoding="utf-8",
            )
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {"features_feature_a-1": str(project_root)},
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with (
                patch(
                    "envctl_engine.runtime.session_management.list_tmux_sessions",
                    return_value=[
                        {
                            "name": "envctl-codex-envctl-pr98-197bdc97",
                            "windows": "features_feature_a-1",
                            "paths": str(project_root),
                            "attach": "tmux attach-session -t envctl-codex-envctl-pr98-197bdc97",
                            "kill": "tmux kill-session -t envctl-codex-envctl-pr98-197bdc97",
                        }
                    ],
                ),
                patch(
                    "envctl_engine.ui.dashboard.rendering._dashboard_current_tmux_target",
                    return_value=("envctl-codex-envctl-pr98-197bdc97", str(project_root)),
                ),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(
                "AI session: tmux attach-session -t envctl-codex-envctl-pr98-197bdc97 (attached)",
                output,
            )
            self.assertNotIn(f"○ Run AI: envctl --repo {repo} --plan features/feature-a.md --opencode", output)
            self.assertNotIn("command:", output)

    def test_dashboard_renders_omx_ai_session_matching_feature_slug_even_when_iteration_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project = "broken_dashboard_configured_missing_service_visibility-2"
            project_root = repo / "trees" / "broken_dashboard_configured_missing_service_visibility" / "2"
            plan_path = repo / "todo" / "plans" / "broken" / "dashboard-configured-missing-service-visibility.md"
            project_root.mkdir(parents=True, exist_ok=True)
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan\n", encoding="utf-8")
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {project: str(project_root)},
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with (
                patch(
                    "envctl_engine.runtime.session_management.list_tmux_sessions",
                    return_value=[
                        {
                            "name": "omx-1-broken-dashboard-configured-missing-service-visibility-1-1777741524847-dhd0zk",
                            "windows": "zsh",
                            "paths": str(repo),
                            "attach": (
                                "tmux attach-session -t "
                                "omx-1-broken-dashboard-configured-missing-service-visibility-1-1777741524847-dhd0zk"
                            ),
                            "kill": (
                                "tmux kill-session -t "
                                "omx-1-broken-dashboard-configured-missing-service-visibility-1-1777741524847-dhd0zk"
                            ),
                        }
                    ],
                ),
                patch(
                    "envctl_engine.ui.dashboard.rendering._dashboard_current_tmux_target",
                    return_value=("", ""),
                ),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(
                "AI session: tmux attach-session -t "
                "omx-1-broken-dashboard-configured-missing-service-visibility-1-1777741524847-dhd0zk (detached)",
                output,
            )
            self.assertNotIn("○ Run AI:", output)

    def test_dashboard_renders_envctl_plan_agent_session_by_generated_session_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "pele-monorepo"
            runtime = Path(tmpdir) / "runtime"
            project = "features_interactive_onboarding_configuration_flow-1"
            project_root = repo / "trees" / "features_interactive_onboarding_configuration_flow" / "1"
            plan_path = repo / "todo" / "plans" / "features" / "interactive-onboarding-configuration-flow.md"
            project_root.mkdir(parents=True, exist_ok=True)
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan\n", encoding="utf-8")
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    f"{project} Backend": ServiceRecord(
                        name=f"{project} Backend",
                        type="backend",
                        cwd=str(project_root / "backend"),
                        requested_port=8000,
                        actual_port=8004,
                        pid=1234,
                        status="running",
                    ),
                },
                metadata={"project_roots": {project: str(project_root)}},
            )

            buffer = io.StringIO()
            with (
                patch(
                    "envctl_engine.runtime.session_management.list_tmux_sessions",
                    return_value=[
                        {
                            "name": "envctl-pele-monorepo-trees-features_interactive_onboarding_configuration_flow-1-codex",
                            "windows": "zsh",
                            "paths": str(repo),
                            "attach": (
                                "tmux attach-session -t "
                                "envctl-pele-monorepo-trees-features_interactive_onboarding_configuration_flow-1-codex"
                            ),
                            "kill": (
                                "tmux kill-session -t "
                                "envctl-pele-monorepo-trees-features_interactive_onboarding_configuration_flow-1-codex"
                            ),
                        }
                    ],
                ),
                patch(
                    "envctl_engine.ui.dashboard.rendering._dashboard_current_tmux_target",
                    return_value=("", ""),
                ),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(
                "AI session: tmux attach-session -t "
                "envctl-pele-monorepo-trees-features_interactive_onboarding_configuration_flow-1-codex "
                "(detached)",
                output,
            )
            self.assertNotIn("○ Run AI:", output)

    def test_dashboard_renders_worktree_ai_launcher_when_plan_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "pele-monorepo"
            runtime = Path(tmpdir) / "runtime"
            project = "features_interactive_onboarding_configuration_flow-1"
            project_root = repo / "trees" / "features_interactive_onboarding_configuration_flow" / "1"
            provenance_dir = project_root / ".envctl-state"
            provenance_dir.mkdir(parents=True, exist_ok=True)
            (project_root / "MAIN_TASK.md").write_text("# Task\n", encoding="utf-8")
            (provenance_dir / "worktree-provenance.json").write_text(
                json.dumps({"plan_file": "features/interactive-onboarding-configuration-flow.md"}),
                encoding="utf-8",
            )
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    f"{project} Backend": ServiceRecord(
                        name=f"{project} Backend",
                        type="backend",
                        cwd=str(project_root / "backend"),
                        requested_port=8000,
                        actual_port=8004,
                        pid=1234,
                        status="running",
                    ),
                },
                metadata={"project_roots": {project: str(project_root)}},
            )

            buffer = io.StringIO()
            with (
                patch("envctl_engine.runtime.session_management.list_tmux_sessions", return_value=[]),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(f"○ Run AI: envctl --repo {project_root} codex-tmux", output)
            self.assertNotIn("AI session:", output)

    def test_dashboard_renders_run_ai_row_only_when_no_matching_session_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "features_feature_a" / "1"
            provenance_dir = project_root / ".envctl-state"
            plan_path = repo / "todo" / "plans" / "features" / "feature-a.md"
            provenance_dir.mkdir(parents=True, exist_ok=True)
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan\n", encoding="utf-8")
            (provenance_dir / "worktree-provenance.json").write_text(
                '{"plan_file": "features/feature-a.md"}',
                encoding="utf-8",
            )
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {"features_feature_a-1": str(project_root)},
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with (
                patch("envctl_engine.runtime.session_management.list_tmux_sessions", return_value=[]),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(f"○ Run AI: envctl --repo {repo} --plan features/feature-a.md --opencode", output)
            self.assertNotIn("AI session:", output)

    def test_dashboard_renders_run_ai_row_for_running_worktree_without_ai_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "features_feature_a" / "1"
            provenance_dir = project_root / ".envctl-state"
            plan_path = repo / "todo" / "plans" / "features" / "feature-a.md"
            provenance_dir.mkdir(parents=True, exist_ok=True)
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan\n", encoding="utf-8")
            (provenance_dir / "worktree-provenance.json").write_text(
                '{"plan_file": "features/feature-a.md"}',
                encoding="utf-8",
            )
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._dashboard_reconcile_for_snapshot = lambda _state: []  # type: ignore[method-assign]

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "features_feature_a-1 Backend": ServiceRecord(
                        name="features_feature_a-1 Backend",
                        type="backend",
                        cwd=str(project_root),
                        requested_port=8000,
                        actual_port=8004,
                        pid=1234,
                        status="running",
                    ),
                    "features_feature_a-1 Frontend": ServiceRecord(
                        name="features_feature_a-1 Frontend",
                        type="frontend",
                        cwd=str(project_root),
                        requested_port=9000,
                        actual_port=9004,
                        pid=1235,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"features_feature_a-1": str(project_root)}},
            )

            buffer = io.StringIO()
            with (
                patch("envctl_engine.runtime.session_management.list_tmux_sessions", return_value=[]),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Backend: http://localhost:8004", output)
            self.assertIn("Frontend: http://localhost:9004", output)
            self.assertIn(f"○ Run AI: envctl --repo {repo} --plan features/feature-a.md --opencode", output)
            self.assertNotIn("AI session:", output)

    def test_dashboard_prefers_attach_when_window_matches_but_session_path_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "features_feature_a" / "1"
            provenance_dir = project_root / ".envctl-state"
            plan_path = repo / "todo" / "plans" / "features" / "feature-a.md"
            provenance_dir.mkdir(parents=True, exist_ok=True)
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan\n", encoding="utf-8")
            (provenance_dir / "worktree-provenance.json").write_text(
                '{"plan_file": "features/feature-a.md"}',
                encoding="utf-8",
            )
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {"features_feature_a-1": str(project_root)},
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with (
                patch(
                    "envctl_engine.runtime.session_management.list_tmux_sessions",
                    return_value=[
                        {
                            "name": "envctl-codex-envctl-pr98-197bdc97",
                            "windows": "features_feature_a-1",
                            "paths": str(repo / "somewhere_else"),
                            "attach": "tmux attach-session -t envctl-codex-envctl-pr98-197bdc97",
                            "kill": "tmux kill-session -t envctl-codex-envctl-pr98-197bdc97",
                        }
                    ],
                ),
                patch(
                    "envctl_engine.ui.dashboard.rendering._dashboard_current_tmux_target",
                    return_value=("", ""),
                ),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(
                "AI session: tmux attach-session -t envctl-codex-envctl-pr98-197bdc97 (detached)",
                output,
            )
            self.assertNotIn(f"○ Run AI: envctl --repo {repo} --plan features/feature-a.md --opencode", output)

    def test_dashboard_omits_run_ai_when_plan_selector_does_not_resolve_for_quoted_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_name = "feature with spaces;and-symbols"
            project_root = repo / "trees" / project_name / "1"
            project_root.mkdir(parents=True, exist_ok=True)
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {project_name: str(project_root)},
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with (
                patch("envctl_engine.runtime.session_management.list_tmux_sessions", return_value=[]),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertNotIn("Run AI:", output)
            self.assertNotIn("codex-tmux", output)
            self.assertNotIn("AI session:", output)

    def test_dashboard_omits_project_ai_fallback_when_no_plan_selector_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "feature_without_plan" / "1"
            project_root.mkdir(parents=True, exist_ok=True)
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {"feature_without_plan-1": str(project_root)},
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with (
                patch("envctl_engine.runtime.session_management.list_tmux_sessions", return_value=[]),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertNotIn("Run AI:", output)
            self.assertNotIn("codex-tmux", output)
            self.assertNotIn("AI session:", output)

    def test_dashboard_infers_plan_from_parent_repo_for_git_worktree_without_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "refactoring_supportopia_to_pele_complete_repo_rename" / "1"
            plan_path = repo / "todo" / "plans" / "refactoring" / "supportopia-to-pele-complete-repo-rename.md"
            project_root.mkdir(parents=True, exist_ok=True)
            (project_root / "todo").mkdir(parents=True, exist_ok=True)
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan\n", encoding="utf-8")
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "bin").mkdir(parents=True, exist_ok=True)
            (repo / "bin" / "envctl").write_text("#!/bin/sh\n", encoding="utf-8")
            (project_root / ".git").write_text("gitdir: ignored\n", encoding="utf-8")
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {"refactoring_supportopia_to_pele_complete_repo_rename-1": str(project_root)},
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with (
                patch("envctl_engine.runtime.session_management.list_tmux_sessions", return_value=[]),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(
                f"○ Run AI: envctl --repo {repo} "
                "--plan refactoring/supportopia-to-pele-complete-repo-rename.md --opencode",
                output,
            )
            self.assertNotIn("codex-tmux", output)

    def test_dashboard_renders_run_ai_row_for_worktree_using_created_from_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "test_headless_tmux_headless_check" / "1"
            provenance_dir = project_root / ".envctl-state"
            plan_path = repo / "todo" / "plans" / "test-headless" / "tmux-headless-check.md"
            provenance_dir.mkdir(parents=True, exist_ok=True)
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Plan\n", encoding="utf-8")
            (provenance_dir / "worktree-provenance.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "created_from_repo": str(repo),
                        "plan_file": "test-headless/tmux-headless-check.md",
                    }
                ),
                encoding="utf-8",
            )
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {"test_headless_tmux_headless_check-1": str(project_root)},
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with (
                patch("envctl_engine.runtime.session_management.list_tmux_sessions", return_value=[]),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(f"○ Run AI: envctl --repo {repo} --plan test-headless/tmux-headless-check.md --opencode", output)
            self.assertNotIn(" --project", output)

    def test_dashboard_renders_run_ai_row_when_active_plan_and_archived_copy_both_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "features_task"
            active_plan = repo / "todo" / "plans" / "features" / "task.md"
            archived_plan = repo / "todo" / "done" / "features" / "task.md"
            project_root.mkdir(parents=True, exist_ok=True)
            active_plan.parent.mkdir(parents=True, exist_ok=True)
            archived_plan.parent.mkdir(parents=True, exist_ok=True)
            active_plan.write_text("# active\n", encoding="utf-8")
            archived_plan.write_text("# archived\n", encoding="utf-8")
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={},
                metadata={
                    "project_roots": {"features_task": str(project_root)},
                    "dashboard_configured_service_types": ["backend"],
                    "dashboard_runs_disabled": True,
                    "dashboard_banner": "envctl runs are disabled for trees; planning and action commands remain available.",
                },
            )

            buffer = io.StringIO()
            with (
                patch("envctl_engine.runtime.session_management.list_tmux_sessions", return_value=[]),
                redirect_stdout(buffer),
            ):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(f"○ Run AI: envctl --repo {repo} --plan features/task.md --opencode", output)
            self.assertNotIn(" --project", output)

    def test_dashboard_does_not_render_workspace_rows_for_running_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "feature-a-1 Frontend": ServiceRecord(
                        name="feature-a-1 Frontend",
                        type="frontend",
                        cwd=str(repo),
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"feature-a-1": str(repo)}},
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertNotIn("workspace backend:", output)
            self.assertNotIn("workspace frontend:", output)

    def test_dashboard_renders_service_log_on_single_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            log_path = Path(tmpdir) / "backend.log"
            log_path.write_text("ok\n", encoding="utf-8")
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

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
                        status="running",
                        log_path=str(log_path),
                    ),
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(f"log: {log_path}", output)
            self.assertNotIn("log:\n", output)

    def test_dashboard_path_output_keeps_visible_text_and_adds_hyperlinks_when_forced(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            log_path = Path(tmpdir) / "backend.log"
            log_path.write_text("ok\n", encoding="utf-8")
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                load_config(self._config(repo, runtime)),
                env={"ENVCTL_UI_HYPERLINK_MODE": "on", "NO_COLOR": "1"},
            )
            summary = (
                engine.runtime_root
                / "runs"
                / "run-1"
                / "test-results"
                / "run_20260302_180000"
                / "Main"
                / "failed_tests_summary.txt"
            )
            summary.parent.mkdir(parents=True, exist_ok=True)
            summary.write_text("# Generated at: now\nNo failed tests.\n", encoding="utf-8")

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
                        status="running",
                        log_path=str(log_path),
                    ),
                },
                metadata={
                    "project_test_summaries": {
                        "Main": {
                            "summary_path": str(summary),
                            "status": "passed",
                        }
                    }
                },
            )

            buffer = _TtyStringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()
            visible = strip_ansi(output)
            from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator

            expected_summary = DashboardOrchestrator._test_summary_display_path(
                project_name="Main",
                entry=state.metadata["project_test_summaries"]["Main"],
            )

            self.assertIn("\x1b]8;;file://", output)
            self.assertIn(f"log: {log_path}", visible)
            self.assertIn(f"tests: {expected_summary}", visible)

    def test_dashboard_renders_project_test_summary_link_with_passed_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            summary = (
                engine.runtime_root
                / "runs"
                / "run-1"
                / "test-results"
                / "run_20260302_180000"
                / "Main"
                / "failed_tests_summary.txt"
            )
            summary.parent.mkdir(parents=True, exist_ok=True)
            summary.write_text("# Generated at: now\nNo failed tests.\n", encoding="utf-8")

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
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo),
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
                metadata={
                    "project_test_summaries": {
                        "Main": {
                            "summary_path": str(summary),
                            "status": "passed",
                        }
                    }
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()
            expected_short = engine.runtime_root / "runs" / "run-1" / f"ft_{hashlib.sha1(b'Main').hexdigest()[:10]}.txt"
            tests_line = next(line for line in output.splitlines() if "tests:" in line and str(expected_short) in line)

            self.assertIn("tests:", output)
            self.assertIn(str(expected_short), output)
            self.assertIn("✓ tests:", output)
            self.assertRegex(tests_line, rf"✓ tests: {re.escape(str(expected_short))} \([A-Z][a-z]{{2}} \d{{2}} \d{{2}}:\d{{2}}\)")
            self.assertTrue(expected_short.is_file())
            self.assertEqual(expected_short.read_text(encoding="utf-8"), summary.read_text(encoding="utf-8"))
            self.assertNotIn(str(summary), output)

    def test_dashboard_renders_project_test_summary_link_with_failed_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            summary = (
                engine.runtime_root
                / "runs"
                / "run-1"
                / "test-results"
                / "run_20260302_180001"
                / "Main"
                / "failed_tests_summary.txt"
            )
            summary.parent.mkdir(parents=True, exist_ok=True)
            summary.write_text(
                (
                    "# Generated at: now\n"
                    "[Repository tests (unittest)]\n"
                    "- tests/test_auth.py::test_signup_regression\n"
                    "    AssertionError: expected 201, got 500\n"
                ),
                encoding="utf-8",
            )

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
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo),
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
                metadata={
                    "project_test_summaries": {
                        "Main": {
                            "summary_path": str(summary),
                            "status": "failed",
                        }
                    }
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()
            expected_short = engine.runtime_root / "runs" / "run-1" / f"ft_{hashlib.sha1(b'Main').hexdigest()[:10]}.txt"
            tests_line = next(line for line in output.splitlines() if "tests:" in line and str(expected_short) in line)

            self.assertIn("tests:", output)
            self.assertIn(str(expected_short), output)
            self.assertIn("✗ tests:", output)
            self.assertRegex(tests_line, rf"✗ tests: {re.escape(str(expected_short))} \([A-Z][a-z]{{2}} \d{{2}} \d{{2}}:\d{{2}}\)")
            self.assertNotIn("tests/test_auth.py::test_signup_regression", output)
            self.assertNotIn("AssertionError: expected 201, got 500", output)
            self.assertTrue(expected_short.is_file())
            self.assertEqual(expected_short.read_text(encoding="utf-8"), summary.read_text(encoding="utf-8"))
            self.assertNotIn(str(summary), output)

    def test_dashboard_renders_active_project_pr_link(self) -> None:
        class _Runner:
            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = tuple(str(token) for token in cmd)
                if command == ("git", "rev-parse", "--abbrev-ref", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="dev\n", stderr="")
                if command == ("git", "rev-parse", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")
                if command[:4] == ("/usr/bin/gh", "pr", "list", "--head"):
                    return SimpleNamespace(
                        returncode=0,
                        stdout='[{"url":"https://github.com/example/supportopia/pull/123","state":"OPEN","mergedAt":null,"headRefOid":"abc123"}]\n',
                        stderr="",
                    )
                return SimpleNamespace(returncode=1, stdout="", stderr="unsupported")

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine.process_runner = _Runner()  # type: ignore[assignment]

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo / "frontend"),
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )

            buffer = io.StringIO()
            with patch("envctl_engine.ui.dashboard.rendering.shutil.which", return_value="/usr/bin/gh"):
                with redirect_stdout(buffer):
                    engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Main PR: https://github.com/example/supportopia/pull/123", output)

    def test_dashboard_renders_project_pr_link_in_gray_when_colors_enabled(self) -> None:
        class _Runner:
            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = tuple(str(token) for token in cmd)
                if command == ("git", "rev-parse", "--abbrev-ref", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="dev\n", stderr="")
                if command == ("git", "rev-parse", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")
                if command[:4] == ("/usr/bin/gh", "pr", "list", "--head"):
                    return SimpleNamespace(
                        returncode=0,
                        stdout='[{"url":"https://github.com/example/supportopia/pull/123","state":"OPEN","mergedAt":null,"headRefOid":"abc123"}]\n',
                        stderr="",
                    )
                return SimpleNamespace(returncode=1, stdout="", stderr="unsupported")

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={})
            engine._can_interactive_tty = lambda: True  # type: ignore[assignment]
            engine.process_runner = _Runner()  # type: ignore[assignment]

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo / "frontend"),
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )

            buffer = io.StringIO()
            with patch("envctl_engine.ui.dashboard.rendering.shutil.which", return_value="/usr/bin/gh"):
                with redirect_stdout(buffer):
                    engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("\x1b[90mhttps://github.com/example/supportopia/pull/123\x1b[0m", output)

    def test_dashboard_pr_lookup_uses_cache_when_metadata_missing(self) -> None:
        class _Runner:
            def __init__(self) -> None:
                self.calls: list[tuple[str, ...]] = []

            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = tuple(str(token) for token in cmd)
                self.calls.append(command)
                if command == ("git", "rev-parse", "--abbrev-ref", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="feature/demo\n", stderr="")
                if command == ("git", "rev-parse", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")
                if command[1:4] == ("pr", "list", "--head"):
                    return SimpleNamespace(
                        returncode=0,
                        stdout='[{"url":"https://github.com/example/supportopia/pull/999","state":"OPEN","mergedAt":null,"headRefOid":"abc123"}]\n',
                        stderr="",
                    )
                return SimpleNamespace(returncode=1, stdout="", stderr="unsupported")

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            runner = _Runner()
            engine.process_runner = runner  # type: ignore[assignment]

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo / "frontend"),
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
                metadata={
                    "project_roots": {
                        "Main": str(repo),
                    }
                },
            )

            with patch("envctl_engine.ui.dashboard.rendering.shutil.which", return_value="/usr/bin/gh"):
                with redirect_stdout(io.StringIO()):
                    engine._print_dashboard_snapshot(state)
                    engine._print_dashboard_snapshot(state)

            self.assertIn(("git", "rev-parse", "--abbrev-ref", "HEAD"), runner.calls)
            self.assertIn(("git", "rev-parse", "HEAD"), runner.calls)
            self.assertTrue(
                any(command[:4] == ("/usr/bin/gh", "pr", "list", "--head") for command in runner.calls),
                msg=runner.calls,
            )
            self.assertEqual(len(runner.calls), 5, msg=runner.calls)

    def test_dashboard_prefetches_project_pr_lookups_in_parallel(self) -> None:
        class _Runner:
            def __init__(self) -> None:
                self._lock = threading.Lock()
                self._active_gh = 0
                self.max_active_gh = 0

            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = env, timeout
                command = tuple(str(token) for token in cmd)
                if command == ("git", "rev-parse", "--abbrev-ref", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="feature/demo\n", stderr="")
                if command == ("git", "rev-parse", "HEAD"):
                    name = Path(cwd).name if cwd is not None else "unknown"
                    return SimpleNamespace(returncode=0, stdout=f"{name}\n", stderr="")
                if command[:4] == ("/usr/bin/gh", "pr", "list", "--head"):
                    with self._lock:
                        self._active_gh += 1
                        self.max_active_gh = max(self.max_active_gh, self._active_gh)
                    time.sleep(0.05)
                    with self._lock:
                        self._active_gh -= 1
                    return SimpleNamespace(returncode=0, stdout="[]\n", stderr="")
                return SimpleNamespace(returncode=1, stdout="", stderr="unsupported")

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            for project_name in ("feature-a-1", "feature-b-1", "feature-c-1"):
                (repo / project_name / "backend").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            runner = _Runner()
            engine.process_runner = runner  # type: ignore[assignment]

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo / "feature-a-1" / "backend"),
                        requested_port=8001,
                        actual_port=8001,
                        status="running",
                    ),
                    "feature-b-1 Backend": ServiceRecord(
                        name="feature-b-1 Backend",
                        type="backend",
                        cwd=str(repo / "feature-b-1" / "backend"),
                        requested_port=8002,
                        actual_port=8002,
                        status="running",
                    ),
                    "feature-c-1 Backend": ServiceRecord(
                        name="feature-c-1 Backend",
                        type="backend",
                        cwd=str(repo / "feature-c-1" / "backend"),
                        requested_port=8003,
                        actual_port=8003,
                        status="running",
                    ),
                },
                metadata={
                    "project_roots": {
                        "feature-a-1": str(repo / "feature-a-1"),
                        "feature-b-1": str(repo / "feature-b-1"),
                        "feature-c-1": str(repo / "feature-c-1"),
                    }
                },
            )

            with patch("envctl_engine.ui.dashboard.rendering.shutil.which", return_value="/usr/bin/gh"):
                with redirect_stdout(io.StringIO()):
                    engine._print_dashboard_snapshot(state)

            self.assertGreaterEqual(runner.max_active_gh, 2)

    def test_dashboard_does_not_render_closed_project_pr(self) -> None:
        class _Runner:
            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = tuple(str(token) for token in cmd)
                if command == ("git", "rev-parse", "--abbrev-ref", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="dev\n", stderr="")
                if command == ("git", "rev-parse", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")
                if command[:4] == ("/usr/bin/gh", "pr", "list", "--head"):
                    return SimpleNamespace(
                        returncode=0,
                        stdout='[{"url":"https://github.com/example/supportopia/pull/123","state":"CLOSED","mergedAt":null,"headRefOid":"abc123"}]\n',
                        stderr="",
                    )
                return SimpleNamespace(returncode=1, stdout="", stderr="unsupported")

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine.process_runner = _Runner()  # type: ignore[assignment]

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )

            buffer = io.StringIO()
            with patch("envctl_engine.ui.dashboard.rendering.shutil.which", return_value="/usr/bin/gh"):
                with redirect_stdout(buffer):
                    engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertNotIn("Main PR:", output)

    def test_dashboard_renders_merged_project_pr_only_when_head_matches(self) -> None:
        class _Runner:
            def __init__(self, *, head_oid: str) -> None:
                self.head_oid = head_oid

            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = tuple(str(token) for token in cmd)
                if command == ("git", "rev-parse", "--abbrev-ref", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="dev\n", stderr="")
                if command == ("git", "rev-parse", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout=f"{self.head_oid}\n", stderr="")
                if command[:4] == ("/usr/bin/gh", "pr", "list", "--head"):
                    return SimpleNamespace(
                        returncode=0,
                        stdout='[{"url":"https://github.com/example/supportopia/pull/123","state":"MERGED","mergedAt":"2026-03-10T14:29:43Z","headRefOid":"abc123"}]\n',
                        stderr="",
                    )
                return SimpleNamespace(returncode=1, stdout="", stderr="unsupported")

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )

            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine.process_runner = _Runner(head_oid="abc123")  # type: ignore[assignment]
            buffer = io.StringIO()
            with patch("envctl_engine.ui.dashboard.rendering.shutil.which", return_value="/usr/bin/gh"):
                with redirect_stdout(buffer):
                    engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()
            self.assertIn("Main PR: https://github.com/example/supportopia/pull/123 (merged)", output)

            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine.process_runner = _Runner(head_oid="def456")  # type: ignore[assignment]
            buffer = io.StringIO()
            with patch("envctl_engine.ui.dashboard.rendering.shutil.which", return_value="/usr/bin/gh"):
                with redirect_stdout(buffer):
                    engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()
            self.assertNotIn("Main PR:", output)


if __name__ == "__main__":
    unittest.main()
