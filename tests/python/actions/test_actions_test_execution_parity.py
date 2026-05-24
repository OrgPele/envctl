from __future__ import annotations

import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.python.actions.actions_parity_test_support import (
    PythonEngineRuntime,
    _ActionsParityTestCase,
    _FakeRunner,
    load_config,
    _TtyStringIO,
    parse_route,
)


class ActionsTestExecutionParityTests(_ActionsParityTestCase):
    def test_interactive_test_action_reports_status_without_stdout_summary_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_TEST_CMD": "sh -lc 'exit 0'"},
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}

            with patch(
                "envctl_engine.actions.action_command_orchestrator._rich_progress_available",
                return_value=(False, "forced_unavailable"),
            ):
                out = _TtyStringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertNotIn("Executed test action", out.getvalue())
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            self.assertTrue(any("Executing configured test command" in message for message in status_messages))
            self.assertTrue(any("Test command finished" in message for message in status_messages))

    def test_interactive_test_action_emits_live_progress_status_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)
            (tree_root / "tests").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            class _ProgressRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = SimpleNamespace(
                        counts_detected=True,
                        passed=3,
                        failed=0,
                        skipped=0,
                        errors=0,
                        total=3,
                    )

                def run_tests(self, command, *, cwd=None, env=None, timeout=None, progress_callback=None):  # noqa: ANN001
                    _ = command, cwd, env, timeout
                    if callable(progress_callback):
                        progress_callback(1, 3)
                        progress_callback(3, 3)
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _ProgressRunner):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 0)
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            self.assertTrue(
                any("1/3 tests complete • 1 passed, 0 failed" in message for message in status_messages),
                msg=status_messages,
            )
            self.assertTrue(
                any("3/3 tests complete • 3 passed, 0 failed" in message for message in status_messages),
                msg=status_messages,
            )

    def test_interactive_test_action_live_progress_counts_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)
            (tree_root / "tests").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            class _ProgressRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = SimpleNamespace(
                        counts_detected=True,
                        passed=1,
                        failed=1,
                        skipped=0,
                        errors=0,
                        total=2,
                        failed_tests=["tests/test_sample.py::test_two"],
                    )

                def run_tests(self, command, *, cwd=None, env=None, timeout=None, progress_callback=None):  # noqa: ANN001
                    _ = command, cwd, env, timeout
                    if callable(progress_callback):
                        progress_callback(2, 2)
                    return SimpleNamespace(returncode=1, stdout="", stderr="")

            route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _ProgressRunner):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 1)
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            self.assertTrue(
                any("2/2 tests complete • 1 passed, 1 failed" in message for message in status_messages),
                msg=status_messages,
            )

    def test_interactive_test_action_live_progress_shows_collection_and_no_total_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)
            (tree_root / "frontend").mkdir(parents=True, exist_ok=True)
            (tree_root / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            class _ProgressRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = SimpleNamespace(
                        counts_detected=True,
                        passed=12,
                        failed=0,
                        skipped=0,
                        errors=0,
                        total=20,
                    )

                def run_tests(self, command, *, cwd=None, env=None, timeout=None, progress_callback=None):  # noqa: ANN001
                    _ = command, cwd, env, timeout
                    if callable(progress_callback):
                        progress_callback(-1, 47)
                        progress_callback(5, 0)
                        progress_callback(12, 20)
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            route = parse_route(
                ["test", "--project", "feature-a-1", "backend=false"], env={"ENVCTL_DEFAULT_MODE": "trees"}
            )
            route.flags = {**route.flags, "interactive_command": True, "batch": True}

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _ProgressRunner):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 0)
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            self.assertTrue(
                any(
                    "Collecting Frontend (package test) tests... 47 discovered" in message
                    for message in status_messages
                )
            )
            self.assertTrue(
                any(
                    "Running Frontend (package test)... 5 tests complete • 5 passed, 0 failed" in message
                    for message in status_messages
                )
            )
            self.assertTrue(
                any(
                    "Running Frontend (package test)... 12/20 tests complete • 12 passed, 0 failed" in message
                    for message in status_messages
                )
            )

    def test_interactive_test_action_ignores_late_collection_updates_after_running_starts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)
            (tree_root / "frontend").mkdir(parents=True, exist_ok=True)
            (tree_root / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            class _ProgressRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = SimpleNamespace(
                        counts_detected=True,
                        passed=7,
                        failed=0,
                        skipped=0,
                        errors=0,
                        total=20,
                    )

                def run_tests(self, command, *, cwd=None, env=None, timeout=None, progress_callback=None):  # noqa: ANN001
                    _ = command, cwd, env, timeout
                    if callable(progress_callback):
                        progress_callback(-1, 47)
                        progress_callback(5, 0)
                        progress_callback(-1, 52)
                        progress_callback(0, 20)
                        progress_callback(7, 20)
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            route = parse_route(
                ["test", "--project", "feature-a-1", "backend=false"], env={"ENVCTL_DEFAULT_MODE": "trees"}
            )
            route.flags = {**route.flags, "interactive_command": True, "batch": True}

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _ProgressRunner):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 0)
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            collecting_messages = [
                message for message in status_messages if "Collecting Frontend (package test) tests..." in message
            ]
            self.assertEqual(len(collecting_messages), 1, msg=status_messages)
            self.assertFalse(any("52 discovered" in message for message in collecting_messages), msg=status_messages)
            self.assertTrue(
                any("Running Frontend (package test)... 5/20 tests complete" in message for message in status_messages),
                msg=status_messages,
            )
            self.assertTrue(
                any("Running Frontend (package test)... 7/20 tests complete" in message for message in status_messages),
                msg=status_messages,
            )

    def test_headless_test_auto_selects_single_main_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "tests").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_DEFAULT_MODE": "main",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            fake_runner = _FakeRunner(returncode=0, stdout="OK\n")
            engine.process_runner = fake_runner  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["test", "--headless"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0, msg=out.getvalue())
            self.assertEqual(len(fake_runner.run_calls), 1, msg=fake_runner.run_calls)
            only_cmd, only_cwd = fake_runner.run_calls[0]
            self.assertIn("-m", only_cmd)
            self.assertIn("envctl_engine.test_output.unittest_runner", only_cmd)
            self.assertEqual(Path(only_cwd).resolve(), repo.resolve())

    def test_headless_test_auto_selects_single_tree_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)
            (tree_root / "tests").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0, stdout="OK\n")
            engine.process_runner = fake_runner  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["test", "--headless"], env={"ENVCTL_DEFAULT_MODE": "trees"}))

            self.assertEqual(code, 0, msg=out.getvalue())
            self.assertEqual(len(fake_runner.run_calls), 1, msg=fake_runner.run_calls)
            only_cmd, only_cwd = fake_runner.run_calls[0]
            self.assertIn("-m", only_cmd)
            self.assertIn("envctl_engine.test_output.unittest_runner", only_cmd)
            self.assertEqual(Path(only_cwd).resolve(), tree_root.resolve())

