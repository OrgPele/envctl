from __future__ import annotations

import json
import tempfile
import unittest
import importlib
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import sys
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
actions_test_module = importlib.import_module("envctl_engine.actions.actions_test")
action_test_support_module = importlib.import_module("envctl_engine.actions.action_test_support")
action_command_orchestrator_module = importlib.import_module("envctl_engine.actions.action_command_orchestrator")
command_router_module = importlib.import_module("envctl_engine.runtime.command_router")
config_module = importlib.import_module("envctl_engine.config")
engine_runtime_module = importlib.import_module("envctl_engine.runtime.engine_runtime")

default_test_command = actions_test_module.default_test_command
default_test_commands = actions_test_module.default_test_commands
_configured_or_default_test_spec = action_test_support_module._configured_or_default_test_spec
ActionCommandOrchestrator = action_command_orchestrator_module.ActionCommandOrchestrator
parse_route = command_router_module.parse_route
load_config = config_module.load_config
PythonEngineRuntime = engine_runtime_module.PythonEngineRuntime
RunState = engine_runtime_module.RunState
ServiceRecord = engine_runtime_module.ServiceRecord


class _FakeRunner:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.run_calls: list[tuple[tuple[str, ...], str]] = []
        self.run_envs: list[dict[str, str] | None] = []

    def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
        _ = env, timeout
        self.run_calls.append((tuple(cmd), str(cwd)))
        self.run_envs.append(dict(env) if isinstance(env, dict) else None)
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)

    def start(self, cmd, *, cwd=None, env=None):  # noqa: ANN001
        _ = cmd, cwd, env
        return SimpleNamespace(pid=10001, poll=lambda: None)

    def wait_for_port(self, _port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
        _ = host, timeout
        return True

    def is_pid_running(self, _pid: int) -> bool:
        return False


class ActionsParityTests(unittest.TestCase):
    def _config(self, repo: Path, runtime: Path):
        return load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(runtime),
                "ENVCTL_DEFAULT_MODE": "trees",
            }
        )

    def test_action_commands_execute_with_configured_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_ACTION_TEST_CMD": "sh -lc 'exit 0'",
                    "ENVCTL_ACTION_PR_CMD": "sh -lc 'exit 0'",
                    "ENVCTL_ACTION_COMMIT_CMD": "sh -lc 'exit 0'",
                    "ENVCTL_ACTION_ANALYZE_CMD": "sh -lc 'exit 0'",
                    "ENVCTL_ACTION_MIGRATE_CMD": "sh -lc 'exit 0'",
                },
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            commands = ("test", "pr", "commit", "review", "migrate")
            for command in commands:
                route = parse_route([command, "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)
                self.assertEqual(code, 0, msg=command)

            self.assertGreaterEqual(len(fake_runner.run_calls), len(commands))

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
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertNotIn("Executed test action", out.getvalue())
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            self.assertTrue(any("Executing configured test command" in message for message in status_messages))
            self.assertTrue(any("Test command finished" in message for message in status_messages))

    def test_interactive_root_unittest_action_prints_resolved_command_and_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)
            (tree_root / "tests").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(
                returncode=0,
                stdout="..\n----------------------------------------------------------------------\nRan 2 tests in 0.003s\n\nOK\n",
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

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("command: ", rendered)
            self.assertIn("-m unittest discover -s tests -t . -p test_*.py", rendered)
            self.assertIn(f"cwd: {tree_root.resolve()}", rendered)
            self.assertIn("2 passed, 0 failed, 0 skipped", rendered)
            self.assertIn("Repository tests (unittest)", rendered)

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
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 1)
            rendered = out.getvalue()
            self.assertNotIn("failure: ", rendered)
            self.assertIn("failure summary:", rendered)
            self.assertIn("ft_", rendered)

    def test_action_commands_require_explicit_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_TEST_CMD": "sh -lc 'exit 0'"},
            )

            code = engine.dispatch(parse_route(["test"], env={"ENVCTL_DEFAULT_MODE": "trees"}))
            self.assertEqual(code, 1)

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

    def test_action_commands_use_shell_compatible_missing_target_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            expected_messages = {
                "pr": "No PR target selected.",
                "commit": "No commit target selected.",
                "review": "No review target selected.",
                "migrate": "No migration target selected.",
            }
            for command, expected in expected_messages.items():
                with self.subTest(command=command):
                    out = StringIO()
                    with redirect_stdout(out):
                        code = engine.dispatch(parse_route([command], env={"ENVCTL_DEFAULT_MODE": "trees"}))
                    self.assertEqual(code, 1, msg=command)
                    self.assertIn(expected, out.getvalue(), msg=command)

    def test_headless_review_auto_selects_single_main_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_DEFAULT_MODE": "main",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={"ENVCTL_ACTION_ANALYZE_CMD": "sh -lc 'exit 0'"},
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["review", "--headless"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0, msg=out.getvalue())
            self.assertEqual(len(fake_runner.run_calls), 1, msg=fake_runner.run_calls)
            only_cmd, only_cwd = fake_runner.run_calls[0]
            self.assertEqual(only_cmd, ("sh", "-lc", "exit 0"))
            self.assertEqual(Path(only_cwd).resolve(), repo.resolve())

    def test_headless_review_streams_output_on_tty_without_reprinting_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_DEFAULT_MODE": "main",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={"ENVCTL_ACTION_ANALYZE_CMD": "sh -lc 'exit 0'"},
            )

            class _StreamingRunner:
                def __init__(self) -> None:
                    self.run_calls: list[tuple[tuple[str, ...], str]] = []
                    self.streaming_calls: list[tuple[tuple[str, ...], str]] = []

                def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                    _ = env, timeout
                    self.run_calls.append((tuple(cmd), str(cwd)))
                    return SimpleNamespace(returncode=0, stdout="SHOULD_NOT_BE_PRINTED\n", stderr="")

                def run_streaming(self, cmd, *, cwd=None, env=None, timeout=None, show_spinner=True, echo_output=True):  # noqa: ANN001
                    _ = env, timeout, show_spinner, echo_output
                    self.streaming_calls.append((tuple(cmd), str(cwd)))
                    print("\x1b[36mRICH_REVIEW_BLOCK\x1b[0m")
                    return SimpleNamespace(returncode=0, stdout="RICH_REVIEW_BLOCK\n", stderr="", args=list(cmd))

            fake_runner = _StreamingRunner()
            engine.process_runner = fake_runner  # type: ignore[assignment]

            out = StringIO()
            with (
                patch("envctl_engine.actions.action_command_orchestrator._stdout_is_live_terminal", return_value=True),
                redirect_stdout(out),
            ):
                code = engine.dispatch(parse_route(["review", "--headless"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            rendered = out.getvalue()
            self.assertEqual(code, 0, msg=rendered)
            self.assertEqual(fake_runner.run_calls, [])
            self.assertEqual(len(fake_runner.streaming_calls), 1, msg=fake_runner.streaming_calls)
            self.assertIn("RICH_REVIEW_BLOCK", rendered)
            self.assertEqual(rendered.count("RICH_REVIEW_BLOCK"), 1, msg=rendered)

    def test_action_env_marks_batch_routes_non_interactive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target_root = repo / "trees" / "feature-a" / "1"
            target_root.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(
                ["commit", "--project", "feature-a-1", "--batch"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            target = SimpleNamespace(name="feature-a-1", root=target_root)

            env = engine.action_command_orchestrator.action_env(
                "commit",
                [target],
                route=route,
                target=target,
                extra=None,
            )
            self.assertEqual(env.get("ENVCTL_ACTION_INTERACTIVE"), "0")

    def test_action_env_keeps_interactive_pr_routes_interactive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target_root = repo / "trees" / "feature-a" / "1"
            target_root.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(
                ["pr", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            route.flags = {**route.flags, "interactive_command": True, "batch": True, "pr_base": "main"}
            target = SimpleNamespace(name="feature-a-1", root=target_root)

            env = engine.action_command_orchestrator.action_env(
                "pr",
                [target],
                route=route,
                target=target,
                extra=engine.action_command_orchestrator.action_extra_env(route),
            )

            self.assertEqual(env.get("ENVCTL_ACTION_INTERACTIVE"), "1")
            self.assertEqual(env.get("ENVCTL_PR_BASE"), "main")

    def test_action_env_exposes_runtime_scoped_tree_diffs_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target_root = repo / "trees" / "feature-a" / "1"
            target_root.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(
                ["review", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            target = SimpleNamespace(name="feature-a-1", root=target_root)

            env = engine.action_command_orchestrator.action_env(
                "review",
                [target],
                route=route,
                target=target,
                extra=None,
            )

            expected_root = engine.state_repository.tree_diffs_dir_path(None)
            self.assertEqual(env.get("ENVCTL_ACTION_TREE_DIFFS_ROOT"), str(expected_root))
            self.assertEqual(env.get("ENVCTL_ACTION_RUNTIME_ROOT"), str(engine.state_repository.runtime_root))

    def test_action_explicit_main_mode_does_not_fallback_to_tree_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_DEFAULT_MODE": "main",
                    }
                ),
                env={"ENVCTL_ACTION_TEST_CMD": "sh -lc 'exit 0'"},
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(
                ["test", "--main", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "main"},
            )
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("No matching targets found", out.getvalue())
            self.assertEqual(fake_runner.run_calls, [])

    def test_action_implicit_main_mode_keeps_main_scope_when_main_candidate_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_DEFAULT_MODE": "main",
                    }
                ),
                env={"ENVCTL_ACTION_TEST_CMD": "sh -lc 'exit 0'"},
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(
                ["test", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "main"},
            )
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("No matching targets found", out.getvalue())
            self.assertEqual(fake_runner.run_calls, [])

    def test_git_actions_use_python_native_defaults_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (repo / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            target.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            for command in ("pr", "commit", "review"):
                route = parse_route([command, "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)
                self.assertEqual(code, 0, msg=command)

            self.assertTrue(
                all(call[0][0] == sys.executable for call in fake_runner.run_calls),
                msg=fake_runner.run_calls,
            )
            self.assertTrue(
                all(call[0][1:3] == ("-m", "envctl_engine.actions.actions_cli") for call in fake_runner.run_calls),
                msg=fake_runner.run_calls,
            )

    def test_interactive_review_prints_action_output_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_ANALYZE_CMD": "sh -lc 'echo Review summary written: /tmp/review.md'"},
            )
            fake_runner = _FakeRunner(returncode=0, stdout="Review summary written: /tmp/review.md\n")
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["review", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("Review summary written: /tmp/review.md", rendered)

    def test_interactive_review_prints_failure_details_and_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target.mkdir(parents=True, exist_ok=True)

            details = (
                "Review failed: feature-a-1\n"
                "  Output directory\n"
                "    /tmp/review-output\n"
                "  Details: analyzer could not resolve docs path\n"
            )
            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_ANALYZE_CMD": "sh -lc 'exit 1'"},
            )
            fake_runner = _FakeRunner(returncode=1, stderr=details)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["review", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            rendered = out.getvalue()
            self.assertIn("review action failed for feature-a-1: Review failed: feature-a-1", rendered)
            self.assertIn("Output directory", rendered)
            self.assertIn("/tmp/review-output", rendered)
            self.assertIn("analyzer could not resolve docs path", rendered)

    def test_interactive_pr_reports_existing_pr_status_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target.mkdir(parents=True, exist_ok=True)

            existing_line = "PR already exists: https://github.com/acme/supportopia/pull/42"
            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_ACTION_PR_CMD": "sh -lc 'echo PR already exists: https://github.com/acme/supportopia/pull/42'"
                },
            )
            fake_runner = _FakeRunner(returncode=0, stdout=f"{existing_line}\n")
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["pr", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}
            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn(existing_line, rendered)
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            self.assertTrue(any(existing_line in message for message in status_messages), msg=status_messages)

    def test_review_action_extra_env_maps_project_scoped_backend_service_to_backend_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(
                ["review", "--service", "Main Backend"],
                env={"ENVCTL_DEFAULT_MODE": "main"},
            )

            extra = engine.action_command_orchestrator.action_extra_env(route)
            self.assertEqual(extra.get("ENVCTL_ANALYZE_SCOPE"), "backend")

    def test_review_action_extra_env_forwards_explicit_review_base_only_when_supplied(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            explicit_route = parse_route(
                ["review", "--review-base", "release/2026.03"],
                env={"ENVCTL_DEFAULT_MODE": "main"},
            )
            explicit_extra = engine.action_command_orchestrator.action_extra_env(explicit_route)
            self.assertEqual(explicit_extra.get("ENVCTL_REVIEW_BASE"), "release/2026.03")

            implicit_route = parse_route(["review"], env={"ENVCTL_DEFAULT_MODE": "main"})
            implicit_extra = engine.action_command_orchestrator.action_extra_env(implicit_route)
            self.assertNotIn("ENVCTL_REVIEW_BASE", implicit_extra)

    def test_git_actions_fallback_to_system_python_when_repo_has_no_venv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            for command in ("pr", "commit", "review"):
                route = parse_route([command, "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)
                self.assertEqual(code, 0, msg=command)

            self.assertTrue(
                all(call[0][0] == sys.executable for call in fake_runner.run_calls),
                msg=fake_runner.run_calls,
            )

    def test_git_actions_fallback_to_runtime_python_when_path_lookup_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["pr", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(fake_runner.run_calls)
            self.assertEqual(fake_runner.run_calls[0][0][0], sys.executable)

    def test_migrate_action_uses_local_dot_venv_python_when_backend_venv_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (target / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (target / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            target.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(fake_runner.run_calls)
            command = fake_runner.run_calls[0][0]
            self.assertEqual(Path(command[0]).resolve(), (target / ".venv" / "bin" / "python").resolve())
            self.assertEqual(command[1:4], ("-m", "alembic", "upgrade"))

    def test_migrate_action_falls_back_to_system_python_when_local_venv_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            target.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with patch(
                "envctl_engine.actions.action_utils.shutil.which",
                side_effect=lambda name: "/usr/bin/python3" if name in {"python3.12", "python3", "python"} else None,
            ):
                route = parse_route(["migrate", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(fake_runner.run_calls)
            self.assertEqual(fake_runner.run_calls[0][0][:3], ("/usr/bin/python3", "-m", "alembic"))

    def test_action_env_includes_pythonpath_for_native_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            target = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
            (repo / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            target.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["pr", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)
            self.assertEqual(code, 0)

            self.assertTrue(fake_runner.run_envs)
            env = fake_runner.run_envs[0] or {}
            self.assertIn("PYTHONPATH", env)
            self.assertIn(str(PYTHON_ROOT), env["PYTHONPATH"])
            self.assertEqual(env.get("GIT_TERMINAL_PROMPT"), "0")
            self.assertEqual(env.get("GH_PROMPT_DISABLED"), "1")
            self.assertEqual(env.get("GCM_INTERACTIVE"), "Never")

    def test_test_action_writes_failed_tests_summary_and_persists_dashboard_metadata(self) -> None:
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
                run_id="run-tests-artifact",
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
                    "feature-a-1 Frontend": ServiceRecord(
                        name="feature-a-1 Frontend",
                        type="frontend",
                        cwd=str(tree_root),
                        pid=2222,
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
            )
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            class _FailingRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = None

                def run_tests(self, _command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    from envctl_engine.test_output.parser_base import TestResult

                    self.last_result = TestResult(
                        passed=10,
                        failed=1,
                        skipped=0,
                        total=11,
                        failed_tests=["backend/tests/test_auth.py::test_signup_regression"],
                        error_details={
                            "backend/tests/test_auth.py::test_signup_regression": (
                                "\x1b]22;default\x07"
                                "AssertionError: expected 201, got 500\n"
                                "\x1b[15;72H"
                                "\\x1b[48;2;39;39;39m \x1b[0m"
                            )
                        },
                    )
                    return SimpleNamespace(returncode=1, stdout="", stderr="suite failed")

            dispatch_out = StringIO()
            with (
                redirect_stdout(dispatch_out),
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _FailingRunner),
            ):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 1)

            refreshed = engine._try_load_existing_state(mode="trees", strict_mode_match=False)
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            summaries = refreshed.metadata.get("project_test_summaries")
            self.assertIsInstance(summaries, dict)
            assert isinstance(summaries, dict)
            project_entry = summaries.get("feature-a-1")
            self.assertIsInstance(project_entry, dict)
            assert isinstance(project_entry, dict)
            summary_path = project_entry.get("summary_path")
            short_summary_path = project_entry.get("short_summary_path")
            manifest_path = project_entry.get("manifest_path")
            self.assertIsInstance(summary_path, str)
            assert isinstance(summary_path, str)
            self.assertIsInstance(short_summary_path, str)
            assert isinstance(short_summary_path, str)
            self.assertIsInstance(manifest_path, str)
            assert isinstance(manifest_path, str)
            expected_root = engine.runtime_root / "runs" / state.run_id / "test-results"
            self.assertTrue(summary_path.endswith("failed_tests_summary.txt"))
            self.assertRegex(Path(short_summary_path).name, r"^ft_[0-9a-f]{10}\.txt$")
            self.assertTrue(manifest_path.endswith("failed_tests_manifest.json"))
            self.assertTrue(Path(summary_path).is_file())
            self.assertTrue(Path(short_summary_path).is_file())
            self.assertTrue(Path(manifest_path).is_file())
            self.assertTrue(Path(summary_path).is_relative_to(expected_root))
            self.assertTrue(Path(short_summary_path).is_relative_to(engine.runtime_root / "runs" / state.run_id))
            self.assertTrue(Path(manifest_path).is_relative_to(expected_root))
            summary_text = Path(summary_path).read_text(encoding="utf-8")
            self.assertEqual(summary_text, Path(short_summary_path).read_text(encoding="utf-8"))
            manifest_payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            self.assertIn("backend/tests/test_auth.py::test_signup_regression", summary_text)
            self.assertIn("AssertionError: expected 201, got 500", summary_text)
            self.assertNotIn("\x1b", summary_text)
            self.assertNotIn("\\x1b", summary_text)
            self.assertNotIn("48;2;39;39;39m", summary_text)
            self.assertEqual(
                manifest_payload["entries"][0]["failed_tests"],
                ["backend/tests/test_auth.py::test_signup_regression"],
            )
            self.assertEqual(project_entry.get("status"), "failed")
            self.assertEqual(
                project_entry.get("summary_excerpt"),
                [
                    "[Test command]",
                    "backend/tests/test_auth.py::test_signup_regression",
                    "AssertionError: expected 201, got 500",
                ],
            )
            results_root = refreshed.metadata.get("project_test_results_root")
            self.assertEqual(results_root, str(Path(summary_path).parent.parent))
            self.assertTrue(Path(str(results_root)).is_relative_to(expected_root))
            self.assertFalse((repo / "test-results").exists())
            dispatch_rendered = dispatch_out.getvalue()
            self.assertIn("failure summary:", dispatch_rendered)
            self.assertIn(short_summary_path, dispatch_rendered)
            self.assertNotIn("backend/tests/test_auth.py::test_signup_regression", dispatch_rendered)
            self.assertNotIn("AssertionError: expected 201, got 500", dispatch_rendered)

            dashboard_out = StringIO()
            with redirect_stdout(dashboard_out):
                engine._print_dashboard_snapshot(refreshed)
            rendered = dashboard_out.getvalue()
            self.assertIn("tests:", rendered)
            self.assertIn("backend/tests/test_auth.py::test_signup_regression", rendered)
            self.assertIn("AssertionError: expected 201, got 500", rendered)
            self.assertIn(short_summary_path, rendered)
            self.assertNotIn(summary_path, rendered)

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
                            "  File \"/tmp/project/conftest.py\", line 4, in <module>\n"
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

    def test_envctl_repo_test_bootstrap_creates_repo_local_venv_and_installs_dev_deps(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "python" / "envctl_engine").mkdir(parents=True, exist_ok=True)
            (repo / "python" / "envctl_engine" / "__init__.py").write_text('"""envctl"""\n', encoding="utf-8")
            (repo / "pyproject.toml").write_text(
                "\n".join(
                    [
                        "[project]",
                        'name = "envctl"',
                        'version = "0.0.0"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            commands: list[tuple[str, ...]] = []
            statuses: list[str] = []

            def fake_run(command, *, cwd=None, capture_output=None, text=None, check=None):  # noqa: ANN001
                _ = capture_output, text, check
                commands.append(tuple(str(part) for part in command))
                self.assertEqual(Path(str(cwd)).resolve(), repo.resolve())
                rendered = tuple(str(part) for part in command)
                if rendered[1:3] == ("-m", "venv"):
                    python_bin = repo / ".venv" / "bin" / "python"
                    python_bin.parent.mkdir(parents=True, exist_ok=True)
                    python_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                    python_bin.chmod(0o755)
                return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("envctl_engine.actions.actions_test.subprocess.run", side_effect=fake_run):
                actions_test_module.ensure_repo_local_test_prereqs(repo, emit_status=statuses.append)

            self.assertEqual(len(commands), 2)
            self.assertEqual(commands[0][1:3], ("-m", "venv"))
            self.assertEqual(Path(commands[0][3]).resolve(), (repo / ".venv").resolve())
            self.assertEqual(
                commands[1],
                (str((repo / ".venv" / "bin" / "python").resolve()), "-m", "pip", "install", "-e", ".[dev]"),
            )
            self.assertTrue(
                any("Creating repo-local .venv for envctl test actions" in message for message in statuses),
                msg=statuses,
            )
            self.assertTrue(
                any("Installing repo-local envctl test prerequisites" in message for message in statuses),
                msg=statuses,
            )

    def test_envctl_repo_test_bootstrap_skips_when_repo_local_python_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "python" / "envctl_engine").mkdir(parents=True, exist_ok=True)
            (repo / "python" / "envctl_engine" / "__init__.py").write_text('"""envctl"""\n', encoding="utf-8")
            (repo / "pyproject.toml").write_text(
                "\n".join(
                    [
                        "[project]",
                        'name = "envctl"',
                        'version = "0.0.0"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            python_bin = repo / ".venv" / "bin" / "python"
            python_bin.parent.mkdir(parents=True, exist_ok=True)
            python_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            python_bin.chmod(0o755)

            def fake_run(command, *, cwd=None, capture_output=None, text=None, check=None):  # noqa: ANN001
                _ = cwd, capture_output, text, check
                rendered = tuple(str(part) for part in command)
                if rendered == (
                    str(python_bin.resolve()),
                    "-c",
                    "import build, prompt_toolkit, psutil, pytest, rich, textual",
                ):
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                self.fail(f"Unexpected bootstrap command: {rendered}")

            with patch("envctl_engine.actions.actions_test.subprocess.run", side_effect=fake_run):
                actions_test_module.ensure_repo_local_test_prereqs(repo)

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

    def test_failed_test_manifest_filters_invalid_pytest_error_lines(self) -> None:
        parser = importlib.import_module("envctl_engine.test_output.parser_pytest").PytestOutputParser()
        parsed = parser.parse_output(
            "\n".join(
                [
                    "ERROR: file or directory not found: app.core.middleware:logging_helpers.py:113 Unhandled request error",
                    "ERROR backend/tests/unit/test_repositories/test_faq_repo.py::test_faq_repo - AssertionError: boom",
                    "========================= 1 error in 0.12s =========================",
                ]
            )
        )
        orchestrator = ActionCommandOrchestrator(SimpleNamespace())
        entries = orchestrator._collect_failed_test_manifest_entries(
            [
                {
                    "index": 0,
                    "project_name": "Main",
                    "suite": "backend_pytest",
                    "parsed": parsed,
                }
            ],
            project_name="Main",
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(
            entries[0]["failed_tests"],
            ["backend/tests/unit/test_repositories/test_faq_repo.py::test_faq_repo"],
        )

    def test_failed_only_backend_rerun_uses_saved_exact_test_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_python = repo / "backend" / ".venv" / "bin" / "python"
            backend_python.parent.mkdir(parents=True, exist_ok=True)
            backend_python.write_text("", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-failed-rerun",
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
            head, status_hash, status_lines = ActionCommandOrchestrator._git_state_components(repo)
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260312_100000" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-12T10:00:00+00:00",
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
                                    "backend/tests/test_auth.py::test_signup_regression",
                                    "backend/tests/test_users.py::test_profile",
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
                    self.last_result = TestResult(passed=2, failed=0, skipped=0, total=2)
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertTrue(captured_commands[0][0].endswith("/backend/.venv/bin/python"))
            self.assertEqual(
                captured_commands[0][1:],
                [
                    "-m",
                    "pytest",
                    "backend/tests/test_auth.py::test_signup_regression",
                    "backend/tests/test_users.py::test_profile",
                ],
            )

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
            head, status_hash, status_lines = ActionCommandOrchestrator._git_state_components(repo)
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

    def test_failed_only_frontend_rerun_uses_saved_failed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            frontend_dir = repo / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-failed-frontend",
                mode="main",
                services={
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo),
                        pid=2222,
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    )
                },
            )
            head, status_hash, status_lines = ActionCommandOrchestrator._git_state_components(repo)
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260312_101000" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-12T10:10:00+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": head,
                            "status_hash": status_hash,
                            "status_lines": status_lines,
                        },
                        "entries": [
                            {
                                "suite": "Frontend (package test)",
                                "source": "frontend_package_test",
                                "failed_tests": [
                                    "src/components/a.test.ts::renders",
                                    "src/components/b.test.ts::fails",
                                    "src/components/a.test.ts",
                                ],
                                "failed_files": [
                                    "src/components/a.test.ts",
                                    "src/components/b.test.ts",
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state.metadata["project_test_summaries"] = {
                "Main": {
                    "manifest_path": str(manifest_path),
                    "failed_tests": 3,
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
                    self.last_result = TestResult(passed=2, failed=0, skipped=0, total=2)
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner),
                patch("envctl_engine.actions.action_test_support.detect_package_manager", return_value="bun"),
            ):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(
                captured_commands[0],
                [
                    "bun",
                    "run",
                    "test",
                    "--",
                    "src/components/a.test.ts",
                    "src/components/b.test.ts",
                ],
            )

    def test_failed_only_frontend_rerun_derives_failed_files_from_legacy_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            frontend_dir = repo / "frontend"
            frontend_dir.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-failed-frontend-legacy",
                mode="main",
                services={
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo),
                        pid=2222,
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    )
                },
            )
            head, status_hash, status_lines = ActionCommandOrchestrator._git_state_components(repo)
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260312_101500" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-12T10:15:00+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": head,
                            "status_hash": status_hash,
                            "status_lines": status_lines,
                        },
                        "entries": [
                            {
                                "suite": "Frontend (package test)",
                                "source": "frontend_package_test",
                                "failed_tests": [
                                    "src/components/a.test.ts::renders",
                                    "src/components/b.test.ts::fails",
                                    "src/components/a.test.ts",
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            state.metadata["project_test_summaries"] = {
                "Main": {
                    "manifest_path": str(manifest_path),
                    "failed_tests": 3,
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
                    self.last_result = TestResult(passed=2, failed=0, skipped=0, total=2)
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner),
                patch("envctl_engine.actions.action_test_support.detect_package_manager", return_value="bun"),
            ):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(
                captured_commands[0],
                [
                    "bun",
                    "run",
                    "test",
                    "--",
                    "src/components/a.test.ts",
                    "src/components/b.test.ts",
                ],
            )

    def test_failed_only_frontend_rerun_normalizes_repo_relative_failed_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "src" / "components").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-failed-frontend-repo-relative",
                mode="main",
                services={
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo),
                        pid=2222,
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    )
                },
            )
            head, status_hash, status_lines = ActionCommandOrchestrator._git_state_components(repo)
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260313_031100" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-13T03:11:00+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": head,
                            "status_hash": status_hash,
                            "status_lines": status_lines,
                        },
                        "entries": [
                            {
                                "suite": "Frontend (package test)",
                                "source": "frontend_package_test",
                                "failed_tests": [
                                    "frontend/src/components/a.test.ts::renders",
                                    "frontend/src/components/b.test.ts::fails",
                                ],
                                "failed_files": [
                                    "frontend/src/components/a.test.ts",
                                    "frontend/src/components/b.test.ts",
                                ],
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
                    self.last_result = TestResult(passed=2, failed=0, skipped=0, total=2)
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner),
                patch("envctl_engine.actions.action_test_support.detect_package_manager", return_value="bun"),
            ):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(
                captured_commands[0],
                [
                    "bun",
                    "run",
                    "test",
                    "--",
                    "src/components/a.test.ts",
                    "src/components/b.test.ts",
                ],
            )

    def test_failed_only_rerun_allows_saved_manifest_from_different_git_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={"NO_COLOR": "1"})
            state = RunState(
                run_id="run-stale-failed",
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
            manifest_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260312_103000" / "Main"
            manifest_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = manifest_dir / "failed_tests_manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-12T10:30:00+00:00",
                        "project_name": "Main",
                        "project_root": str(repo),
                        "git_state": {
                            "head": "stale-head",
                            "status_hash": "stale-hash",
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

            with (
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner),
            ):
                code = engine.dispatch(parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(
                captured_commands[0][1:], ["-m", "pytest", "backend/tests/test_auth.py::test_signup_regression"]
            )

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
            head, status_hash, status_lines = ActionCommandOrchestrator._git_state_components(repo)
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
            head, status_hash, status_lines = ActionCommandOrchestrator._git_state_components(repo)
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

    def test_failed_only_summary_persistence_preserves_previous_manifest_after_extraction_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={"NO_COLOR": "1"})
            state = RunState(
                run_id="run-preserve-failed-only",
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
            head, status_hash, status_lines = ActionCommandOrchestrator._git_state_components(repo)
            previous_dir = engine.runtime_root / "runs" / state.run_id / "test-results" / "run_20260312_100000" / "Main"
            previous_dir.mkdir(parents=True, exist_ok=True)
            previous_manifest_path = previous_dir / "failed_tests_manifest.json"
            previous_manifest_path.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-03-12T10:00:00+00:00",
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
                                "failed_tests": ["backend/tests/test_auth.py::test_signup_regression"],
                                "failed_files": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            previous_summary_path = previous_dir / "failed_tests_summary.txt"
            previous_summary_path.write_text("previous summary", encoding="utf-8")
            previous_short_summary_path = engine.runtime_root / "runs" / state.run_id / "ft_preserved.txt"
            previous_short_summary_path.write_text("previous summary", encoding="utf-8")
            state.metadata["project_test_summaries"] = {
                "Main": {
                    "summary_path": str(previous_summary_path),
                    "short_summary_path": str(previous_short_summary_path),
                    "manifest_path": str(previous_manifest_path),
                    "failed_tests": 1,
                    "failed_manifest_entries": 1,
                    "status": "failed",
                }
            }
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            orchestrator = ActionCommandOrchestrator(engine)
            route = parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"})
            outcomes = [
                {
                    "index": 1,
                    "project_name": "Main",
                    "project_root": str(repo),
                    "suite": "backend_pytest",
                    "failed_only": True,
                    "returncode": 1,
                    "parsed": SimpleNamespace(failed_tests=[], error_details={}),
                    "failure_summary": "ERROR: file or directory not found: poisoned selector",
                }
            ]

            summaries = orchestrator._persist_test_summary_artifacts(
                route=route,
                targets=[SimpleNamespace(name="Main", root=str(repo))],
                outcomes=outcomes,
            )

            project_entry = summaries["Main"]
            self.assertEqual(project_entry["manifest_path"], str(previous_manifest_path))
            self.assertEqual(project_entry["short_summary_path"], str(previous_short_summary_path))
            self.assertTrue(bool(project_entry.get("preserved_after_failed_only_extraction_failure")))

    def test_failed_test_summary_omits_terminal_chrome_and_separator_noise(self) -> None:
        lines = ActionCommandOrchestrator._format_summary_error_lines(
            "\n".join(
                [
                    "----------------------------------------------------------------------",
                    "Traceback (most recent call last):",
                    'AssertionError: Regex didn\'t match: something not found in "\\x1b[48;2;39;39;39m..."',
                    "  ╭────────────────────────────────────────────────────╮",
                    "  │  Run tests for                                    │",
                    "RESULT_SERVICES=Main Admin",
                    'File "/tmp/test.py", line 10, in test_case',
                ]
            )
        )
        rendered = "\n".join(lines)
        self.assertIn("Traceback (most recent call last):", rendered)
        self.assertIn("AssertionError: Regex didn't match: something not found in <omitted output>", rendered)
        self.assertIn('File "/tmp/test.py", line 10, in test_case', rendered)
        self.assertNotIn("------", rendered)
        self.assertNotIn("Run tests for", rendered)
        self.assertNotIn("RESULT_SERVICES=", rendered)

    def test_failed_test_summary_keeps_relevant_traceback_tail(self) -> None:
        lines = ActionCommandOrchestrator._format_summary_error_lines(
            "\n".join(
                [
                    "Traceback (most recent call last):",
                    'File "/opt/homebrew/Cellar/python@3.12/.../asyncio/runners.py", line 118, in run',
                    "return self._loop.run_until_complete(task)",
                    'File "/opt/homebrew/Cellar/python@3.12/.../asyncio/base_events.py", line 691, in run_until_complete',
                    "return future.result()",
                    'File "/Users/kfiramar/projects/envctl/tests/python/ui/test_textual_selector_responsiveness.py", line 274, in test_mouse_click_selects_single_mode_without_enter',
                    'self.assertEqual(app.return_value, ["beta"])',
                    "AssertionError: None != ['beta']",
                ]
            )
        )
        rendered = "\n".join(lines)
        self.assertIn("Traceback (most recent call last):", rendered)
        self.assertIn('File "/opt/homebrew/Cellar/python@3.12/.../asyncio/runners.py", line 118, in run', rendered)
        self.assertIn(
            'File "/Users/kfiramar/projects/envctl/tests/python/ui/test_textual_selector_responsiveness.py", line 274, in test_mouse_click_selects_single_mode_without_enter',
            rendered,
        )
        self.assertIn('self.assertEqual(app.return_value, ["beta"])', rendered)
        self.assertIn("AssertionError: None != ['beta']", rendered)

    def test_failed_test_summary_keeps_captured_output_sections(self) -> None:
        lines = ActionCommandOrchestrator._format_summary_error_lines(
            "\n".join(
                [
                    "Traceback (most recent call last):",
                    'File "/Users/kfiramar/projects/envctl/tests/python/ui/test_textual_selector_responsiveness.py", line 274, in test_mouse_click_selects_single_mode_without_enter',
                    'self.assertEqual(app.return_value, ["beta"])',
                    "AssertionError: None != ['beta']",
                    "Captured stdout call",
                    "selector state before click: focused=selector-row-1",
                    "return_value=None",
                    "Captured stderr call",
                    "mouse event propagated",
                ]
            )
        )
        rendered = "\n".join(lines)
        self.assertIn("Captured stdout call", rendered)
        self.assertIn("selector state before click: focused=selector-row-1", rendered)
        self.assertIn("Captured stderr call", rendered)
        self.assertIn("mouse event propagated", rendered)

    def test_failed_test_summary_keeps_multiline_exception_body(self) -> None:
        lines = ActionCommandOrchestrator._format_summary_error_lines(
            "\n".join(
                [
                    "Traceback (most recent call last):",
                    'File "/Users/kfiramar/projects/envctl/python/foo.py", line 10, in explode',
                    "raise RuntimeError('bad state')",
                    "RuntimeError: invalid selector state",
                    "details: selected_row=None",
                    "details: expected token=beta",
                ]
            )
        )
        rendered = "\n".join(lines)
        self.assertIn("RuntimeError: invalid selector state", rendered)
        self.assertIn("details: selected_row=None", rendered)
        self.assertIn("details: expected token=beta", rendered)

    def test_failed_test_summary_keeps_multiple_user_frames_and_exception_context(self) -> None:
        lines = ActionCommandOrchestrator._format_summary_error_lines(
            "\n".join(
                [
                    "Traceback (most recent call last):",
                    'File "/Users/kfiramar/projects/envctl/python/envctl_engine/ui/foo.py", line 10, in helper',
                    "do_the_thing()",
                    'File "/Users/kfiramar/projects/envctl/tests/python/ui/test_textual_selector_responsiveness.py", line 274, in test_mouse_click_selects_single_mode_without_enter',
                    'self.assertEqual(app.return_value, ["beta"])',
                    "AssertionError: None != ['beta']",
                    "",
                    "During handling of the above exception, another exception occurred:",
                    "Traceback (most recent call last):",
                    'File "/Users/kfiramar/projects/envctl/python/envctl_engine/ui/bar.py", line 22, in wrapper',
                    "raise RuntimeError('wrapper failed')",
                    "RuntimeError: wrapper failed",
                ]
            )
        )
        rendered = "\n".join(lines)
        self.assertIn(
            'File "/Users/kfiramar/projects/envctl/python/envctl_engine/ui/foo.py", line 10, in helper', rendered
        )
        self.assertIn(
            'File "/Users/kfiramar/projects/envctl/tests/python/ui/test_textual_selector_responsiveness.py", line 274, in test_mouse_click_selects_single_mode_without_enter',
            rendered,
        )
        self.assertIn("During handling of the above exception, another exception occurred:", rendered)
        self.assertIn("RuntimeError: wrapper failed", rendered)

    def test_test_action_writes_passed_summary_with_no_failed_tests_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_TEST_CMD": "sh -lc 'exit 0'"},
            )

            state = RunState(
                run_id="run-tests-artifact-pass",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree_root),
                        pid=3333,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "feature-a-1 Frontend": ServiceRecord(
                        name="feature-a-1 Frontend",
                        type="frontend",
                        cwd=str(tree_root),
                        pid=4444,
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
            )
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            class _PassingRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = None

                def run_tests(self, _command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    from envctl_engine.test_output.parser_base import TestResult

                    self.last_result = TestResult(
                        passed=5,
                        failed=0,
                        skipped=1,
                        total=6,
                        failed_tests=[],
                        error_details={},
                    )
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PassingRunner):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            refreshed = engine._try_load_existing_state(mode="trees", strict_mode_match=False)
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            summaries = refreshed.metadata.get("project_test_summaries")
            self.assertIsInstance(summaries, dict)
            assert isinstance(summaries, dict)
            project_entry = summaries.get("feature-a-1")
            self.assertIsInstance(project_entry, dict)
            assert isinstance(project_entry, dict)
            summary_path = project_entry.get("summary_path")
            short_summary_path = project_entry.get("short_summary_path")
            self.assertIsInstance(summary_path, str)
            assert isinstance(summary_path, str)
            self.assertIsInstance(short_summary_path, str)
            assert isinstance(short_summary_path, str)
            expected_root = engine.runtime_root / "runs" / state.run_id / "test-results"
            self.assertTrue(Path(summary_path).is_relative_to(expected_root))
            self.assertTrue(Path(short_summary_path).is_relative_to(engine.runtime_root / "runs" / state.run_id))
            text = Path(summary_path).read_text(encoding="utf-8")
            self.assertIn("No failed tests.", text)
            self.assertEqual(text, Path(short_summary_path).read_text(encoding="utf-8"))
            self.assertEqual(project_entry.get("status"), "passed")
            self.assertEqual(
                refreshed.metadata.get("project_test_results_root"),
                str(Path(summary_path).parent.parent),
            )
            self.assertFalse((repo / "test-results").exists())

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

    def test_test_action_uses_python_native_fallback_when_repo_has_tests_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(
                any(
                    "-m" in call[0] and "envctl_engine.test_output.unittest_runner" in call[0] and "discover" in call[0]
                    for call in fake_runner.run_calls
                ),
                msg=fake_runner.run_calls,
            )

    def test_test_action_uses_backend_pytest_fallback_when_backend_tests_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(
                any(
                    call[0][:3] == ("/usr/bin/python3", "-m", "pytest")
                    and any(str(arg).endswith("/backend/tests") for arg in call[0])
                    for call in fake_runner.run_calls
                ),
                msg=fake_runner.run_calls,
            )

    def test_default_test_command_prefers_backend_pytest_over_root_unittest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            (repo / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "tests" / "test_placeholder.py").write_text(
                "import unittest\n\nclass Placeholder(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )

            with patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"):
                command = default_test_command(repo)

            self.assertEqual(command, ["/usr/bin/python3", "-m", "pytest", str(repo / "backend" / "tests")])

    def test_test_action_prefers_backend_pytest_when_both_root_and_backend_tests_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "tests" / "test_placeholder.py").write_text(
                "import unittest\n\nclass Placeholder(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(fake_runner.run_calls, msg="expected test command execution")
            command = fake_runner.run_calls[0][0]
            self.assertEqual(command[:3], ("/usr/bin/python3", "-m", "pytest"))
            self.assertIn("envctl_engine.test_output.pytest_progress_plugin", command)
            self.assertTrue(any(str(part).endswith("/backend/tests") for part in command), msg=command)

    def test_default_test_command_uses_package_manager_test_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            (repo / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            with patch(
                "envctl_engine.shared.node_tooling.shutil.which",
                side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
            ):
                command = default_test_command(repo)

            self.assertEqual(command, ["pnpm", "run", "test"])

    def test_default_test_commands_include_backend_and_frontend_for_mixed_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
            ):
                commands = default_test_commands(repo)

            self.assertEqual(len(commands), 2)
            self.assertEqual(commands[0].command, ["/usr/bin/python3", "-m", "pytest", str(repo / "backend" / "tests")])
            self.assertEqual(commands[0].cwd, repo)
            self.assertEqual(commands[1].command, ["pnpm", "run", "test"])
            self.assertEqual(commands[1].cwd, repo / "frontend")

    def test_default_test_commands_append_frontend_test_path_when_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            frontend = repo / "frontend"
            frontend.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (frontend / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            with patch(
                "envctl_engine.shared.node_tooling.shutil.which",
                side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
            ):
                commands = default_test_commands(repo, frontend_test_path="src")

            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0].command, ["pnpm", "run", "test", "--", "src"])
            self.assertEqual(commands[0].cwd, repo / "frontend")

    def test_default_test_commands_normalize_repo_relative_frontend_test_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            frontend = repo / "frontend"
            frontend.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (frontend / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            with patch(
                "envctl_engine.shared.node_tooling.shutil.which",
                side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
            ):
                commands = default_test_commands(repo, frontend_test_path="frontend/src")

            self.assertEqual(len(commands), 1)
            self.assertEqual(commands[0].command, ["pnpm", "run", "test", "--", "src"])
            self.assertEqual(commands[0].cwd, repo / "frontend")

    def test_test_action_runs_backend_and_frontend_for_mixed_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
            ):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(len(fake_runner.run_calls), 2, msg=fake_runner.run_calls)
            command_set = {call[0] for call in fake_runner.run_calls}
            cwd_set = {Path(call[1]).resolve() for call in fake_runner.run_calls}
            frontend_commands = [
                command for command in command_set if len(command) >= 3 and command[:3] == ("pnpm", "run", "test")
            ]
            self.assertEqual(len(frontend_commands), 1)
            self.assertEqual(frontend_commands[0][-3], "--")
            self.assertEqual(frontend_commands[0][-2], "--reporter=default")
            self.assertTrue(frontend_commands[0][-1].endswith("vitest_progress_reporter.mjs"))
            pytest_commands = [
                command
                for command in command_set
                if len(command) >= 4 and command[:3] == ("/usr/bin/python3", "-m", "pytest")
            ]
            self.assertEqual(len(pytest_commands), 1)
            self.assertIn("envctl_engine.test_output.pytest_progress_plugin", pytest_commands[0])
            self.assertTrue(any(str(part).endswith("/backend/tests") for part in pytest_commands[0]))
            self.assertIn(repo.resolve(), cwd_set)
            self.assertIn((repo / "frontend").resolve(), cwd_set)

    def test_test_action_appends_frontend_test_path_to_configured_frontend_test_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root = repo / "trees" / "feature-a" / "1"
            tree_root.mkdir(parents=True, exist_ok=True)
            (repo / ".envctl").write_text(
                "\n".join(
                    [
                        "ENVCTL_DEFAULT_MODE=trees",
                        "MAIN_BACKEND_ENABLE=false",
                        "MAIN_FRONTEND_ENABLE=true",
                        "TREES_BACKEND_ENABLE=false",
                        "TREES_FRONTEND_ENABLE=true",
                        "ENVCTL_FRONTEND_TEST_CMD=pnpm run test",
                        "ENVCTL_FRONTEND_TEST_PATH=src",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            frontend = tree_root / "frontend"
            src_dir = frontend / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (frontend / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(
                ["test", "--project", "feature-a-1", "backend=false", "frontend=true"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            with patch(
                "envctl_engine.runtime.engine_runtime_commands.shutil.which",
                side_effect=lambda name: f"/usr/bin/{name}",
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(fake_runner.run_calls)
            self.assertEqual(fake_runner.run_calls[0][0][:5], ("pnpm", "run", "test", "--", "src"))
            if len(fake_runner.run_calls[0][0]) > 5:
                self.assertEqual(fake_runner.run_calls[0][0][5], "--reporter=default")
                self.assertTrue(fake_runner.run_calls[0][0][6].startswith("--reporter="))

    def test_test_action_normalizes_repo_relative_frontend_test_path_for_configured_frontend_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".envctl").write_text(
                "\n".join(
                    [
                        "ENVCTL_DEFAULT_MODE=main",
                        "MAIN_BACKEND_ENABLE=false",
                        "MAIN_FRONTEND_ENABLE=true",
                        "TREES_BACKEND_ENABLE=false",
                        "TREES_FRONTEND_ENABLE=true",
                        "ENVCTL_FRONTEND_TEST_CMD=pnpm run test",
                        "ENVCTL_FRONTEND_TEST_PATH=frontend/src",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            frontend = repo / "frontend"
            (frontend / "src").mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (frontend / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(
                ["test", "backend=false", "frontend=true"],
                env={"ENVCTL_DEFAULT_MODE": "main"},
            )
            with patch(
                "envctl_engine.runtime.engine_runtime_commands.shutil.which",
                side_effect=lambda name: f"/usr/bin/{name}",
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertTrue(fake_runner.run_calls)
            self.assertEqual(fake_runner.run_calls[0][0][:5], ("pnpm", "run", "test", "--", "src"))
            if len(fake_runner.run_calls[0][0]) > 5:
                self.assertEqual(fake_runner.run_calls[0][0][5], "--reporter=default")
                self.assertTrue(fake_runner.run_calls[0][0][6].startswith("--reporter="))

    def test_test_action_uses_separate_backend_and_frontend_test_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root = repo / "trees" / "feature-a" / "1"
            tree_root.mkdir(parents=True, exist_ok=True)
            (repo / ".envctl").write_text(
                "\n".join(
                    [
                        "ENVCTL_DEFAULT_MODE=trees",
                        "MAIN_BACKEND_ENABLE=true",
                        "MAIN_FRONTEND_ENABLE=true",
                        "TREES_BACKEND_ENABLE=true",
                        "TREES_FRONTEND_ENABLE=true",
                        "ENVCTL_BACKEND_TEST_CMD=python -m pytest backend/tests",
                        "ENVCTL_FRONTEND_TEST_CMD=pnpm run test",
                        "ENVCTL_FRONTEND_TEST_PATH=src",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            frontend = tree_root / "frontend"
            (frontend / "src").mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (frontend / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
            with patch(
                "envctl_engine.runtime.engine_runtime_commands.shutil.which",
                side_effect=lambda name: f"/usr/bin/{name}",
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            commands = {call[0] for call in fake_runner.run_calls}
            backend_commands = [
                command for command in commands if len(command) >= 4 and command[:3] == ("python", "-m", "pytest")
            ]
            self.assertEqual(len(backend_commands), 1, msg=commands)
            self.assertIn("envctl_engine.test_output.pytest_progress_plugin", backend_commands[0])
            self.assertEqual(backend_commands[0][-1], "backend/tests")
            frontend_commands = [
                command
                for command in commands
                if len(command) >= 5 and command[:5] == ("pnpm", "run", "test", "--", "src")
            ]
            self.assertEqual(len(frontend_commands), 1, msg=commands)

    def test_configured_backend_and_frontend_test_commands_keep_runner_suite_labels(self) -> None:
        target = action_test_support_module.TestTargetContext(
            project_name="Main",
            project_root=Path("/tmp/repo"),
            target_obj=None,
        )

        backend_spec = _configured_or_default_test_spec(
            raw_command="python -m pytest backend/tests",
            target=target,
            repo_root=Path("/tmp/repo"),
            include_backend=True,
            include_frontend=False,
            frontend_test_path=None,
            split_command=lambda raw, _replacements: raw.split(),
            replacements_for_target=lambda _target: {},
        )
        frontend_spec = _configured_or_default_test_spec(
            raw_command="pnpm run test",
            target=target,
            repo_root=Path("/tmp/repo"),
            include_backend=False,
            include_frontend=True,
            frontend_test_path="src",
            split_command=lambda raw, _replacements: raw.split(),
            replacements_for_target=lambda _target: {},
        )

        self.assertIsNotNone(backend_spec)
        self.assertIsNotNone(frontend_spec)
        self.assertEqual(backend_spec.source, "backend_pytest")
        self.assertEqual(frontend_spec.source, "frontend_package_test")

    def test_shared_configured_root_unittest_command_keeps_repository_suite_label(self) -> None:
        target = action_test_support_module.TestTargetContext(
            project_name="Main",
            project_root=Path("/tmp/repo"),
            target_obj=None,
        )

        specs = action_test_support_module.build_test_execution_specs(
            repo_root=Path("/tmp/repo"),
            target_contexts=[target],
            shared_raw_command="python3.12 -m unittest discover -s tests -t . -p test_*.py",
            backend_raw_command=None,
            frontend_raw_command=None,
            include_backend=True,
            include_frontend=False,
            frontend_test_path=None,
            run_all=False,
            untested=False,
            split_command=lambda raw, _replacements: raw.split(),
            replacements_for_target=lambda _target: {},
            is_legacy_tree_test_script=lambda _cmd: False,
        )

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].spec.source, "root_unittest")
        self.assertEqual(specs[0].resolved_source, "root_unittest")

    def test_shared_configured_frontend_package_test_runs_from_frontend_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            frontend = repo / "frontend"
            frontend.mkdir(parents=True, exist_ok=True)
            (frontend / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )

            target = action_test_support_module.TestTargetContext(
                project_name="Main",
                project_root=repo,
                target_obj=None,
            )

            specs = action_test_support_module.build_test_execution_specs(
                repo_root=repo,
                target_contexts=[target],
                shared_raw_command="pnpm run test",
                backend_raw_command=None,
                frontend_raw_command=None,
                include_backend=False,
                include_frontend=True,
                frontend_test_path="src",
                run_all=False,
                untested=False,
                split_command=lambda raw, _replacements: raw.split(),
                replacements_for_target=lambda _target: {},
                is_legacy_tree_test_script=lambda _cmd: False,
            )

            self.assertEqual(len(specs), 1)
            self.assertEqual(specs[0].spec.command, ["pnpm", "run", "test", "--", "src"])
            self.assertEqual(specs[0].spec.cwd, frontend)
            self.assertEqual(specs[0].spec.source, "frontend_package_test")

    def test_test_action_uses_parallel_executor_for_mixed_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            executor_calls: dict[str, int] = {"workers": 0, "submitted": 0}

            class _ExecutorStub:
                def __init__(self, max_workers: int) -> None:
                    executor_calls["workers"] = max_workers

                def __enter__(self) -> "_ExecutorStub":
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                    _ = exc_type, exc, tb
                    return False

                def submit(self, fn, *args, **kwargs):  # noqa: ANN001
                    executor_calls["submitted"] += 1
                    from concurrent.futures import Future

                    future: Future[Any] = Future()
                    try:
                        future.set_result(fn(*args, **kwargs))
                    except Exception as exc:  # pragma: no cover - defensive
                        future.set_exception(exc)
                    return future

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.concurrent.futures.ThreadPoolExecutor",
                    side_effect=lambda max_workers: _ExecutorStub(max_workers),
                ),
            ):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(executor_calls["workers"], 2)
            self.assertEqual(executor_calls["submitted"], 2)
            plans = [event for event in engine.events if event.get("event") == "test.suite.plan"]
            self.assertTrue(plans)
            self.assertTrue(bool(plans[-1].get("parallel")))

    def test_test_action_fans_out_across_all_selected_tree_roots_in_parallel(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            for tree in (tree_a, tree_b):
                (tree / "backend" / "tests").mkdir(parents=True, exist_ok=True)
                (tree / "backend" / "pyproject.toml").write_text(
                    "[project]\nname='backend'\nversion='1.0.0'\n",
                    encoding="utf-8",
                )
                (tree / "frontend").mkdir(parents=True, exist_ok=True)
                (tree / "frontend" / "package.json").write_text(
                    '{"name":"frontend","scripts":{"test":"vitest run"}}',
                    encoding="utf-8",
                )
                (tree / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            executor_calls: dict[str, int] = {"workers": 0, "submitted": 0}

            class _ExecutorStub:
                def __init__(self, max_workers: int) -> None:
                    executor_calls["workers"] = max_workers

                def __enter__(self) -> "_ExecutorStub":
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                    _ = exc_type, exc, tb
                    return False

                def submit(self, fn, *args, **kwargs):  # noqa: ANN001
                    executor_calls["submitted"] += 1
                    from concurrent.futures import Future

                    future: Future[Any] = Future()
                    try:
                        future.set_result(fn(*args, **kwargs))
                    except Exception as exc:  # pragma: no cover - defensive
                        future.set_exception(exc)
                    return future

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.concurrent.futures.ThreadPoolExecutor",
                    side_effect=lambda max_workers: _ExecutorStub(max_workers),
                ),
            ):
                route = parse_route(["test", "--all"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(executor_calls["workers"], 4)
            self.assertEqual(executor_calls["submitted"], 4)
            self.assertEqual(len(fake_runner.run_calls), 4, msg=fake_runner.run_calls)

            cwd_set = {Path(call[1]).resolve() for call in fake_runner.run_calls}
            self.assertIn(tree_a.resolve(), cwd_set)
            self.assertIn((tree_a / "frontend").resolve(), cwd_set)
            self.assertIn(tree_b.resolve(), cwd_set)
            self.assertIn((tree_b / "frontend").resolve(), cwd_set)

            plans = [event for event in engine.events if event.get("event") == "test.suite.plan"]
            self.assertTrue(plans)
            self.assertEqual(int(plans[-1].get("total", 0)), 4)
            self.assertEqual(sorted(plans[-1].get("projects") or []), ["feature-a-1", "feature-b-1"])

    def test_test_action_parallel_max_flag_controls_worker_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            for tree in (tree_a, tree_b):
                (tree / "backend" / "tests").mkdir(parents=True, exist_ok=True)
                (tree / "backend" / "pyproject.toml").write_text(
                    "[project]\nname='backend'\nversion='1.0.0'\n",
                    encoding="utf-8",
                )
                (tree / "frontend").mkdir(parents=True, exist_ok=True)
                (tree / "frontend" / "package.json").write_text(
                    '{"name":"frontend","scripts":{"test":"vitest run"}}',
                    encoding="utf-8",
                )
                (tree / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            executor_calls: dict[str, int] = {"workers": 0, "submitted": 0}

            class _ExecutorStub:
                def __init__(self, max_workers: int) -> None:
                    executor_calls["workers"] = max_workers

                def __enter__(self) -> "_ExecutorStub":
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                    _ = exc_type, exc, tb
                    return False

                def submit(self, fn, *args, **kwargs):  # noqa: ANN001
                    executor_calls["submitted"] += 1
                    from concurrent.futures import Future

                    future: Future[Any] = Future()
                    try:
                        future.set_result(fn(*args, **kwargs))
                    except Exception as exc:  # pragma: no cover - defensive
                        future.set_exception(exc)
                    return future

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.concurrent.futures.ThreadPoolExecutor",
                    side_effect=lambda max_workers: _ExecutorStub(max_workers),
                ),
            ):
                route = parse_route(
                    ["test", "--all", "--test-parallel-max", "4"],
                    env={"ENVCTL_DEFAULT_MODE": "trees"},
                )
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(executor_calls["workers"], 4)
            self.assertEqual(executor_calls["submitted"], 4)

    def test_test_action_parallel_progress_status_reports_queued_and_running(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._rich_progress_available",
                    return_value=(False, "forced_unavailable"),
                ),
            ):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                route.flags = {**route.flags, "interactive_command": True, "batch": True}
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            self.assertTrue(
                any(
                    message.startswith("Tests progress: running ") and "queued " in message
                    for message in status_messages
                ),
                msg=status_messages,
            )
            self.assertTrue(
                any(" • running: " in message and " • done: " in message for message in status_messages),
                msg=status_messages,
            )

    def test_test_action_uses_suite_spinner_group_and_suppresses_single_line_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            class _Policy:
                enabled = True
                backend = "rich"
                style = "dots"
                mode = "auto"
                reason = ""
                min_ms = 0
                verbose_events = False

            suite_events: list[str] = []

            class _SuiteSpinnerStub:
                def __init__(self, **kwargs) -> None:  # noqa: ANN003
                    self.enabled = bool(kwargs.get("enabled", False))

                def __enter__(self):
                    suite_events.append("enter")
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                    _ = exc_type, exc, tb
                    suite_events.append("exit")
                    return False

                def mark_running(self, execution) -> None:  # noqa: ANN001
                    suite_events.append(f"running:{int(getattr(execution, 'index', 0))}")

                def mark_finished(self, execution, *, success: bool, duration_text: str, parsed: object | None) -> None:  # noqa: ANN001
                    _ = duration_text, parsed
                    marker = "ok" if success else "fail"
                    suite_events.append(f"done:{int(getattr(execution, 'index', 0))}:{marker}")

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.resolve_spinner_policy", return_value=_Policy()
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._rich_progress_available",
                    return_value=(True, ""),
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.sys.stderr",
                    new=SimpleNamespace(isatty=lambda: True),
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._TestSuiteSpinnerGroup",
                    side_effect=lambda **kwargs: _SuiteSpinnerStub(**kwargs),
                ),
            ):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                route.flags = {**route.flags, "interactive_command": True, "batch": True}
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertIn("enter", suite_events)
            self.assertIn("exit", suite_events)
            self.assertTrue(any(event.startswith("running:") for event in suite_events), msg=suite_events)
            self.assertTrue(any(event.startswith("done:") for event in suite_events), msg=suite_events)
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            self.assertFalse(
                any(message.startswith("Tests progress: running ") for message in status_messages), msg=status_messages
            )

    def test_parallel_suite_spinner_group_receives_live_progress_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            class _Policy:
                enabled = True
                backend = "rich"
                style = "dots"
                mode = "auto"
                reason = ""
                min_ms = 0
                verbose_events = False

            suite_events: list[str] = []

            class _SuiteSpinnerStub:
                def __init__(self, **kwargs) -> None:  # noqa: ANN003
                    self.enabled = bool(kwargs.get("enabled", False))

                def __enter__(self):
                    suite_events.append("enter")
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                    _ = exc_type, exc, tb
                    suite_events.append("exit")
                    return False

                def mark_running(self, execution) -> None:  # noqa: ANN001
                    suite_events.append(f"running:{int(getattr(execution, 'index', 0))}")

                def mark_progress(self, execution, *, status_text: str) -> None:  # noqa: ANN001
                    suite_events.append(f"progress:{int(getattr(execution, 'index', 0))}:{status_text}")

                def mark_finished(self, execution, *, success: bool, duration_text: str, parsed: object | None) -> None:  # noqa: ANN001
                    _ = duration_text, parsed
                    marker = "ok" if success else "fail"
                    suite_events.append(f"done:{int(getattr(execution, 'index', 0))}:{marker}")

            class _ProgressRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = SimpleNamespace(
                        counts_detected=True,
                        passed=0,
                        failed=0,
                        skipped=0,
                        errors=0,
                        total=0,
                    )

                def run_tests(self, command, *, cwd=None, env=None, timeout=None, progress_callback=None):  # noqa: ANN001
                    _ = cwd, env, timeout
                    rendered = " ".join(str(part) for part in command)
                    if "pytest" in rendered:
                        self.last_result = SimpleNamespace(
                            counts_detected=True,
                            passed=3,
                            failed=0,
                            skipped=0,
                            errors=0,
                            total=3,
                        )
                        if callable(progress_callback):
                            progress_callback(1, 3)
                            progress_callback(3, 3)
                    else:
                        self.last_result = SimpleNamespace(
                            counts_detected=True,
                            passed=5,
                            failed=1,
                            skipped=0,
                            errors=0,
                            total=6,
                            failed_tests=["src/foo.test.ts::bar"],
                        )
                        if callable(progress_callback):
                            progress_callback(-1, 6)
                            progress_callback(2, 0)
                            progress_callback(6, 6)
                    return SimpleNamespace(returncode=0, stdout="", stderr="")

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.resolve_spinner_policy", return_value=_Policy()
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._rich_progress_available",
                    return_value=(True, ""),
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._TestSuiteSpinnerGroup",
                    side_effect=lambda **kwargs: _SuiteSpinnerStub(**kwargs),
                ),
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _ProgressRunner),
            ):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                route.flags = {**route.flags, "interactive_command": True, "batch": True}
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertIn("enter", suite_events)
            self.assertIn("exit", suite_events)
            self.assertTrue(
                any(event == "progress:1:1/3 complete • 1 passed, 0 failed" for event in suite_events), msg=suite_events
            )
            self.assertTrue(
                any(event == "progress:1:3/3 complete • 3 passed, 0 failed" for event in suite_events), msg=suite_events
            )
            self.assertTrue(any(event == "progress:2:6 discovered" for event in suite_events), msg=suite_events)
            self.assertTrue(
                any(event == "progress:2:2 complete • 1 passed, 1 failed" for event in suite_events), msg=suite_events
            )
            self.assertTrue(
                any(event == "progress:2:6/6 complete • 5 passed, 1 failed" for event in suite_events), msg=suite_events
            )

    def test_interactive_single_suite_uses_rich_suite_spinner_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            class _Policy:
                enabled = True
                backend = "rich"
                style = "dots"
                mode = "auto"
                reason = ""
                min_ms = 0
                verbose_events = False

            suite_events: list[str] = []

            class _SuiteSpinnerStub:
                def __init__(self, **kwargs) -> None:  # noqa: ANN003
                    self.enabled = bool(kwargs.get("enabled", False))

                def __enter__(self):
                    suite_events.append("enter")
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                    _ = exc_type, exc, tb
                    suite_events.append("exit")
                    return False

                def mark_running(self, execution) -> None:  # noqa: ANN001
                    suite_events.append(f"running:{int(getattr(execution, 'index', 0))}")

                def mark_progress(self, execution, *, status_text: str) -> None:  # noqa: ANN001
                    suite_events.append(f"progress:{int(getattr(execution, 'index', 0))}:{status_text}")

                def mark_finished(self, execution, *, success: bool, duration_text: str, parsed: object | None) -> None:  # noqa: ANN001
                    _ = duration_text, parsed
                    marker = "ok" if success else "fail"
                    suite_events.append(f"done:{int(getattr(execution, 'index', 0))}:{marker}")

            with (
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.resolve_spinner_policy", return_value=_Policy()
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._rich_progress_available",
                    return_value=(True, ""),
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._TestSuiteSpinnerGroup",
                    side_effect=lambda **kwargs: _SuiteSpinnerStub(**kwargs),
                ),
            ):
                route = parse_route(
                    ["test", "--project", "feature-a-1", "backend=false"],
                    env={"ENVCTL_DEFAULT_MODE": "trees"},
                )
                route.flags = {**route.flags, "interactive_command": True, "batch": True}
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("Test execution mode: sequential (1 suites)", rendered)
            self.assertNotIn("Frontend (package test) started", rendered)
            self.assertNotIn("command: ", rendered)
            self.assertNotIn("cwd: ", rendered)
            self.assertIn("enter", suite_events)
            self.assertIn("exit", suite_events)
            self.assertTrue(any(event.startswith("running:") for event in suite_events), msg=suite_events)
            self.assertTrue(any(event.startswith("done:") for event in suite_events), msg=suite_events)

    def test_test_action_suite_spinner_group_overrides_non_tty_policy_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            class _Policy:
                enabled = False
                backend = "rich"
                style = "dots"
                mode = "auto"
                reason = "non_tty"
                min_ms = 0
                verbose_events = False

            suite_events: list[str] = []

            class _SuiteSpinnerStub:
                def __init__(self, **kwargs) -> None:  # noqa: ANN003
                    self.enabled = bool(kwargs.get("enabled", False))

                def __enter__(self):
                    suite_events.append("enter")
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                    _ = exc_type, exc, tb
                    suite_events.append("exit")
                    return False

                def mark_running(self, execution) -> None:  # noqa: ANN001
                    suite_events.append(f"running:{int(getattr(execution, 'index', 0))}")

                def mark_finished(self, execution, *, success: bool, duration_text: str, parsed: object | None) -> None:  # noqa: ANN001
                    _ = duration_text, parsed
                    marker = "ok" if success else "fail"
                    suite_events.append(f"done:{int(getattr(execution, 'index', 0))}:{marker}")

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.resolve_spinner_policy", return_value=_Policy()
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._rich_progress_available",
                    return_value=(True, ""),
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator._TestSuiteSpinnerGroup",
                    side_effect=lambda **kwargs: _SuiteSpinnerStub(**kwargs),
                ),
            ):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                route.flags = {**route.flags, "interactive_command": True, "batch": True}
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertIn("enter", suite_events)
            self.assertIn("exit", suite_events)
            self.assertTrue(any(event.startswith("running:") for event in suite_events), msg=suite_events)
            self.assertTrue(any(event.startswith("done:") for event in suite_events), msg=suite_events)
            policy_events = [
                event for event in engine.events if event.get("event") == "test.suite_spinner_group.policy"
            ]
            self.assertTrue(policy_events)
            self.assertTrue(bool(policy_events[-1].get("enabled")))

    def test_interactive_multi_project_test_output_is_grouped_by_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            for tree in (tree_a, tree_b):
                (tree / "backend" / "tests").mkdir(parents=True, exist_ok=True)
                (tree / "backend" / "pyproject.toml").write_text(
                    "[project]\nname='backend'\nversion='1.0.0'\n",
                    encoding="utf-8",
                )
                (tree / "frontend").mkdir(parents=True, exist_ok=True)
                (tree / "frontend" / "package.json").write_text(
                    '{"name":"frontend","scripts":{"test":"vitest run"}}',
                    encoding="utf-8",
                )
                (tree / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
            ):
                route = parse_route(["test", "--all"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                route.flags = {**route.flags, "interactive_command": True, "batch": True}
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("Test execution mode: parallel (4 suites across 2 projects)", rendered)
            self.assertNotIn("Selected test targets:", rendered)
            self.assertIn("feature-a-1", rendered)
            self.assertIn("feature-b-1", rendered)
            self.assertIn("Backend (pytest)", rendered)
            self.assertIn("Frontend (package test)", rendered)

    def test_test_action_sequential_flag_disables_parallel_executor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.concurrent.futures.ThreadPoolExecutor",
                    side_effect=AssertionError("ThreadPoolExecutor should not be used for --test-sequential"),
                ),
            ):
                route = parse_route(
                    ["test", "--project", "feature-a-1", "--test-sequential"],
                    env={"ENVCTL_DEFAULT_MODE": "trees"},
                )
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            plans = [event for event in engine.events if event.get("event") == "test.suite.plan"]
            self.assertTrue(plans)
            self.assertFalse(bool(plans[-1].get("parallel")))

    def test_test_action_parallel_flag_overrides_env_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"ENVCTL_ACTION_TEST_PARALLEL": "false"},
            )
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]
            executor_calls: dict[str, int] = {"workers": 0, "submitted": 0}

            class _ExecutorStub:
                def __init__(self, max_workers: int) -> None:
                    executor_calls["workers"] = max_workers

                def __enter__(self) -> "_ExecutorStub":
                    return self

                def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                    _ = exc_type, exc, tb
                    return False

                def submit(self, fn, *args, **kwargs):  # noqa: ANN001
                    executor_calls["submitted"] += 1
                    from concurrent.futures import Future

                    future: Future[Any] = Future()
                    try:
                        future.set_result(fn(*args, **kwargs))
                    except Exception as exc:  # pragma: no cover - defensive
                        future.set_exception(exc)
                    return future

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch(
                    "envctl_engine.actions.action_command_orchestrator.concurrent.futures.ThreadPoolExecutor",
                    side_effect=lambda max_workers: _ExecutorStub(max_workers),
                ),
            ):
                route = parse_route(
                    ["test", "--project", "feature-a-1", "--test-parallel"],
                    env={"ENVCTL_DEFAULT_MODE": "trees"},
                )
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(executor_calls["workers"], 2)
            self.assertEqual(executor_calls["submitted"], 2)
            plans = [event for event in engine.events if event.get("event") == "test.suite.plan"]
            self.assertTrue(plans)
            self.assertTrue(bool(plans[-1].get("parallel")))

    def test_test_action_interactive_reports_parallel_execution_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
            ):
                route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                route.flags = {**route.flags, "interactive_command": True, "batch": True}
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("Test execution mode: parallel (2 suites)", rendered)
            mode_events = [event for event in engine.events if event.get("event") == "test.execution.mode"]
            self.assertTrue(mode_events)
            self.assertEqual(mode_events[-1].get("mode"), "parallel")
            status_messages = [
                str(event.get("message", "")) for event in engine.events if event.get("event") == "ui.status"
            ]
            spinner_events = [
                event
                for event in engine.events
                if event.get("event") == "ui.spinner.lifecycle" and event.get("component") == "action.test.parallel"
            ]
            self.assertTrue(
                any(message.startswith("Tests progress: running ") for message in status_messages)
                or bool(spinner_events)
            )
            self.assertFalse(any("Running bun test script" in message for message in status_messages))
            if spinner_events:
                self.assertFalse(any("Running pytest suite" in message for message in status_messages))
                self.assertNotIn("Backend (pytest) started", rendered)
                self.assertNotIn("Frontend (package test) started", rendered)

    def test_failed_test_summary_artifacts_are_scoped_per_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            for tree in (tree_a, tree_b):
                (tree / "backend" / "tests").mkdir(parents=True, exist_ok=True)
                (tree / "backend" / "pyproject.toml").write_text(
                    "[project]\nname='backend'\nversion='1.0.0'\n",
                    encoding="utf-8",
                )

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"NO_COLOR": "1"})
            state = RunState(
                run_id="run-tests-artifact-multi",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(tree_a),
                        pid=1001,
                        requested_port=8001,
                        actual_port=8001,
                        status="running",
                    ),
                    "feature-b-1 Backend": ServiceRecord(
                        name="feature-b-1 Backend",
                        type="backend",
                        cwd=str(tree_b),
                        pid=1002,
                        requested_port=8002,
                        actual_port=8002,
                        status="running",
                    ),
                },
            )
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            class _PerProjectFailingRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = None

                def run_tests(self, _command, *, cwd=None, env=None, timeout=None):  # noqa: ANN001, ARG002
                    from envctl_engine.test_output.parser_base import TestResult

                    cwd_text = str(cwd or "")
                    marker = "feature-a-1" if "feature-a" in cwd_text else "feature-b-1"
                    self.last_result = TestResult(
                        passed=2,
                        failed=1,
                        skipped=0,
                        total=3,
                        failed_tests=[f"{marker}/backend/tests/test_auth.py::test_signup"],
                        error_details={
                            f"{marker}/backend/tests/test_auth.py::test_signup": f"AssertionError: {marker} failed"
                        },
                    )
                    return SimpleNamespace(returncode=1, stdout="", stderr=f"{marker} suite failed")

            with (
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _PerProjectFailingRunner),
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
            ):
                route = parse_route(["test", "--all", "frontend=false"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                rendered_out = StringIO()
                with redirect_stdout(rendered_out):
                    code = engine.dispatch(route)

            self.assertEqual(code, 1)
            refreshed = engine._try_load_existing_state(mode="trees", strict_mode_match=False)
            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            summaries = refreshed.metadata.get("project_test_summaries")
            self.assertIsInstance(summaries, dict)
            assert isinstance(summaries, dict)

            first = summaries.get("feature-a-1")
            second = summaries.get("feature-b-1")
            self.assertIsInstance(first, dict)
            self.assertIsInstance(second, dict)
            assert isinstance(first, dict)
            assert isinstance(second, dict)

            first_text = Path(str(first.get("summary_path"))).read_text(encoding="utf-8")
            second_text = Path(str(second.get("summary_path"))).read_text(encoding="utf-8")
            self.assertIn("feature-a-1/backend/tests/test_auth.py::test_signup", first_text)
            self.assertNotIn("feature-b-1/backend/tests/test_auth.py::test_signup", first_text)
            self.assertIn("feature-b-1/backend/tests/test_auth.py::test_signup", second_text)
            self.assertNotIn("feature-a-1/backend/tests/test_auth.py::test_signup", second_text)
            rendered = rendered_out.getvalue()
            first_short = str(first.get("short_summary_path"))
            second_short = str(second.get("short_summary_path"))
            self.assertIn("feature-a-1", rendered)
            self.assertIn(first_short, rendered)
            self.assertIn("feature-b-1", rendered)
            self.assertIn(second_short, rendered)

    def test_test_action_backend_false_runs_frontend_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
            ):
                route = parse_route(
                    ["test", "--project", "feature-a-1", "backend=false"],
                    env={"ENVCTL_DEFAULT_MODE": "trees"},
                )
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(len(fake_runner.run_calls), 1, msg=fake_runner.run_calls)
            only_cmd, only_cwd = fake_runner.run_calls[0]
            self.assertEqual(only_cmd[:3], ("pnpm", "run", "test"))
            self.assertEqual(only_cmd[-3], "--")
            self.assertEqual(only_cmd[-2], "--reporter=default")
            self.assertTrue(only_cmd[-1].endswith("vitest_progress_reporter.mjs"))
            self.assertEqual(Path(only_cwd).resolve(), (repo / "frontend").resolve())

    def test_test_action_frontend_false_runs_backend_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
            ):
                route = parse_route(
                    ["test", "--project", "feature-a-1", "frontend=false"],
                    env={"ENVCTL_DEFAULT_MODE": "trees"},
                )
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(len(fake_runner.run_calls), 1, msg=fake_runner.run_calls)
            only_cmd, only_cwd = fake_runner.run_calls[0]
            self.assertEqual(only_cmd[:3], ("/usr/bin/python3", "-m", "pytest"))
            self.assertIn("envctl_engine.test_output.pytest_progress_plugin", only_cmd)
            self.assertTrue(any(str(part).endswith("/backend/tests") for part in only_cmd))
            self.assertEqual(Path(only_cwd).resolve(), repo.resolve())

    def test_test_action_services_frontend_only_runs_frontend_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
            ):
                route = parse_route(
                    ["test", "--project", "feature-a-1"],
                    env={"ENVCTL_DEFAULT_MODE": "trees"},
                )
                route.flags = {**route.flags, "services": ["feature-a-1 Frontend"]}
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(len(fake_runner.run_calls), 1, msg=fake_runner.run_calls)
            only_cmd, only_cwd = fake_runner.run_calls[0]
            self.assertEqual(only_cmd[:3], ("pnpm", "run", "test"))
            self.assertEqual(only_cmd[-3], "--")
            self.assertEqual(only_cmd[-2], "--reporter=default")
            self.assertTrue(only_cmd[-1].endswith("vitest_progress_reporter.mjs"))
            self.assertEqual(Path(only_cwd).resolve(), (repo / "frontend").resolve())

    def test_test_action_disabling_all_suites_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "tests").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "pyproject.toml").write_text(
                "[project]\nname='backend'\nversion='1.0.0'\n",
                encoding="utf-8",
            )
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend" / "package.json").write_text(
                '{"name":"frontend","scripts":{"test":"vitest run"}}',
                encoding="utf-8",
            )
            (repo / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=0)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            route = parse_route(
                ["test", "--project", "feature-a-1", "backend=false", "frontend=false"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertEqual(fake_runner.run_calls, [])

    def test_delete_worktree_supports_project_selection_and_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a.mkdir(parents=True, exist_ok=True)
            tree_b.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            delete_one = parse_route(
                ["delete-worktree", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code_one = engine.dispatch(delete_one)
            self.assertEqual(code_one, 0)
            self.assertFalse(tree_a.exists())
            self.assertTrue(tree_b.exists())

            delete_all_without_yes = parse_route(
                ["delete-worktree", "--all"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code_guard = engine.dispatch(delete_all_without_yes)
            self.assertEqual(code_guard, 1)
            self.assertTrue(tree_b.exists())

            delete_all_with_yes = parse_route(
                ["delete-worktree", "--all", "--yes"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code_all = engine.dispatch(delete_all_with_yes)
            self.assertEqual(code_all, 0)
            self.assertFalse(tree_b.exists())

    def test_delete_worktree_supports_flat_trees_feature_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees-feature-a" / "1"
            tree_b = repo / "trees-feature-b" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a.mkdir(parents=True, exist_ok=True)
            tree_b.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            delete_one = parse_route(
                ["delete-worktree", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code_one = engine.dispatch(delete_one)

            self.assertEqual(code_one, 0)
            self.assertFalse(tree_a.exists())
            self.assertTrue(tree_b.exists())

    def test_delete_worktree_runs_blast_cleanup_before_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            cleanup_calls: list[tuple[str, Path, str]] = []

            def fake_blast_worktree_before_delete(*, project_name: str, project_root: Path, source_command: str):
                cleanup_calls.append((project_name, project_root, source_command))
                return []

            engine._blast_worktree_before_delete = fake_blast_worktree_before_delete  # type: ignore[assignment]
            route = parse_route(
                ["delete-worktree", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(cleanup_calls, [("feature-a-1", tree_a.resolve(), "delete-worktree")])
            self.assertFalse(tree_a.exists())

    def test_blast_worktree_alias_routes_to_delete_flow_with_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            cleanup_calls: list[tuple[str, Path, str]] = []

            def fake_blast_worktree_before_delete(*, project_name: str, project_root: Path, source_command: str):
                cleanup_calls.append((project_name, project_root, source_command))
                return []

            engine._blast_worktree_before_delete = fake_blast_worktree_before_delete  # type: ignore[assignment]
            route = parse_route(
                ["blast-worktree", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(cleanup_calls, [("feature-a-1", tree_a.resolve(), "blast-worktree")])
            self.assertFalse(tree_a.exists())

    def test_delete_worktree_dry_run_skips_blast_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            cleanup_calls: list[tuple[str, Path, str]] = []

            def fake_blast_worktree_before_delete(*, project_name: str, project_root: Path, source_command: str):
                cleanup_calls.append((project_name, project_root, source_command))
                return []

            engine._blast_worktree_before_delete = fake_blast_worktree_before_delete  # type: ignore[assignment]
            route = parse_route(
                ["delete-worktree", "--project", "feature-a-1", "--dry-run"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(cleanup_calls, [])
            self.assertTrue(tree_a.exists())


if __name__ == "__main__":
    unittest.main()
