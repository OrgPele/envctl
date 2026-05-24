from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tests.python.actions.actions_parity_test_support import (
    PythonEngineRuntime,
    _ActionsParityTestCase,
    _FakeRunner,
    parse_route,
)


class ActionsTestParallelParityTests(_ActionsParityTestCase):
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

