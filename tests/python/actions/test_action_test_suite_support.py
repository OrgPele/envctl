from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import concurrent.futures
import tempfile
import unittest
from unittest.mock import patch

from envctl_engine.actions.action_test_suite_execution_support import TestSuiteRunLoop, _TestSuiteExecutor
from envctl_engine.actions.action_test_suite_event_support import TestSuiteEventEmitter
from envctl_engine.actions.action_test_suite_fallback_support import run_test_suites_with_parallel_fallback
from envctl_engine.actions.action_test_suite_outcome_support import TestSuiteOutcomeRecorder
from envctl_engine.actions.actions_test import TestCommandSpec as CommandSpec
from envctl_engine.runtime.command_router import parse_route


class _Runtime:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, payload))


class ActionTestSuiteSupportTests(unittest.TestCase):
    def test_suite_run_loop_stops_sequential_execution_after_first_failure(self) -> None:
        first = SimpleNamespace(index=1, project_name="Main", spec=SimpleNamespace(source="backend_pytest"))
        second = SimpleNamespace(index=2, project_name="Main", spec=SimpleNamespace(source="frontend_package_test"))
        calls: list[int] = []

        def run_spec(execution: object) -> tuple[int, str]:
            calls.append(int(getattr(execution, "index")))
            return 1, "backend failed"

        failures = TestSuiteRunLoop(
            execution_specs=[first, second],
            parallel=False,
            parallel_workers=1,
            futures_module=concurrent.futures,
            run_spec=run_spec,
            failure_label=lambda execution: f"{execution.project_name}:{execution.spec.source}",
            cancel_interrupted=lambda _executor, _future_map: None,
            shutdown_executor=lambda _executor: None,
        ).run()

        self.assertEqual(calls, [1])
        self.assertEqual(failures, ["Main:backend_pytest: backend failed"])

    def test_suite_run_loop_can_collect_all_sequential_failures_for_fallback(self) -> None:
        first = SimpleNamespace(index=1, project_name="Main", spec=SimpleNamespace(source="backend_pytest"))
        second = SimpleNamespace(index=2, project_name="Main", spec=SimpleNamespace(source="frontend_package_test"))
        calls: list[int] = []

        def run_spec(execution: object) -> tuple[int, str]:
            index = int(getattr(execution, "index"))
            calls.append(index)
            return 1, f"suite {index} failed"

        failures = TestSuiteRunLoop(
            execution_specs=[first, second],
            parallel=False,
            parallel_workers=1,
            futures_module=concurrent.futures,
            run_spec=run_spec,
            failure_label=lambda execution: f"{execution.project_name}:{execution.spec.source}",
            cancel_interrupted=lambda _executor, _future_map: None,
            shutdown_executor=lambda _executor: None,
            stop_on_sequential_failure=False,
        ).run()

        self.assertEqual(calls, [1, 2])
        self.assertEqual(
            failures,
            ["Main:backend_pytest: suite 1 failed", "Main:frontend_package_test: suite 2 failed"],
        )

    def test_suite_run_loop_collects_parallel_failures_without_stopping_other_suites(self) -> None:
        first = SimpleNamespace(index=1, project_name="Main", spec=SimpleNamespace(source="backend_pytest"))
        second = SimpleNamespace(index=2, project_name="Main", spec=SimpleNamespace(source="frontend_package_test"))

        def run_spec(execution: object) -> tuple[int, str]:
            index = int(getattr(execution, "index"))
            return (1, "backend failed") if index == 1 else (0, "")

        failures = TestSuiteRunLoop(
            execution_specs=[first, second],
            parallel=True,
            parallel_workers=2,
            futures_module=concurrent.futures,
            run_spec=run_spec,
            failure_label=lambda execution: f"{execution.project_name}:{execution.spec.source}",
            cancel_interrupted=lambda _executor, _future_map: None,
            shutdown_executor=lambda executor: executor.shutdown(wait=True) if executor is not None else None,
        ).run()

        self.assertEqual(failures, ["Main:backend_pytest: backend failed"])

    def test_parallel_executor_falls_back_to_sequential_and_replaces_parallel_outcomes(self) -> None:
        first = SimpleNamespace(index=1, project_name="Main", spec=SimpleNamespace(source="backend_pytest"))
        second = SimpleNamespace(index=2, project_name="Main", spec=SimpleNamespace(source="frontend_package_test"))
        calls: list[tuple[str, int]] = []
        statuses: list[str] = []
        emitted_events: list[tuple[str, dict[str, object]]] = []

        class _ImmediateExecutor:
            def __init__(self, max_workers: int) -> None:
                self.max_workers = max_workers

            def submit(self, fn, *args, **kwargs):  # noqa: ANN001
                future: concurrent.futures.Future[tuple[int, str]] = concurrent.futures.Future()
                future.set_result(fn(*args, **kwargs))
                return future

            def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
                _ = wait, cancel_futures

        executor = _TestSuiteExecutor.__new__(_TestSuiteExecutor)
        executor.orchestrator = SimpleNamespace(_emit_status=statuses.append)
        executor.runtime = SimpleNamespace(_emit=lambda event, **payload: emitted_events.append((event, payload)))
        executor.plan = SimpleNamespace(parallel=True, parallel_workers=2)
        executor.use_suite_spinner_group = False
        executor.suite_spinner_group = None
        executor.interrupt_registry = SimpleNamespace(interrupt_received=False)
        executor.progress_tracker = SimpleNamespace(emit_status=lambda **_kwargs: None)
        executor.execution_specs = [first, second]
        executor.futures_module = SimpleNamespace(
            ThreadPoolExecutor=_ImmediateExecutor,
            as_completed=concurrent.futures.as_completed,
        )
        executor.presenter = SimpleNamespace(
            failure_label=lambda execution: f"{execution.project_name}:{execution.spec.source}"
        )
        executor.outcomes = SimpleNamespace(outcomes=[])

        def run_spec(execution: object) -> tuple[int, str]:
            attempt = "parallel" if len(calls) < 2 else "fallback"
            index = int(getattr(execution, "index"))
            calls.append((attempt, index))
            executor.outcomes.outcomes.append({"attempt": attempt, "index": index})
            if attempt == "parallel" and index == 1:
                return 1, "parallel-only failure"
            return 0, ""

        executor.run_spec = run_spec

        result = _TestSuiteExecutor.run(executor)

        self.assertEqual(calls, [("parallel", 1), ("parallel", 2), ("fallback", 1), ("fallback", 2)])
        self.assertEqual(result.failures, [])
        self.assertEqual(
            result.outcomes,
            [{"attempt": "fallback", "index": 1}, {"attempt": "fallback", "index": 2}],
        )
        self.assertTrue(any("retrying the same suites sequentially" in status for status in statuses))
        self.assertEqual(
            emitted_events,
            [("test.parallel.fallback", {"failures": 1, "suites": 2, "reason": "test_failure"})],
        )

    def test_parallel_executor_falls_back_to_sequential_when_parallel_executor_raises(self) -> None:
        first = SimpleNamespace(index=1, project_name="Main", spec=SimpleNamespace(source="backend_pytest"))
        calls: list[int] = []
        statuses: list[str] = []
        emitted_events: list[tuple[str, dict[str, object]]] = []

        class _FailingExecutor:
            def __init__(self, max_workers: int) -> None:
                _ = max_workers
                raise RuntimeError("thread pool unavailable")

        executor = _TestSuiteExecutor.__new__(_TestSuiteExecutor)
        executor.orchestrator = SimpleNamespace(_emit_status=statuses.append)
        executor.runtime = SimpleNamespace(_emit=lambda event, **payload: emitted_events.append((event, payload)))
        executor.plan = SimpleNamespace(parallel=True, parallel_workers=2)
        executor.use_suite_spinner_group = False
        executor.suite_spinner_group = None
        executor.progress_tracker = SimpleNamespace(emit_status=lambda **_kwargs: None)
        executor.execution_specs = [first]
        executor.futures_module = SimpleNamespace(
            ThreadPoolExecutor=_FailingExecutor,
            as_completed=concurrent.futures.as_completed,
        )
        executor.presenter = SimpleNamespace(
            failure_label=lambda execution: f"{execution.project_name}:{execution.spec.source}"
        )
        executor.outcomes = SimpleNamespace(outcomes=[])

        def run_spec(execution: object) -> tuple[int, str]:
            calls.append(int(getattr(execution, "index")))
            executor.outcomes.outcomes.append({"attempt": "fallback", "index": int(getattr(execution, "index"))})
            return 0, ""

        executor.run_spec = run_spec

        result = _TestSuiteExecutor.run(executor)

        self.assertEqual(calls, [1])
        self.assertEqual(result.failures, [])
        self.assertEqual(result.outcomes, [{"attempt": "fallback", "index": 1}])
        self.assertTrue(any("retrying the same suites sequentially" in status for status in statuses))
        self.assertEqual(
            emitted_events,
            [("test.parallel.fallback", {"failures": 1, "suites": 1, "reason": "RuntimeError"})],
        )

    def test_parallel_fallback_does_not_retry_when_only_one_worker_ran(self) -> None:
        outcomes = SimpleNamespace(outcomes=[])
        statuses: list[str] = []
        emitted_events: list[tuple[str, dict[str, object]]] = []
        calls: list[dict[str, object]] = []

        def run_loop(**kwargs: object) -> list[str]:
            calls.append(dict(kwargs))
            outcomes.outcomes.append({"parallel": kwargs["parallel"], "workers": kwargs["parallel_workers"]})
            return ["Main:backend_pytest: failed"]

        failures = run_test_suites_with_parallel_fallback(
            parallel=True,
            parallel_workers=1,
            suite_count=1,
            outcomes=outcomes,
            emit_status=statuses.append,
            emit_event=lambda event, **payload: emitted_events.append((event, payload)),
            run_loop=run_loop,
        )

        self.assertEqual(failures, ["Main:backend_pytest: failed"])
        self.assertEqual(calls, [{"parallel": True, "parallel_workers": 1}])
        self.assertEqual(outcomes.outcomes, [{"parallel": True, "workers": 1}])
        self.assertEqual(statuses, [])
        self.assertEqual(emitted_events, [])

    def test_event_emitter_preserves_suite_event_payloads(self) -> None:
        runtime = _Runtime()
        emitter = TestSuiteEventEmitter(runtime=runtime, total=2)
        execution = SimpleNamespace(
            index=1,
            spec=SimpleNamespace(source="backend_pytest", cwd=Path("/repo")),
            project_name="Main",
            project_root=Path("/repo"),
        )
        parsed = SimpleNamespace(
            counts_detected=True,
            passed=3,
            failed=1,
            skipped=0,
            errors=0,
            total=4,
        )

        emitter.emit_start(execution, command=["python", "-m", "pytest"])
        emitter.emit_summary(execution, parsed=parsed)
        emitter.emit_finish(
            execution,
            command=["python", "-m", "pytest"],
            completed=SimpleNamespace(returncode=1),
            duration_ms=42.5,
        )

        self.assertEqual([event for event, _payload in runtime.events], ["test.suite.start", "test.suite.summary", "test.suite.finish"])
        self.assertEqual(runtime.events[0][1]["total"], 2)
        self.assertEqual(runtime.events[1][1]["passed"], 3)
        self.assertEqual(runtime.events[2][1]["returncode"], 1)
        self.assertEqual(runtime.events[2][1]["duration_ms"], 42.5)

    def test_outcome_recorder_formats_success_and_failure_records(self) -> None:
        recorder = TestSuiteOutcomeRecorder(failed_only=True)
        execution = SimpleNamespace(
            index=2,
            spec=CommandSpec(source="backend_pytest", command=["python", "-m", "pytest"], cwd=Path("/repo")),
            project_name="Main",
            project_root=Path("/repo"),
        )

        recorder.record(
            execution,
            command=["python", "-m", "pytest"],
            completed=SimpleNamespace(returncode=1, stdout="FAILED tests/test_app.py::test_x\n", stderr=""),
            parsed=None,
            duration_ms=99.0,
        )

        self.assertEqual(len(recorder.outcomes), 1)
        outcome = recorder.outcomes[0]
        self.assertEqual(outcome["suite"], "backend_pytest")
        self.assertEqual(outcome["returncode"], 1)
        self.assertTrue(outcome["failed_only"])
        self.assertIn("FAILED tests/test_app.py::test_x", str(outcome["failure_summary"]))
        self.assertIn("FAILED tests/test_app.py::test_x", str(outcome["failure_details"]))

    def test_envctl_test_pytest_command_does_not_inject_xdist_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            python = root / ".venv" / "bin" / "python"
            (root / ".venv" / "lib" / "python3.12" / "site-packages" / "xdist").mkdir(parents=True)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            executor = _TestSuiteExecutor.__new__(_TestSuiteExecutor)
            executor.runtime = SimpleNamespace(env={}, config=SimpleNamespace(raw={}))
            executor.route = parse_route(["test"], env={})

            command = executor._execution_command(
                [str(python), "-m", "pytest", "-q", "tests"],
                cwd=root,
            )

        self.assertEqual(command, [str(python), "-m", "pytest", "-q", "tests"])

    def test_envctl_test_sequential_flag_keeps_pytest_xdist_env_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            python = root / ".venv" / "bin" / "python"
            (root / ".venv" / "lib" / "python3.12" / "site-packages" / "xdist").mkdir(parents=True)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            executor = _TestSuiteExecutor.__new__(_TestSuiteExecutor)
            executor.runtime = SimpleNamespace(
                env={"ENVCTL_ACTION_TEST_PYTEST_PARALLEL": "true"},
                config=SimpleNamespace(raw={}),
            )
            executor.route = parse_route(["test", "--sequential"], env={})

            with (
                patch("envctl_engine.actions.action_pytest_parallel_support.os.cpu_count", return_value=4),
                patch("envctl_engine.actions.action_pytest_parallel_support.os.getloadavg", return_value=(0.0, 0.0, 0.0)),
            ):
                command = executor._execution_command(
                    [str(python), "-m", "pytest", "-q", "tests"],
                    cwd=root,
                )

        self.assertEqual(command, [str(python), "-m", "pytest", "-n", "4", "-q", "tests"])

    def test_envctl_test_pytest_parallel_flag_does_not_enable_nested_xdist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            python = root / ".venv" / "bin" / "python"
            (root / ".venv" / "lib" / "python3.12" / "site-packages" / "xdist").mkdir(parents=True)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            executor = _TestSuiteExecutor.__new__(_TestSuiteExecutor)
            executor.runtime = SimpleNamespace(env={}, config=SimpleNamespace(raw={}))
            executor.route = parse_route(["test", "--parallel"], env={})

            command = executor._execution_command(
                [str(python), "-m", "pytest", "-q", "tests"],
                cwd=root,
            )

        self.assertEqual(command, [str(python), "-m", "pytest", "-q", "tests"])

    def test_envctl_test_retries_injected_xdist_137_without_xdist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".venv" / "lib" / "python3.12" / "site-packages" / "xdist").mkdir(parents=True)
            calls: list[list[str]] = []
            statuses: list[str] = []
            recorded: list[dict[str, object]] = []

            class _Runner:
                last_result = None

                def run_tests(self, command, **_kwargs):  # noqa: ANN001
                    calls.append(list(command))
                    self.last_result = SimpleNamespace(counts_detected=False)
                    return SimpleNamespace(returncode=137 if len(calls) == 1 else 0, stdout="", stderr="")

            executor = _TestSuiteExecutor.__new__(_TestSuiteExecutor)
            executor.failed_only = False
            executor.interactive_command = False
            executor.targets = []
            executor.route = parse_route(["test"], env={})
            executor.runtime = SimpleNamespace(
                env={"ENVCTL_ACTION_TEST_PYTEST_PARALLEL": "true"},
                config=SimpleNamespace(raw={}),
                _emit=lambda *_args, **_kwargs: None,
            )
            executor.orchestrator = SimpleNamespace(
                runtime=executor.runtime,
                _suite_display_name=lambda source, **_kwargs: source,
                _test_execution_status=lambda *_args, **_kwargs: "running tests",
                _emit_status=statuses.append,
                test_action_extra_env=lambda **_kwargs: {},
                action_env=lambda *_args, **_kwargs: {},
            )
            executor.plan = SimpleNamespace(multi_project=False)
            executor.use_suite_spinner_group = False
            executor.progress_tracker = SimpleNamespace(mark_running=lambda *_args, **_kwargs: None)
            executor.presenter = SimpleNamespace(
                announce_suite_start=lambda *_args, **_kwargs: None,
                emit_suite_summary=lambda *_args, **_kwargs: None,
                print_interactive_suite_finish=lambda *_args, **_kwargs: None,
                mark_finished=lambda *_args, **_kwargs: None,
            )
            executor.events = SimpleNamespace(
                emit_start=lambda *_args, **_kwargs: None,
                emit_finish=lambda *_args, **_kwargs: None,
            )
            executor.outcomes = SimpleNamespace(
                record=lambda _execution, **kwargs: recorded.append(kwargs),
            )
            executor.interrupt_registry = SimpleNamespace(
                clear_by_index=lambda *_args, **_kwargs: None,
                register_started_suite=lambda *_args, **_kwargs: None,
            )
            executor.test_runner_cls = lambda *_args, **_kwargs: _Runner()

            with (
                patch("envctl_engine.actions.action_pytest_parallel_support.os.cpu_count", return_value=4),
                patch("envctl_engine.actions.action_pytest_parallel_support.os.getloadavg", return_value=(0.0, 0.0, 0.0)),
            ):
                code, error = executor.run_spec(
                    SimpleNamespace(
                        index=1,
                        spec=CommandSpec(
                            source="backend_pytest",
                            command=["uv", "run", "pytest", "-q", "tests"],
                            cwd=root,
                        ),
                        args=[],
                        resolved_source="configured",
                        project_name="Main",
                        project_root=root,
                        target_obj=None,
                    )
                )

        self.assertEqual((code, error), (0, ""))
        self.assertEqual(calls[0], ["uv", "run", "pytest", "-n", "4", "-q", "tests"])
        self.assertEqual(calls[1], ["uv", "run", "pytest", "-q", "tests"])
        self.assertIn("retrying without pytest-xdist", statuses[-1])
        self.assertEqual(recorded[-1]["command"], ["uv", "run", "pytest", "-q", "tests"])

    def test_envctl_test_does_not_retry_explicit_xdist_137_with_rewritten_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            calls: list[list[str]] = []
            statuses: list[str] = []
            recorded: list[dict[str, object]] = []

            class _Runner:
                last_result = None

                def run_tests(self, command, **_kwargs):  # noqa: ANN001
                    calls.append(list(command))
                    self.last_result = SimpleNamespace(counts_detected=False)
                    return SimpleNamespace(returncode=137 if len(calls) == 1 else 0, stdout="", stderr="")

            executor = _TestSuiteExecutor.__new__(_TestSuiteExecutor)
            executor.failed_only = False
            executor.interactive_command = False
            executor.targets = []
            executor.route = parse_route(["test"], env={})
            executor.runtime = SimpleNamespace(
                env={"ENVCTL_ACTION_TEST_PYTEST_PARALLEL": "true"},
                config=SimpleNamespace(raw={}),
                _emit=lambda *_args, **_kwargs: None,
            )
            executor.orchestrator = SimpleNamespace(
                runtime=executor.runtime,
                _suite_display_name=lambda source, **_kwargs: source,
                _test_execution_status=lambda *_args, **_kwargs: "running tests",
                _emit_status=statuses.append,
                test_action_extra_env=lambda **_kwargs: {},
                action_env=lambda *_args, **_kwargs: {},
            )
            executor.plan = SimpleNamespace(multi_project=False)
            executor.use_suite_spinner_group = False
            executor.progress_tracker = SimpleNamespace(mark_running=lambda *_args, **_kwargs: None)
            executor.presenter = SimpleNamespace(
                announce_suite_start=lambda *_args, **_kwargs: None,
                emit_suite_summary=lambda *_args, **_kwargs: None,
                print_interactive_suite_finish=lambda *_args, **_kwargs: None,
                mark_finished=lambda *_args, **_kwargs: None,
            )
            executor.events = SimpleNamespace(
                emit_start=lambda *_args, **_kwargs: None,
                emit_finish=lambda *_args, **_kwargs: None,
            )
            executor.outcomes = SimpleNamespace(
                record=lambda _execution, **kwargs: recorded.append(kwargs),
            )
            executor.interrupt_registry = SimpleNamespace(
                clear_by_index=lambda *_args, **_kwargs: None,
                register_started_suite=lambda *_args, **_kwargs: None,
            )
            executor.test_runner_cls = lambda *_args, **_kwargs: _Runner()

            code, error = executor.run_spec(
                SimpleNamespace(
                    index=1,
                    spec=CommandSpec(
                        source="backend_pytest",
                        command=["uv", "run", "pytest", "-n", "4", "-q", "tests"],
                        cwd=root,
                    ),
                    args=[],
                    resolved_source="configured",
                    project_name="Main",
                    project_root=root,
                    target_obj=None,
                )
            )

        self.assertEqual(code, 1)
        self.assertIn("137", error)
        self.assertEqual(calls, [["uv", "run", "pytest", "-n", "4", "-q", "tests"]])
        self.assertEqual(statuses, [])
        self.assertEqual(recorded[-1]["command"], ["uv", "run", "pytest", "-n", "4", "-q", "tests"])

    def test_envctl_test_uv_pytest_command_uses_free_core_worker_count_when_xdist_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".venv" / "lib" / "python3.12" / "site-packages" / "xdist").mkdir(parents=True)
            executor = _TestSuiteExecutor.__new__(_TestSuiteExecutor)
            executor.runtime = SimpleNamespace(
                env={"ENVCTL_ACTION_TEST_PYTEST_PARALLEL": "true"},
                config=SimpleNamespace(raw={}),
            )
            executor.route = parse_route(["test"], env={})

            with (
                patch("envctl_engine.actions.action_pytest_parallel_support.os.cpu_count", return_value=10),
                patch("envctl_engine.actions.action_pytest_parallel_support.os.getloadavg", return_value=(3.4, 1.0, 1.0)),
            ):
                command = executor._execution_command(
                    ["uv", "run", "pytest", "-q", "tests"],
                    cwd=root,
                )

        self.assertEqual(command, ["uv", "run", "pytest", "-n", "6", "-q", "tests"])

    def test_envctl_test_pytest_xdist_detection_keeps_venv_symlink_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            base_python = root / "base" / "python"
            python = root / ".venv" / "bin" / "python"
            (root / ".venv" / "lib" / "python3.12" / "site-packages" / "xdist").mkdir(parents=True)
            base_python.parent.mkdir(parents=True)
            base_python.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            python.parent.mkdir(parents=True)
            python.symlink_to(base_python)
            executor = _TestSuiteExecutor.__new__(_TestSuiteExecutor)
            executor.runtime = SimpleNamespace(
                env={"ENVCTL_ACTION_TEST_PYTEST_PARALLEL": "true"},
                config=SimpleNamespace(raw={}),
            )
            executor.route = parse_route(["test"], env={})

            with (
                patch("envctl_engine.actions.action_pytest_parallel_support.os.cpu_count", return_value=4),
                patch("envctl_engine.actions.action_pytest_parallel_support.os.getloadavg", return_value=(0.1, 1.0, 1.0)),
            ):
                command = executor._execution_command(
                    [str(python), "-m", "pytest", "-q", "tests"],
                    cwd=root,
                )

        self.assertEqual(command, [str(python), "-m", "pytest", "-n", "3", "-q", "tests"])

    def test_envctl_test_pytest_parallel_respects_plugin_opt_outs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            python = root / ".venv" / "bin" / "python"
            (root / ".venv" / "lib" / "python3.12" / "site-packages" / "xdist").mkdir(parents=True)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!/usr/bin/env python\n", encoding="utf-8")

            for args, env in (
                ([str(python), "-m", "pytest", "-pno:xdist", "-q", "tests"], {}),
                ([str(python), "-m", "pytest", "-p=no:xdist", "-q", "tests"], {}),
                ([str(python), "-m", "pytest", "--disable-plugin-autoload", "-q", "tests"], {}),
                ([str(python), "-m", "pytest", "-q", "tests"], {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}),
            ):
                with self.subTest(args=args, env=env):
                    executor = _TestSuiteExecutor.__new__(_TestSuiteExecutor)
                    executor.runtime = SimpleNamespace(
                        env={"ENVCTL_ACTION_TEST_PYTEST_PARALLEL": "true", **env},
                        config=SimpleNamespace(raw={}),
                    )
                    executor.route = parse_route(["test"], env={})

                    with patch("envctl_engine.actions.action_pytest_parallel_support.os.cpu_count", return_value=4):
                        command = executor._execution_command(args, cwd=root)

                    self.assertEqual(command, args)

    def test_envctl_test_pytest_workers_can_be_capped_without_focused_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            python = root / ".venv" / "bin" / "python"
            (root / ".venv" / "lib" / "python3.12" / "site-packages" / "xdist").mkdir(parents=True)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            executor = _TestSuiteExecutor.__new__(_TestSuiteExecutor)
            executor.runtime = SimpleNamespace(
                env={
                    "ENVCTL_ACTION_TEST_PYTEST_PARALLEL": "true",
                    "ENVCTL_ACTION_TEST_PYTEST_WORKERS": "6",
                    "ENVCTL_TEST_FOCUSED_PYTEST_WORKERS": "2",
                },
                config=SimpleNamespace(raw={}),
            )
            executor.route = parse_route(["test"], env={})

            with patch("envctl_engine.actions.action_pytest_parallel_support.os.cpu_count", return_value=12):
                command = executor._execution_command(
                    [str(python), "-m", "pytest", "-q", "tests"],
                    cwd=root,
                )

        self.assertEqual(command, [str(python), "-m", "pytest", "-n", "6", "-q", "tests"])

    def test_envctl_test_pytest_workers_can_be_capped_by_route_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            python = root / ".venv" / "bin" / "python"
            (root / ".venv" / "lib" / "python3.12" / "site-packages" / "xdist").mkdir(parents=True)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            executor = _TestSuiteExecutor.__new__(_TestSuiteExecutor)
            executor.runtime = SimpleNamespace(
                env={"ENVCTL_ACTION_TEST_PYTEST_PARALLEL": "true"},
                config=SimpleNamespace(raw={}),
            )
            executor.route = parse_route(["test", "--test-parallel-max", "3"], env={})

            with patch("envctl_engine.actions.action_pytest_parallel_support.os.cpu_count", return_value=12):
                command = executor._execution_command(
                    [str(python), "-m", "pytest", "-q", "tests"],
                    cwd=root,
                )

        self.assertEqual(command, [str(python), "-m", "pytest", "-n", "3", "-q", "tests"])

    def test_envctl_test_suite_parallel_max_does_not_replace_pytest_worker_auto_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            python = root / ".venv" / "bin" / "python"
            (root / ".venv" / "lib" / "python3.12" / "site-packages" / "xdist").mkdir(parents=True)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("#!/usr/bin/env python\n", encoding="utf-8")
            executor = _TestSuiteExecutor.__new__(_TestSuiteExecutor)
            executor.runtime = SimpleNamespace(
                env={
                    "ENVCTL_ACTION_TEST_PARALLEL_MAX": "2",
                    "ENVCTL_ACTION_TEST_PYTEST_PARALLEL": "true",
                },
                config=SimpleNamespace(raw={}),
            )
            executor.route = parse_route(["test"], env={})

            with (
                patch("envctl_engine.actions.action_pytest_parallel_support.os.cpu_count", return_value=8),
                patch("envctl_engine.actions.action_pytest_parallel_support.os.getloadavg", return_value=(2.1, 1.0, 1.0)),
            ):
                command = executor._execution_command(
                    [str(python), "-m", "pytest", "-q", "tests"],
                    cwd=root,
                )

        self.assertEqual(command, [str(python), "-m", "pytest", "-n", "5", "-q", "tests"])


if __name__ == "__main__":
    unittest.main()
