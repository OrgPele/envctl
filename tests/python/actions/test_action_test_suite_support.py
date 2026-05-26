from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import concurrent.futures
import unittest

from envctl_engine.actions.action_test_suite_execution_support import TestSuiteRunLoop
from envctl_engine.actions.action_test_suite_event_support import TestSuiteEventEmitter
from envctl_engine.actions.action_test_suite_outcome_support import TestSuiteOutcomeRecorder
from envctl_engine.actions.actions_test import TestCommandSpec as CommandSpec


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


if __name__ == "__main__":
    unittest.main()
