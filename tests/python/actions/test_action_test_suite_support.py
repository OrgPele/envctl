from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.actions.action_test_suite_event_support import TestSuiteEventEmitter
from envctl_engine.actions.action_test_suite_outcome_support import TestSuiteOutcomeRecorder
from envctl_engine.actions.actions_test import TestCommandSpec as CommandSpec


class _Runtime:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, payload))


class ActionTestSuiteSupportTests(unittest.TestCase):
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
