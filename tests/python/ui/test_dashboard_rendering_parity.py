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
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.test_output.parser_base import strip_ansi


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
                "○ AI session: tmux attach-session -t envctl-codex-envctl-pr98-197bdc97 (attached)",
                output,
            )
            self.assertNotIn("○ Run AI: envctl --plan features/feature-a.md --tmux", output)
            self.assertNotIn("command:", output)

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

            self.assertIn("○ Run AI: envctl --plan features/feature-a.md --tmux", output)
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
                "○ AI session: tmux attach-session -t envctl-codex-envctl-pr98-197bdc97 (detached)",
                output,
            )
            self.assertNotIn("○ Run AI: envctl --plan features/feature-a.md --tmux", output)

    def test_dashboard_quotes_project_fallback_command(self) -> None:
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

            self.assertIn("○ Run AI: envctl --project 'feature with spaces;and-symbols' --tmux", output)
            self.assertNotIn("AI session:", output)

    def test_dashboard_renders_project_ai_fallback_when_no_plan_selector_resolves(self) -> None:
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

            self.assertIn("○ Run AI: envctl --project feature_without_plan-1 --tmux", output)
            self.assertNotIn("AI session:", output)

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

            self.assertIn("○ Run AI: envctl --plan test-headless/tmux-headless-check.md --tmux", output)
            self.assertNotIn("envctl --project", output)

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

            self.assertIn("○ Run AI: envctl --plan features/task.md --tmux", output)
            self.assertNotIn("envctl --project", output)

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
