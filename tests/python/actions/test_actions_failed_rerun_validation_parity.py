from __future__ import annotations

import sys
import json
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.python.actions.actions_parity_test_support import (
    PythonEngineRuntime,
    RunState,
    ServiceRecord,
    _ActionsParityTestCase,
    default_git_state_components,
    engine_runtime_module,
    parse_route,
)


class ActionsFailedRerunValidationParityTests(_ActionsParityTestCase):
    def test_failed_only_backend_rerun_skips_invalid_saved_pytest_selectors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_python = repo / "backend" / ".venv" / "bin" / "python"
            backend_python.parent.mkdir(parents=True, exist_ok=True)
            backend_python.write_text("", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"NO_COLOR": "1"})
            state = RunState(
                run_id="run-failed-rerun-invalid",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )
            head, status_hash, status_lines = default_git_state_components(repo)
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260312_100500" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-12T10:05:00+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": head,
                            "status_hash": status_hash,
                            "status_lines": status_lines,
                        },
                        "entries": [
                            {
                                "suite": "Backend (pytest)",
                                "source": "backend_pytest",
                                "failed_tests": [
                                    "app.core.middleware:logging_helpers.py:113 Unhandled request error",
                                    "backend/tests/test_auth.py::test_signup_regression",
                                ],
                                "failed_files": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state.metadata["project_test_summaries"] = {
                "Main": {
                    "manifest_path": str(manifest_path),
                    "failed_tests": 2,
                    "status": "failed",
                }
            }
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            captured_commands: list[list[str]] = []

            class _PassingRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = None

                def run_tests(self, command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    from envctl_engine.test_output.parser_base import TestResult

                    captured_commands.append(list(command))
                    self.last_result = TestResult(passed=1, failed=0, skipped=0, total=1)
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            out = StringIO()
            with (
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner),
                redirect_stdout(out),
            ):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(
                captured_commands[0][1:],
                ["-m", "pytest", "backend/tests/test_auth.py::test_signup_regression"],
            )
            self.assertIn("Skipping 1 invalid saved pytest selector for Main", out.getvalue())

    def test_failed_only_rerun_reports_extraction_failure_without_telling_user_to_rerun_full_suite(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={"NO_COLOR": "1"})
            state = RunState(
                run_id="run-extraction-failure",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata={},
            )
            head, status_hash, status_lines = default_git_state_components(repo)
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260312_103500" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-12T10:35:00+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": head,
                            "status_hash": status_hash,
                            "status_lines": status_lines,
                        },
                        "entries": [],
                    }
                ),
                encoding="utf-8",
            )
            summary_path = manifest_dir / "failed_tests_summary.txt"
            summary_path.write_text(
                "# envctl Failed Test Summary\n\n[Backend (pytest)]\n- suite failed before envctl could extract failed tests\n",
                encoding="utf-8",
            )
            state.metadata["project_test_summaries"] = {
                "Main": {
                    "manifest_path": str(manifest_path),
                    "summary_path": str(summary_path),
                    "failed_tests": 1,
                    "status": "failed",
                }
            }
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            rendered = out.getvalue()
            self.assertEqual(code, 1)
            self.assertIn("No rerunnable failed tests were extracted for: Main", rendered)
            self.assertIn(
                "The last full run failed before envctl could derive rerunnable test selectors. See the saved failure summary.",
                rendered,
            )
            self.assertNotIn("Run the full suite first.", rendered)

    def test_failed_only_rerun_rejects_custom_test_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"NO_COLOR": "1", "ENVCTL_ACTION_TEST_CMD": "pytest tests"},
            )
            state = RunState(
                run_id="run-custom-failed",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )
            head, status_hash, status_lines = default_git_state_components(repo)
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260312_104000" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-12T10:40:00+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": head,
                            "status_hash": status_hash,
                            "status_lines": status_lines,
                        },
                        "entries": [
                            {
                                "suite": "Test command",
                                "source": "configured",
                                "failed_tests": ["tests/test_thing.py::test_case"],
                                "failed_files": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state.metadata["project_test_summaries"] = {
                "Main": {
                    "manifest_path": str(manifest_path),
                    "failed_tests": 1,
                    "status": "failed",
                }
            }
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 1)
            self.assertIn(
                "Failed-only reruns are not supported for Main because the previous test run used a custom configured command.",
                out.getvalue(),
            )

    def test_failed_only_rerun_allows_configured_backend_pytest_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend = repo / "backend"
            (backend / "tests").mkdir(parents=True, exist_ok=True)
            (backend / "requirements.txt").write_text("", encoding="utf-8")
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "NO_COLOR": "1",
                    "ENVCTL_BACKEND_TEST_CMD": f"{sys.executable} -m pytest backend/tests",
                },
            )
            state = RunState(
                run_id="run-configured-backend-failed",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata={},
            )
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260312_103900" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-12T10:39:00+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": "any-head",
                            "status_hash": "any-hash",
                            "status_lines": 99,
                        },
                        "entries": [
                            {
                                "suite": "Backend (pytest)",
                                "source": "backend_pytest",
                                "failed_tests": ["backend/tests/test_auth.py::test_signup_regression"],
                                "failed_files": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state.metadata["project_test_summaries"] = {
                "Main": {
                    "manifest_path": str(manifest_path),
                    "failed_tests": 1,
                    "status": "failed",
                }
            }
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            captured_commands: list[list[str]] = []

            class _PassingRunner:
                def __init__(self, *args: object, **kwargs: object) -> None:
                    self.last_result = None

                def run_tests(self, command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    captured_commands.append(list(command))
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(
                captured_commands[0][1:], ["-m", "pytest", "backend/tests/test_auth.py::test_signup_regression"]
            )

    def test_failed_only_rerun_allows_configured_shared_unittest_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tests_pkg = repo / "tests" / "python" / "config"
            tests_pkg.mkdir(parents=True, exist_ok=True)
            (repo / "tests" / "__init__.py").write_text("", encoding="utf-8")
            (repo / "tests" / "python" / "__init__.py").write_text("", encoding="utf-8")
            (tests_pkg / "__init__.py").write_text("", encoding="utf-8")
            (tests_pkg / "test_config_persistence.py").write_text(
                "\n".join(
                    [
                        "import unittest",
                        "",
                        "class ConfigPersistenceTests(unittest.TestCase):",
                        "    def test_reference_envctl_example_matches_current_defaults(self):",
                        "        self.assertTrue(True)",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "NO_COLOR": "1",
                    "ENVCTL_ACTION_TEST_CMD": f"{sys.executable} -m unittest discover -s tests -t . -p test_*.py",
                },
            )
            state = RunState(
                run_id="run-configured-shared-failed",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata={},
            )
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260312_103950" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-12T10:39:50+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": "any-head",
                            "status_hash": "any-hash",
                            "status_lines": 99,
                        },
                        "entries": [
                            {
                                "suite": "Repository tests (unittest)",
                                "source": "root_unittest",
                                "failed_tests": [
                                    "python.config.test_config_persistence.ConfigPersistenceTests.test_reference_envctl_example_matches_current_defaults"
                                ],
                                "failed_files": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state.metadata["project_test_summaries"] = {
                "Main": {
                    "manifest_path": str(manifest_path),
                    "failed_tests": 1,
                    "status": "failed",
                }
            }
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            captured_commands: list[list[str]] = []

            class _PassingRunner:
                def __init__(self, *args: object, **kwargs: object) -> None:
                    self.last_result = None

                def run_tests(self, command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    captured_commands.append(list(command))
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(
                captured_commands[0][1:],
                [
                    "-m",
                    "unittest",
                    "tests.python.config.test_config_persistence.ConfigPersistenceTests.test_reference_envctl_example_matches_current_defaults",
                ],
            )

    def test_failed_only_rerun_normalizes_unittest_display_labels_to_runnable_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tests_pkg = repo / "tests" / "python" / "config"
            tests_pkg.mkdir(parents=True, exist_ok=True)
            (repo / "tests" / "__init__.py").write_text("", encoding="utf-8")
            (repo / "tests" / "python" / "__init__.py").write_text("", encoding="utf-8")
            (tests_pkg / "__init__.py").write_text("", encoding="utf-8")
            (tests_pkg / "test_config_persistence.py").write_text(
                "\n".join(
                    [
                        "import unittest",
                        "",
                        "class ConfigPersistenceTests(unittest.TestCase):",
                        "    def test_reference_envctl_example_matches_current_defaults(self):",
                        "        self.assertTrue(True)",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "NO_COLOR": "1",
                    "ENVCTL_ACTION_TEST_CMD": f"{sys.executable} -m unittest discover -s tests -t . -p test_*.py",
                },
            )
            state = RunState(
                run_id="run-configured-shared-unittest-display-labels",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata={},
            )
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260313_034452" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-13T03:44:52+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": "any-head",
                            "status_hash": "any-hash",
                            "status_lines": 99,
                        },
                        "entries": [
                            {
                                "suite": "Repository tests (unittest)",
                                "source": "root_unittest",
                                "failed_tests": [
                                    "test_reference_envctl_example_matches_current_defaults (python.config.test_config_persistence.ConfigPersistenceTests.test_reference_envctl_example_matches_current_defaults)"
                                ],
                                "failed_files": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state.metadata["project_test_summaries"] = {
                "Main": {
                    "manifest_path": str(manifest_path),
                    "failed_tests": 1,
                    "status": "failed",
                }
            }
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            captured_commands: list[list[str]] = []

            class _PassingRunner:
                def __init__(self, *args: object, **kwargs: object) -> None:
                    self.last_result = None

                def run_tests(self, command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    captured_commands.append(list(command))
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(
                captured_commands[0][1:],
                [
                    "-m",
                    "unittest",
                    "tests.python.config.test_config_persistence.ConfigPersistenceTests.test_reference_envctl_example_matches_current_defaults",
                ],
            )

    def test_failed_only_rerun_repairs_root_unittest_ids_missing_tests_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tests_pkg = repo / "tests" / "python" / "actions"
            tests_pkg.mkdir(parents=True, exist_ok=True)
            (repo / "tests" / "__init__.py").write_text("", encoding="utf-8")
            (repo / "tests" / "python" / "__init__.py").write_text("", encoding="utf-8")
            (tests_pkg / "__init__.py").write_text("", encoding="utf-8")
            (tests_pkg / "test_actions_parity.py").write_text(
                "\n".join(
                    [
                        "import unittest",
                        "",
                        "class ActionsParityTests(unittest.TestCase):",
                        "    def test_test_action_uses_separate_backend_and_frontend_test_commands(self):",
                        "        self.assertTrue(True)",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "NO_COLOR": "1",
                    "ENVCTL_ACTION_TEST_CMD": f"{sys.executable} -m unittest discover -s tests -t . -p test_*.py",
                },
            )
            state = RunState(
                run_id="run-configured-shared-unittest-prefix-repair",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata={},
            )
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260313_140000" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-13T14:00:00+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": "any-head",
                            "status_hash": "any-hash",
                            "status_lines": 99,
                        },
                        "entries": [
                            {
                                "suite": "Repository tests (unittest)",
                                "source": "root_unittest",
                                "failed_tests": [
                                    "python.actions.test_actions_parity.ActionsParityTests.test_test_action_uses_separate_backend_and_frontend_test_commands"
                                ],
                                "failed_files": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state.metadata["project_test_summaries"] = {
                "Main": {
                    "manifest_path": str(manifest_path),
                    "failed_tests": 1,
                    "status": "failed",
                }
            }
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            captured_commands: list[list[str]] = []

            class _PassingRunner:
                def __init__(self, *args: object, **kwargs: object) -> None:
                    self.last_result = None

                def run_tests(self, command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    captured_commands.append(list(command))
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(
                captured_commands[0][1:],
                [
                    "-m",
                    "unittest",
                    "tests.python.actions.test_actions_parity.ActionsParityTests.test_test_action_uses_separate_backend_and_frontend_test_commands",
                ],
            )

    def test_failed_only_rerun_skips_root_unittest_ids_that_no_longer_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / "tests").mkdir(parents=True, exist_ok=True)
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "NO_COLOR": "1",
                    "ENVCTL_ACTION_TEST_CMD": f"{sys.executable} -m unittest discover -s tests -t . -p test_*.py",
                },
            )
            state = RunState(
                run_id="run-configured-shared-unittest-missing-test",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata={},
            )
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260313_142000" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-13T14:20:00+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": "any-head",
                            "status_hash": "any-hash",
                            "status_lines": 99,
                        },
                        "entries": [
                            {
                                "suite": "Repository tests (unittest)",
                                "source": "root_unittest",
                                "failed_tests": [
                                    "python.test_failed_rerun_probe.FailedRerunProbeTests.test_intentional_failure_for_failed_rerun"
                                ],
                                "failed_files": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state.metadata["project_test_summaries"] = {
                "Main": {
                    "manifest_path": str(manifest_path),
                    "failed_tests": 1,
                    "status": "failed",
                }
            }
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            class _FailIfCalledRunner:
                def __init__(self, *args: object, **kwargs: object) -> None:
                    raise AssertionError("TestRunner should not be constructed for non-rerunnable unittest ids")

            out = StringIO()
            with (
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _FailIfCalledRunner),
                redirect_stdout(out),
            ):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 1)
            self.assertIn("No rerunnable failed tests remain for: Main", out.getvalue())

    def test_failed_only_rerun_skips_root_unittest_ids_with_missing_test_method(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tests_pkg = repo / "tests" / "python" / "config"
            tests_pkg.mkdir(parents=True, exist_ok=True)
            (repo / "tests" / "__init__.py").write_text("", encoding="utf-8")
            (repo / "tests" / "python" / "__init__.py").write_text("", encoding="utf-8")
            (tests_pkg / "__init__.py").write_text("", encoding="utf-8")
            (tests_pkg / "test_config_loader.py").write_text(
                "\n".join(
                    [
                        "import unittest",
                        "",
                        "class ConfigLoaderTests(unittest.TestCase):",
                        "    def test_existing(self):",
                        "        self.assertTrue(True)",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "NO_COLOR": "1",
                    "ENVCTL_ACTION_TEST_CMD": f"{sys.executable} -m unittest discover -s tests -t . -p test_*.py",
                },
            )
            state = RunState(
                run_id="run-configured-shared-unittest-missing-method",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata={},
            )
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260313_143000" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-13T14:30:00+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": "any-head",
                            "status_hash": "any-hash",
                            "status_lines": 99,
                        },
                        "entries": [
                            {
                                "suite": "Repository tests (unittest)",
                                "source": "root_unittest",
                                "failed_tests": ["python.config.test_config_loader.ConfigLoaderTests.test_removed"],
                                "failed_files": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state.metadata["project_test_summaries"] = {
                "Main": {
                    "manifest_path": str(manifest_path),
                    "failed_tests": 1,
                    "status": "failed",
                }
            }
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            class _FailIfCalledRunner:
                def __init__(self, *args: object, **kwargs: object) -> None:
                    raise AssertionError("TestRunner should not be constructed for missing unittest methods")

            out = StringIO()
            with (
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _FailIfCalledRunner),
                redirect_stdout(out),
            ):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 1)
            self.assertIn("No rerunnable failed tests remain for: Main", out.getvalue())

