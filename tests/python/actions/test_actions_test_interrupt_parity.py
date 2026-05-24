from __future__ import annotations

import subprocess
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.python.actions.actions_parity_test_support import (
    PythonEngineRuntime,
    RunState,
    _ActionsParityTestCase,
    engine_runtime_module,
    parse_route,
)


class ActionsTestInterruptParityTests(_ActionsParityTestCase):
    def test_test_action_interrupt_terminates_started_sequential_suite_and_skips_summary_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)
            (tree_root / "tests").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            terminated_pids: list[int] = []
            engine.process_runner = SimpleNamespace(  # type: ignore[assignment]
                terminate_process_group=lambda pid, **_kwargs: terminated_pids.append(pid) or True,
            )
            state = RunState(run_id="run-test-interrupt-sequential", mode="trees", services={})
            engine.state_repository.save_resume_state(
                state=state,
                emit=engine._emit,
                runtime_map_builder=engine_runtime_module.build_runtime_map,
            )

            class _InterruptingRunner:
                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = None

                def run_tests(
                    self,
                    command,
                    *,
                    cwd=None,
                    env=None,
                    timeout=None,
                    progress_callback=None,
                    process_started_callback=None,
                ):  # noqa: ANN001
                    _ = command, cwd, env, timeout, progress_callback
                    if callable(process_started_callback):
                        process_started_callback(4321)
                    raise KeyboardInterrupt

            route = parse_route(
                ["test", "--project", "feature-a-1", "--test-sequential"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )

            with patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _InterruptingRunner):
                with self.assertRaises(KeyboardInterrupt):
                    engine.dispatch(route)

            self.assertEqual(terminated_pids, [4321])
            self.assertFalse(any(event.get("event") == "test.summary.persisted" for event in engine.events))
            self.assertTrue(
                any(event.get("event") == "test.interrupt.cleanup" for event in engine.events),
                msg=engine.events,
            )

    def test_test_action_interrupt_cancels_parallel_queue_and_terminates_started_suites(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            for feature_name in ("feature-a", "feature-b"):
                tree_root = repo / "trees" / feature_name / "1"
                tree_root.mkdir(parents=True, exist_ok=True)
                (tree_root / "backend" / "tests").mkdir(parents=True, exist_ok=True)
                (tree_root / "backend" / "pyproject.toml").write_text(
                    "[project]\nname='backend'\nversion='1.0.0'\n",
                    encoding="utf-8",
                )
                (tree_root / "frontend").mkdir(parents=True, exist_ok=True)
                (tree_root / "frontend" / "package.json").write_text(
                    '{"name":"frontend","scripts":{"test":"vitest run"}}',
                    encoding="utf-8",
                )
                (tree_root / "frontend" / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            terminated_pids: list[int] = []
            engine.process_runner = SimpleNamespace(  # type: ignore[assignment]
                terminate_process_group=lambda pid, **_kwargs: terminated_pids.append(pid) or True,
            )

            class _InterruptingRunner:
                call_count = 0
                started_first_suite = threading.Event()
                allow_first_suite_to_finish = threading.Event()

                def __init__(self, *_args, **_kwargs) -> None:
                    self.last_result = None

                def run_tests(
                    self,
                    command,
                    *,
                    cwd=None,
                    env=None,
                    timeout=None,
                    progress_callback=None,
                    process_started_callback=None,
                ):  # noqa: ANN001
                    _ = command, cwd, env, timeout, progress_callback
                    _InterruptingRunner.call_count += 1
                    if _InterruptingRunner.call_count == 1:
                        if callable(process_started_callback):
                            process_started_callback(2001)
                        _InterruptingRunner.started_first_suite.set()
                        _InterruptingRunner.allow_first_suite_to_finish.wait(timeout=1.0)
                        return SimpleNamespace(returncode=0, stdout="", stderr="")
                    if callable(process_started_callback):
                        process_started_callback(2002)
                    raise KeyboardInterrupt

            executor_state: dict[str, object] = {"shutdown_calls": []}

            class _FutureStub:
                def __init__(self, *, callback) -> None:  # noqa: ANN001
                    self._callback = callback
                    self.cancelled_flag = False

                def result(self):  # noqa: ANN201
                    if self.cancelled_flag:
                        raise AssertionError("cancelled future should not be awaited")
                    return self._callback()

                def cancel(self) -> bool:
                    self.cancelled_flag = True
                    return True

                def cancelled(self) -> bool:
                    return self.cancelled_flag

            class _ExecutorStub:
                def __init__(self, max_workers: int) -> None:
                    _ = max_workers
                    self.futures: list[_FutureStub] = []
                    self.pending: list[_FutureStub] = []
                    self.background_threads: list[threading.Thread] = []

                def submit(self, fn, *args, **kwargs):  # noqa: ANN001
                    submit_index = len(self.futures)
                    if submit_index == 0:
                        future = _FutureStub(callback=lambda: fn(*args, **kwargs))
                    elif submit_index == 1:
                        future = _FutureStub(callback=lambda: fn(*args, **kwargs))
                        worker = threading.Thread(target=future.result, daemon=True)
                        worker.start()
                        self.background_threads.append(worker)
                        _InterruptingRunner.started_first_suite.wait(timeout=1.0)
                    else:
                        future = _FutureStub(callback=lambda: fn(*args, **kwargs))
                        self.pending.append(future)
                    self.futures.append(future)
                    return future

                def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
                    shutdown_calls = executor_state["shutdown_calls"]
                    assert isinstance(shutdown_calls, list)
                    shutdown_calls.append((wait, cancel_futures))
                    _InterruptingRunner.allow_first_suite_to_finish.set()
                    if cancel_futures:
                        for future in self.pending:
                            future.cancel()
                    if wait:
                        for worker in self.background_threads:
                            worker.join(timeout=1.0)

            def _as_completed(futures):  # noqa: ANN001
                future_list = list(futures)
                if future_list:
                    yield future_list[0]

            futures_stub = SimpleNamespace(
                ThreadPoolExecutor=lambda max_workers: _ExecutorStub(max_workers),
                as_completed=_as_completed,
            )

            route = parse_route(["test", "--all"], env={"ENVCTL_DEFAULT_MODE": "trees"})

            with (
                patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                patch(
                    "envctl_engine.shared.node_tooling.shutil.which",
                    side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                ),
                patch("envctl_engine.actions.action_command_orchestrator.TestRunner", _InterruptingRunner),
                patch("envctl_engine.actions.action_command_orchestrator.concurrent.futures", futures_stub),
            ):
                with self.assertRaises(KeyboardInterrupt):
                    engine.dispatch(route)

            self.assertEqual(sorted(terminated_pids), [2001, 2002])
            shutdown_calls = executor_state["shutdown_calls"]
            assert isinstance(shutdown_calls, list)
            self.assertIn((False, True), shutdown_calls)
            cleanup_events = [event for event in engine.events if event.get("event") == "test.interrupt.cleanup"]
            self.assertTrue(cleanup_events, msg=engine.events)
            self.assertGreaterEqual(int(cleanup_events[-1].get("queued_cancelled", 0) or 0), 1)
            self.assertFalse(any(event.get("event") == "test.summary.persisted" for event in engine.events))

    def test_interrupt_cleanup_uses_real_test_runner_process_started_callback_in_sequential_and_parallel_modes(self) -> None:
        for sequential in (True, False):
            with self.subTest(sequential=sequential):
                with tempfile.TemporaryDirectory() as tmpdir:
                    repo = Path(tmpdir) / "repo"
                    runtime = Path(tmpdir) / "runtime"
                    tree_root = repo / "trees" / "feature-a" / "1"
                    (repo / ".git").mkdir(parents=True, exist_ok=True)
                    tree_root.mkdir(parents=True, exist_ok=True)
                    (tree_root / "backend" / "tests").mkdir(parents=True, exist_ok=True)
                    (tree_root / "backend" / "pyproject.toml").write_text(
                        "[project]\nname='backend'\nversion='1.0.0'\n",
                        encoding="utf-8",
                    )
                    frontend_dir = tree_root / "frontend"
                    frontend_dir.mkdir(parents=True, exist_ok=True)
                    (frontend_dir / "package.json").write_text(
                        '{"name":"frontend","scripts":{"test":"vitest run"}}',
                        encoding="utf-8",
                    )
                    (frontend_dir / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

                    engine = PythonEngineRuntime(self._config(repo, runtime), env={})

                    class _InterruptingProcessRunner:
                        def __init__(self) -> None:
                            self.terminated_pids: list[int] = []
                            self.backend_started = threading.Event()
                            self.release_backend = threading.Event()

                        def run_streaming(
                            self,
                            cmd,
                            *,
                            cwd=None,
                            env=None,
                            timeout=None,
                            callback=None,
                            process_started_callback=None,
                            show_spinner=True,
                            echo_output=True,
                            stdin=None,
                        ):  # noqa: ANN001
                            _ = cwd, env, timeout, callback, show_spinner, echo_output, stdin
                            rendered = " ".join(str(part) for part in cmd)
                            if sequential:
                                if callable(process_started_callback):
                                    process_started_callback(8101)
                                raise KeyboardInterrupt
                            if "pytest" in rendered:
                                if callable(process_started_callback):
                                    process_started_callback(8101)
                                self.backend_started.set()
                                self.release_backend.wait(timeout=1.0)
                                return subprocess.CompletedProcess(args=list(cmd), returncode=0, stdout="1 passed\n", stderr="")
                            self.backend_started.wait(timeout=1.0)
                            if callable(process_started_callback):
                                process_started_callback(8102)
                            raise KeyboardInterrupt

                        def terminate_process_group(self, pid: int, *, term_timeout: float = 2.0, kill_timeout: float = 1.0) -> bool:
                            _ = term_timeout, kill_timeout
                            self.terminated_pids.append(pid)
                            if pid == 8101:
                                self.release_backend.set()
                            return True

                    process_runner = _InterruptingProcessRunner()
                    engine.process_runner = process_runner  # type: ignore[assignment]

                    route_args = ["test", "--project", "feature-a-1"]
                    if sequential:
                        route_args.append("--test-sequential")
                    route = parse_route(route_args, env={"ENVCTL_DEFAULT_MODE": "trees"})

                    with (
                        patch("envctl_engine.actions.actions_test.detect_python_bin", return_value="/usr/bin/python3"),
                        patch(
                            "envctl_engine.shared.node_tooling.shutil.which",
                            side_effect=lambda name: "/usr/bin/pnpm" if name == "pnpm" else None,
                        ),
                    ):
                        with self.assertRaises(KeyboardInterrupt):
                            engine.dispatch(route)

                    expected_pids = [8101] if sequential else [8101, 8102]
                    self.assertEqual(sorted(process_runner.terminated_pids), expected_pids)
                    self.assertFalse(any(event.get("event") == "test.summary.persisted" for event in engine.events))
                    cleanup_events = [event for event in engine.events if event.get("event") == "test.interrupt.cleanup"]
                    self.assertTrue(cleanup_events, msg=engine.events)

