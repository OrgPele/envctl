from __future__ import annotations

import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

from tests.python.actions.actions_parity_test_support import (
    PythonEngineRuntime,
    RunState,
    ServiceRecord,
    _ActionsParityTestCase,
    _FakeRunner,
    _TtyStringIO,
    action_migrate_support_module,
    parse_route,
    strip_ansi,
)


class ActionsMigrateReportingParityTests(_ActionsParityTestCase):
    def test_migrate_action_failure_summary_includes_env_hint_for_missing_settings_vars(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            backend_dir = target / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            (backend_dir / ".env").write_text("CUSTOM_BACKEND_FLAG=enabled\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            self._save_state(
                engine,
                RunState(
                    run_id="run-migrate-failure",
                    mode="trees",
                    services={
                        "feature-a-1 Backend": ServiceRecord(
                            name="feature-a-1 Backend",
                            type="backend",
                            cwd=str(backend_dir),
                            pid=1001,
                            requested_port=8000,
                            actual_port=8000,
                            status="running",
                        )
                    },
                ),
            )
            fake_runner = _FakeRunner(
                returncode=1,
                stderr=(
                    "Traceback (most recent call last):\n"
                    '  File "/tmp/project/backend/alembic/env.py", line 19, in <module>\n'
                    "    from app.core.config import settings\n"
                    "pydantic_core._pydantic_core.ValidationError: 2 validation errors for Settings\n"
                    "DATABASE_URL\n"
                    "  Field required [type=missing, input_value={}, input_type=dict]\n"
                    "REDIS_URL\n"
                    "  Field required [type=missing, input_value={}, input_type=dict]\n"
                ),
            )
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)

            self.assertEqual(code, 1)
            saved_state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(saved_state)
            assert saved_state is not None
            reports = saved_state.metadata.get("project_action_reports")
            self.assertIsInstance(reports, dict)
            assert isinstance(reports, dict)
            project_reports = reports.get("feature-a-1")
            self.assertIsInstance(project_reports, dict)
            assert isinstance(project_reports, dict)
            migrate_entry = project_reports.get("migrate")
            self.assertIsInstance(migrate_entry, dict)
            assert isinstance(migrate_entry, dict)
            summary = str(migrate_entry.get("summary", ""))
            self.assertEqual(
                str(migrate_entry.get("headline", "")),
                "pydantic_core._pydantic_core.ValidationError: 2 validation errors for Settings",
            )
            self.assertTrue(
                summary.startswith("pydantic_core._pydantic_core.ValidationError: 2 validation errors for Settings")
            )
            self.assertIn("ValidationError", summary)
            self.assertIn("hint: envctl migrate loads backend env from backend/.env by default.", summary)
            self.assertIn("BACKEND_ENV_FILE_OVERRIDE", summary)
            self.assertIn("hint: backend env source: default", summary)
            backend_env_metadata = migrate_entry.get("backend_env")
            self.assertIsInstance(backend_env_metadata, dict)
            assert isinstance(backend_env_metadata, dict)
            self.assertEqual(backend_env_metadata.get("env_file_source"), "default")
            self.assertEqual(
                Path(str(backend_env_metadata.get("env_file_path", ""))).resolve(),
                (backend_dir / ".env").resolve(),
            )
            report_path = Path(str(migrate_entry.get("report_path", "")))
            self.assertTrue(report_path.is_file())
            report_text = report_path.read_text(encoding="utf-8")
            self.assertIn("DATABASE_URL", report_text)
            self.assertNotIn("hint: envctl migrate loads backend env", report_text)

    def test_direct_cli_migrate_failure_prints_compact_summary_instead_of_raw_wall(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            backend_dir = target / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend_dir / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            (backend_dir / ".env").write_text("CUSTOM_BACKEND_FLAG=enabled\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_UI_HYPERLINK_MODE": "on", "ENVCTL_UI_COLOR_MODE": "on"},
            )
            self._save_state(
                engine,
                RunState(
                    run_id="run-migrate-cli-failure",
                    mode="trees",
                    services={
                        "feature-a-1 Backend": ServiceRecord(
                            name="feature-a-1 Backend",
                            type="backend",
                            cwd=str(backend_dir),
                            pid=1001,
                            requested_port=8000,
                            actual_port=8000,
                            status="running",
                        )
                    },
                ),
            )
            engine.process_runner = _FakeRunner(  # type: ignore[assignment]
                returncode=1,
                stderr=(
                    "Traceback (most recent call last):\n"
                    '  File "/tmp/project/backend/alembic/env.py", line 19, in <module>\n'
                    "    from app.core.config import settings\n"
                    "alembic.util.exc.CommandError: migration failed\n"
                    "details: revision mismatch\n"
                ),
            )

            route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})

            out = _TtyStringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            rendered = out.getvalue()
            visible = strip_ansi(rendered)
            self.assertIn("✗ migrate failed for feature-a-1: alembic.util.exc.CommandError: migration failed", visible)
            self.assertIn("migrate failure log for feature-a-1:", visible)
            self.assertIn("\x1b]8;;file://", rendered)
            self.assertNotIn("migrate action failed for feature-a-1:", visible)
            self.assertNotIn("✗ migrate failed for feature-a-1: Traceback (most recent call last):", visible)
            self.assertNotIn("Traceback (most recent call last):", visible.splitlines()[0])

    def test_direct_cli_migrate_mixed_results_prints_successes_and_failures_in_route_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            backend_a = tree_a / "backend"
            backend_b = tree_b / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (backend_a / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend_b / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend_a / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            (backend_b / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            (backend_a / ".env").write_text("CUSTOM_BACKEND_FLAG=a\n", encoding="utf-8")
            (backend_b / ".env").write_text("CUSTOM_BACKEND_FLAG=b\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_UI_HYPERLINK_MODE": "on", "ENVCTL_UI_COLOR_MODE": "on"},
            )
            self._save_state(
                engine,
                RunState(
                    run_id="run-migrate-cli-mixed",
                    mode="trees",
                    services={
                        "feature-a-1 Backend": ServiceRecord(
                            name="feature-a-1 Backend",
                            type="backend",
                            cwd=str(backend_a),
                            pid=1001,
                            requested_port=8000,
                            actual_port=8000,
                            status="running",
                        ),
                        "feature-b-1 Backend": ServiceRecord(
                            name="feature-b-1 Backend",
                            type="backend",
                            cwd=str(backend_b),
                            pid=1002,
                            requested_port=8001,
                            actual_port=8001,
                            status="running",
                        ),
                    },
                ),
            )

            class _SequencedRunner:
                def __init__(self) -> None:
                    self.calls = 0

                def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                    _ = cmd, cwd, env, timeout
                    self.calls += 1
                    if self.calls == 1:
                        return SimpleNamespace(returncode=0, stdout="", stderr="")
                    return SimpleNamespace(
                        returncode=1,
                        stdout="",
                        stderr=(
                            "Traceback (most recent call last):\n"
                            '  File "/tmp/project/backend/alembic/env.py", line 22, in <module>\n'
                            "alembic.util.exc.CommandError: feature-b failed\n"
                        ),
                    )

                def start(self, cmd, *, cwd=None, env=None):  # noqa: ANN001
                    _ = cmd, cwd, env
                    return SimpleNamespace(pid=10001, poll=lambda: None)

                def wait_for_port(self, _port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
                    _ = host, timeout
                    return True

                def is_pid_running(self, _pid: int) -> bool:
                    return False

            engine.process_runner = _SequencedRunner()  # type: ignore[assignment]

            route = parse_route(
                ["migrate", "--project", "feature-a-1", "--project", "feature-b-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )

            out = _TtyStringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            rendered = out.getvalue()
            self.assertIn("\x1b[1;32m✓\x1b[0m", rendered)
            self.assertIn("\x1b[1;31m✗\x1b[0m", rendered)
            self.assertIn("\x1b[1;34mfeature-a-1\x1b[0m", rendered)
            self.assertIn("\x1b[1;35mfeature-b-1\x1b[0m", rendered)
            visible = strip_ansi(rendered)
            self.assertLess(
                visible.index("✓ migrate succeeded for feature-a-1"),
                visible.index("✗ migrate failed for feature-b-1: alembic.util.exc.CommandError: feature-b failed"),
            )
            self.assertIn("migrate failure log for feature-b-1:", visible)
            self.assertNotIn("migrate action succeeded for feature-a-1.", visible)
            self.assertNotIn("migrate action failed for feature-b-1:", visible)

    def test_direct_cli_migrate_multiple_failures_compact_shared_hints_and_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            backend_a = tree_a / "backend"
            backend_b = tree_b / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (backend_a / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend_b / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend_a / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            (backend_b / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            (backend_a / ".env").write_text("CUSTOM_BACKEND_FLAG=a\n", encoding="utf-8")
            (backend_b / ".env").write_text("CUSTOM_BACKEND_FLAG=b\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"ENVCTL_UI_HYPERLINK_MODE": "on"})
            self._save_state(
                engine,
                RunState(
                    run_id="run-migrate-cli-failure-batch",
                    mode="trees",
                    services={
                        "feature-a-1 Backend": ServiceRecord(
                            name="feature-a-1 Backend",
                            type="backend",
                            cwd=str(backend_a),
                            pid=1001,
                            requested_port=8000,
                            actual_port=8000,
                            status="running",
                        ),
                        "feature-b-1 Backend": ServiceRecord(
                            name="feature-b-1 Backend",
                            type="backend",
                            cwd=str(backend_b),
                            pid=1002,
                            requested_port=8001,
                            actual_port=8001,
                            status="running",
                        ),
                    },
                ),
            )

            class _SequencedRunner:
                def __init__(self) -> None:
                    self.calls = 0

                def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                    _ = cmd, cwd, env, timeout
                    self.calls += 1
                    project = "feature-a" if self.calls == 1 else "feature-b"
                    return SimpleNamespace(
                        returncode=1,
                        stdout="",
                        stderr=(
                            "Traceback (most recent call last):\n"
                            f'  File "/tmp/project/{project}/backend/alembic/env.py", line 19, in <module>\n'
                            "    from app.core.config import settings\n"
                            "pydantic_core._pydantic_core.ValidationError: 2 validation errors for Settings\n"
                            "DATABASE_URL\n"
                            "  Field required [type=missing, input_value={}, input_type=dict]\n"
                            "REDIS_URL\n"
                            "  Field required [type=missing, input_value={}, input_type=dict]\n"
                        ),
                    )

                def start(self, cmd, *, cwd=None, env=None):  # noqa: ANN001
                    _ = cmd, cwd, env
                    return SimpleNamespace(pid=10001, poll=lambda: None)

                def wait_for_port(self, _port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
                    _ = host, timeout
                    return True

                def is_pid_running(self, _pid: int) -> bool:
                    return False

            engine.process_runner = _SequencedRunner()  # type: ignore[assignment]

            route = parse_route(
                ["migrate", "--project", "feature-a-1", "--project", "feature-b-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )

            out = _TtyStringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            saved_state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(saved_state)
            assert saved_state is not None
            reports = saved_state.metadata.get("project_action_reports")
            self.assertIsInstance(reports, dict)
            assert isinstance(reports, dict)
            project_a_reports = reports.get("feature-a-1")
            self.assertIsInstance(project_a_reports, dict)
            assert isinstance(project_a_reports, dict)
            project_b_reports = reports.get("feature-b-1")
            self.assertIsInstance(project_b_reports, dict)
            assert isinstance(project_b_reports, dict)
            migrate_a = project_a_reports.get("migrate")
            self.assertIsInstance(migrate_a, dict)
            assert isinstance(migrate_a, dict)
            migrate_b = project_b_reports.get("migrate")
            self.assertIsInstance(migrate_b, dict)
            assert isinstance(migrate_b, dict)
            report_a = Path(str(migrate_a.get("report_path", "")))
            report_b = Path(str(migrate_b.get("report_path", "")))
            visible = strip_ansi(out.getvalue())
            self.assertIn(
                "✗ migrate failed for feature-a-1: pydantic_core._pydantic_core.ValidationError: 2 validation errors for Settings",
                visible,
            )
            self.assertIn(
                "✗ migrate failed for feature-b-1: pydantic_core._pydantic_core.ValidationError: 2 validation errors for Settings",
                visible,
            )
            self.assertEqual(
                visible.count(
                    "hint: migrate failed before Alembic reached revisions because required env vars were missing (DATABASE_URL, REDIS_URL)."
                ),
                1,
            )
            self.assertNotIn("hint: backend env source:", visible)
            self.assertIn("migrate failure logs:", visible)
            self.assertIn(str(report_a.parent), visible)
            self.assertIn(f"- feature-a-1: {report_a.name}", visible)
            self.assertIn(f"- feature-b-1: {report_b.name}", visible)
            self.assertNotIn("migrate failure log for feature-a-1:", visible)
            self.assertNotIn("migrate failure log for feature-b-1:", visible)

    def test_direct_cli_migrate_all_success_prints_visible_result_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            backend_a = tree_a / "backend"
            backend_b = tree_b / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (backend_a / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend_b / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (backend_a / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            (backend_b / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            (backend_a / ".env").write_text("CUSTOM_BACKEND_FLAG=a\n", encoding="utf-8")
            (backend_b / ".env").write_text("CUSTOM_BACKEND_FLAG=b\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            self._save_state(
                engine,
                RunState(
                    run_id="run-migrate-cli-success",
                    mode="trees",
                    services={
                        "feature-a-1 Backend": ServiceRecord(
                            name="feature-a-1 Backend",
                            type="backend",
                            cwd=str(backend_a),
                            pid=1001,
                            requested_port=8000,
                            actual_port=8000,
                            status="running",
                        ),
                        "feature-b-1 Backend": ServiceRecord(
                            name="feature-b-1 Backend",
                            type="backend",
                            cwd=str(backend_b),
                            pid=1002,
                            requested_port=8001,
                            actual_port=8001,
                            status="running",
                        ),
                    },
                ),
            )
            engine.process_runner = _FakeRunner(returncode=0)  # type: ignore[assignment]

            route = parse_route(
                ["migrate", "--project", "feature-a-1", "--project", "feature-b-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("✓ migrate succeeded for feature-a-1", rendered)
            self.assertIn("✓ migrate succeeded for feature-b-1", rendered)
            self.assertNotIn("migrate action succeeded for feature-a-1.", rendered)

    def test_migrate_failure_summary_prefers_actionable_exception_headline(self) -> None:
        lines = action_migrate_support_module.project_action_failure_summary_lines(
            command_name="migrate",
            error_output="\n".join(
                [
                    "Traceback (most recent call last):",
                    '  File "/tmp/project/backend/alembic/env.py", line 19, in <module>',
                    "    from app.core.config import settings",
                    "alembic.util.exc.CommandError: migration failed",
                ]
            ),
        )

        self.assertEqual(lines[0], "alembic.util.exc.CommandError: migration failed")
        self.assertIn("Traceback (most recent call last):", lines[1:])

