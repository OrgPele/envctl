from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.state.models import RunState, ServiceRecord


class DashboardRenderingParityTests(unittest.TestCase):
    def _config(self, repo: Path, runtime: Path) -> dict[str, str]:
        return {
            "RUN_REPO_ROOT": str(repo),
            "RUN_SH_RUNTIME_DIR": str(runtime),
            "ENVCTL_DEFAULT_MODE": "main",
        }

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

    def test_dashboard_renders_project_test_summary_link_with_passed_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            summary = engine.runtime_root / "runs" / "run-1" / "test-results" / "run_20260302_180000" / "Main" / "failed_tests_summary.txt"
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

            self.assertIn("tests:", output)
            self.assertIn(str(summary), output)
            self.assertIn("✓ tests:", output)

    def test_dashboard_renders_project_test_summary_link_with_failed_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            summary = engine.runtime_root / "runs" / "run-1" / "test-results" / "run_20260302_180001" / "Main" / "failed_tests_summary.txt"
            summary.parent.mkdir(parents=True, exist_ok=True)
            summary.write_text("# Generated at: now\n- tests/test_auth.py::test_signup_regression\n", encoding="utf-8")

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

            self.assertIn("tests:", output)
            self.assertIn(str(summary), output)
            self.assertIn("✗ tests:", output)

    def test_dashboard_renders_project_pr_link_from_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

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
                    "project_pr_links": {
                        "Main": "https://github.com/example/supportopia/pull/123",
                    }
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Main PR: https://github.com/example/supportopia/pull/123", output)

    def test_dashboard_renders_project_pr_link_in_gray_when_colors_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={})
            engine._can_interactive_tty = lambda: True  # type: ignore[assignment]

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
                    "project_pr_links": {
                        "Main": "https://github.com/example/supportopia/pull/123",
                    }
                },
            )

            buffer = io.StringIO()
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
                if command[:3] == ("git", "rev-parse", "--abbrev-ref"):
                    return SimpleNamespace(returncode=0, stdout="feature/demo\n", stderr="")
                if command[1:4] == ("pr", "list", "--head"):
                    return SimpleNamespace(returncode=0, stdout="https://github.com/example/supportopia/pull/999\n", stderr="")
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
            self.assertTrue(
                any(command[:4] == ("/usr/bin/gh", "pr", "list", "--head") for command in runner.calls),
                msg=runner.calls,
            )
            self.assertEqual(len(runner.calls), 2, msg=runner.calls)


if __name__ == "__main__":
    unittest.main()
