from __future__ import annotations

from concurrent.futures import Future
import unittest

from envctl_engine.actions.action_test_suite_run_loop import TestSuiteRunLoop


class _SynchronousExecutor:
    def __init__(self, *, max_workers: int) -> None:
        self.max_workers = max_workers
        self.shutdown_calls: list[bool] = []

    def submit(self, fn, spec):  # noqa: ANN001, ANN202
        future: Future[tuple[int, str]] = Future()
        try:
            future.set_result(fn(spec))
        except BaseException as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, *, cancel_futures: bool = False) -> None:
        self.shutdown_calls.append(cancel_futures)


class _FuturesModule:
    last_executor: _SynchronousExecutor | None = None

    @classmethod
    def ThreadPoolExecutor(cls, *, max_workers: int) -> _SynchronousExecutor:  # noqa: N802
        cls.last_executor = _SynchronousExecutor(max_workers=max_workers)
        return cls.last_executor

    @staticmethod
    def as_completed(future_map):  # noqa: ANN001, ANN202
        return list(future_map)


class TestSuiteRunLoopTests(unittest.TestCase):
    def test_sequential_run_stops_after_first_failure(self) -> None:
        seen: list[str] = []

        def run_spec(spec: str) -> tuple[int, str]:
            seen.append(spec)
            if spec == "second":
                return 1, "boom"
            return 0, ""

        failures = TestSuiteRunLoop(
            execution_specs=["first", "second", "third"],
            parallel=False,
            parallel_workers=1,
            futures_module=_FuturesModule,
            run_spec=run_spec,
            failure_label=lambda spec: f"label:{spec}",
            cancel_interrupted=lambda _executor, _future_map: None,
            shutdown_executor=lambda _executor: None,
        ).run()

        self.assertEqual(seen, ["first", "second"])
        self.assertEqual(failures, ["label:second: boom"])

    def test_parallel_run_collects_failures_without_short_circuiting(self) -> None:
        seen: list[str] = []

        def run_spec(spec: str) -> tuple[int, str]:
            seen.append(spec)
            return (1, "") if spec in {"second", "third"} else (0, "")

        failures = TestSuiteRunLoop(
            execution_specs=["first", "second", "third"],
            parallel=True,
            parallel_workers=3,
            futures_module=_FuturesModule,
            run_spec=run_spec,
            failure_label=lambda spec: f"label:{spec}",
            cancel_interrupted=lambda _executor, _future_map: None,
            shutdown_executor=lambda _executor: None,
        ).run()

        self.assertEqual(seen, ["first", "second", "third"])
        self.assertEqual(failures, ["label:second: unknown test failure", "label:third: unknown test failure"])
        self.assertIsNotNone(_FuturesModule.last_executor)
        self.assertEqual(_FuturesModule.last_executor.max_workers, 3)

    def test_keyboard_interrupt_cancels_queued_work_and_still_shuts_down_executor(self) -> None:
        calls: list[str] = []

        def run_spec(_spec: str) -> tuple[int, str]:
            calls.append("run")
            raise KeyboardInterrupt

        def cancel_interrupted(executor, future_map) -> None:  # noqa: ANN001
            calls.append(f"cancel:{executor is not None}:{len(future_map)}")

        def shutdown_executor(executor) -> None:  # noqa: ANN001
            calls.append(f"shutdown:{executor is not None}")

        with self.assertRaises(KeyboardInterrupt):
            TestSuiteRunLoop(
                execution_specs=["first"],
                parallel=True,
                parallel_workers=1,
                futures_module=_FuturesModule,
                run_spec=run_spec,
                failure_label=lambda spec: f"label:{spec}",
                cancel_interrupted=cancel_interrupted,
                shutdown_executor=shutdown_executor,
            ).run()

        self.assertEqual(calls, ["run", "cancel:True:1", "shutdown:True"])


if __name__ == "__main__":
    unittest.main()
