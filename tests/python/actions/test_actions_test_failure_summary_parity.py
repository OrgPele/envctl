from __future__ import annotations

import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.actions.action_test_runner import _outcome_int
from tests.python.actions.actions_parity_test_support import (
    PythonEngineRuntime,
    RunState,
    ServiceRecord,
    _ActionsParityTestCase,
    _FakeRunner,
    _TtyStringIO,
    engine_runtime_module,
    parse_route,
    strip_ansi,
)


class ActionsTestFailureSummaryParityTests(_ActionsParityTestCase):
    def test_outcome_int_preserves_valid_values_and_defaults_malformed_values(self) -> None:
        self.assertEqual(_outcome_int(2), 2)
        self.assertEqual(_outcome_int("3"), 3)
        self.assertEqual(_outcome_int(None), 0)
        self.assertEqual(_outcome_int("not-a-number", default=9), 9)
        self.assertEqual(_outcome_int(object(), default=4), 4)

    def test_interactive_test_action_omits_inline_failure_excerpt_when_summary_artifact_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)
            (tree_root / "tests").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(
                returncode=1,
                stdout="E\nFAILED (errors=1)\n",
                stderr="ImportError: cannot import name 'x' from 'y'\n",
            )
            engine.process_runner = fake_runner  # type: ignore[assignment]
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree_root),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )
            state = RunState(
                run_id="run-interactive-failure-summary",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree_root),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )
            route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}

            with patch(
                "envctl_engine.actions.action_command_orchestrator._rich_progress_available",
                return_value=(False, "forced_unavailable"),
            ):
                out = _TtyStringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 1)
            rendered = out.getvalue()
            visible = strip_ansi(rendered)
            self.assertNotIn("failure: ", visible)
            self.assertIn("failure summary:", visible)
            self.assertIn("ft_", visible)
            self.assertIn("\x1b]8;;file://", rendered)
            self.assertNotIn("Test command failed:", rendered)
            self.assertNotIn("ImportError: cannot import name 'x' from 'y'", rendered)
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            self.assertFalse(
                any(message.startswith("Test command failed:") for message in status_messages),
                msg=status_messages,
            )
            self.assertFalse(
                any("ImportError: cannot import name 'x' from 'y'" in message for message in status_messages),
                msg=status_messages,
            )

    def test_interactive_test_action_keeps_inline_failure_status_when_no_summary_artifact_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)
            (tree_root / "tests").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(
                returncode=1,
                stdout="E\nFAILED (errors=1)\n",
                stderr="ImportError: cannot import name 'x' from 'y'\n",
            )
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}

            with patch(
                "envctl_engine.actions.action_command_orchestrator._rich_progress_available",
                return_value=(False, "forced_unavailable"),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertNotIn("failure summary:", out.getvalue())
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            self.assertTrue(
                any(message.startswith("Test command failed:") for message in status_messages),
                msg=status_messages,
            )
            self.assertTrue(
                any("ImportError: cannot import name 'x' from 'y'" in message for message in status_messages),
                msg=status_messages,
            )

    def test_test_action_writes_generic_suite_failure_summary_with_combined_cleaned_streams(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_TEST_CMD": "sh -lc 'exit 1'", "NO_COLOR": "1"},
            )
            engine.process_runner = _FakeRunner(returncode=1)  # type: ignore[assignment]

            state = RunState(
                run_id="run-generic-failure-summary",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree_root),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            class _GenericFailureRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    from envctl_engine.test_output.parser_base import TestResult

                    self.last_result = TestResult()

                def run_tests(self, _command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    return SimpleNamespace(
                        returncode=1,
                        stdout=(
                            "Collecting tests...\n"
                            "RuntimeConfigError: frontend env is missing API_URL\n"
                            "stdout unique detail\n"
                        ),
                        stderr=(
                            "\x1b[31mImportError: cannot import name 'settings' from 'app.config'\x1b[0m\n"
                            "stderr unique detail\n"
                        ),
                    )

            dispatch_out = StringIO()
            with (
                redirect_stdout(dispatch_out),
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _GenericFailureRunner),
            ):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                route.flags = {**route.flags, "interactive_command": True, "batch": True}
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            refreshed = engine._try_load_existing_state(mode="trees", strict_mode_match=False)
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            entry = refreshed.metadata["project_test_summaries"]["feature-a-1"]
            assert isinstance(entry, dict)
            summary_path = Path(str(entry["summary_path"]))
            short_summary_path = Path(str(entry["short_summary_path"]))
            summary_text = summary_path.read_text(encoding="utf-8")

            self.assertEqual(summary_text, short_summary_path.read_text(encoding="utf-8"))
            self.assertIn("- suite failed before envctl could extract failed tests", summary_text)
            self.assertIn("stderr:", summary_text)
            self.assertIn("stdout:", summary_text)
            self.assertIn("ImportError: cannot import name 'settings' from 'app.config'", summary_text)
            self.assertIn("stderr unique detail", summary_text)
            self.assertIn("RuntimeConfigError: frontend env is missing API_URL", summary_text)
            self.assertIn("stdout unique detail", summary_text)
            self.assertNotIn("\x1b", summary_text)
            self.assertIn("failure summary:", dispatch_out.getvalue())
            self.assertNotIn("failure: ", dispatch_out.getvalue())

    def test_test_action_writes_generic_suite_failure_summary_for_stderr_only_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_TEST_CMD": "sh -lc 'exit 1'", "NO_COLOR": "1"},
            )
            engine.process_runner = _FakeRunner(returncode=1)  # type: ignore[assignment]

            state = RunState(
                run_id="run-stderr-only-failure-summary",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree_root),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            class _StderrOnlyFailureRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    from envctl_engine.test_output.parser_base import TestResult

                    self.last_result = TestResult()

                def run_tests(self, _command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    return SimpleNamespace(
                        returncode=1,
                        stdout="",
                        stderr=(
                            "Traceback (most recent call last):\n"
                            '  File "/tmp/project/conftest.py", line 4, in <module>\n'
                            "ModuleNotFoundError: No module named 'missing_dependency'\n"
                        ),
                    )

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _StderrOnlyFailureRunner):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            refreshed = engine._try_load_existing_state(mode="trees", strict_mode_match=False)
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            entry = refreshed.metadata["project_test_summaries"]["feature-a-1"]
            assert isinstance(entry, dict)
            summary_text = Path(str(entry["summary_path"])).read_text(encoding="utf-8")

            self.assertIn("Traceback (most recent call last):", summary_text)
            self.assertIn("ModuleNotFoundError: No module named 'missing_dependency'", summary_text)
            self.assertNotIn("stdout:", summary_text)

    def test_test_action_summary_event_omits_fake_zero_counts_when_parsing_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_TEST_CMD": "sh -lc 'exit 1'", "NO_COLOR": "1"},
            )
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            state = RunState(
                run_id="run-tests-no-counts",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree_root),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                },
            )
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            class _UnparsedFailingRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = None

                def run_tests(self, _command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    from envctl_engine.test_output.parser_base import TestResult

                    self.last_result = TestResult()
                    return SimpleNamespace(returncode=1, stdout="", stderr="startup import error")

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _UnparsedFailingRunner):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            summary_events = [event for event in engine.events if event.get("event") == "test.suite.summary"]
            self.assertEqual(len(summary_events), 1)
            summary = summary_events[0]
            self.assertFalse(bool(summary.get("counts_detected")))
            self.assertIsNone(summary.get("passed"))
            self.assertIsNone(summary.get("failed"))
            self.assertIsNone(summary.get("skipped"))
            self.assertIsNone(summary.get("errors"))
            self.assertIsNone(summary.get("total_tests"))

    def test_test_action_skips_summary_artifacts_when_no_run_state_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            class _PassingRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = None

                def run_tests(self, _command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    from envctl_engine.test_output.parser_base import TestResult

                    self.last_result = TestResult(
                        passed=3,
                        failed=0,
                        skipped=0,
                        total=3,
                        failed_tests=[],
                        error_details={},
                    )
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertFalse((repo / "test-results").exists())
            self.assertFalse((engine.runtime_root / "runs").exists())
