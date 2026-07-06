from __future__ import annotations

import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.python.actions.actions_parity_test_support import (
    PythonEngineRuntime,
    _ActionsParityTestCase,
    _FakeRunner,
    parse_route,
)


class ActionsTestParallelFlagsParityTests(_ActionsParityTestCase):
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
                    side_effect=AssertionError("ThreadPoolExecutor should not be used for --sequential"),
                ),
            ):
                route = parse_route(
                    ["test", "--project", "feature-a-1", "--sequential"],
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
                    ["test", "--project", "feature-a-1", "--parallel"],
                    env={"ENVCTL_DEFAULT_MODE": "trees"},
                )
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(executor_calls["workers"], 2)
            self.assertEqual(executor_calls["submitted"], 2)
            pytest_commands = [call[0] for call in fake_runner.run_calls if "-m" in call[0] and "pytest" in call[0]]
            self.assertEqual(len(pytest_commands), 1)
            self.assertNotIn("-n", pytest_commands[0])
            plans = [event for event in engine.events if event.get("event") == "test.suite.plan"]
            self.assertTrue(plans)
            self.assertTrue(bool(plans[-1].get("parallel")))

    def test_test_action_interactive_reports_parallel_execution_mode_by_default(self) -> None:
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
            self.assertFalse(any("Running bun test script" in message for message in status_messages))
