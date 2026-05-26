from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from envctl_engine.actions.action_test_interrupt_support import TestSuiteInterruptRegistry


def _execution(*, index: int = 1, source: str = "backend", project_name: str = "feature-a") -> SimpleNamespace:
    return SimpleNamespace(
        index=index,
        spec=SimpleNamespace(source=source),
        project_name=project_name,
    )


class TestSuiteInterruptRegistryTests(TestCase):
    def test_register_started_suite_tracks_and_clear_removes_matching_pid(self) -> None:
        runtime = SimpleNamespace(
            process_runner=SimpleNamespace(terminate_process_group=lambda *_args, **_kwargs: True),
            _emit=lambda *_args, **_kwargs: None,
        )
        registry = TestSuiteInterruptRegistry(
            runtime=runtime,
            emit_status=lambda _message: None,
            execution_mode="sequential",
        )

        registry.register_started_suite(_execution(index=2, source="frontend"), 4321)
        self.assertEqual(registry.active_suite_count, 1)

        registry.clear_by_index(2, pid=9999)
        self.assertEqual(registry.active_suite_count, 1)

        registry.clear_by_index(2, pid=4321)
        self.assertEqual(registry.active_suite_count, 0)

    def test_cleanup_interrupted_suites_emits_events_and_terminates_active_processes(self) -> None:
        statuses: list[str] = []
        events: list[tuple[str, dict[str, object]]] = []
        terminated: list[int] = []
        clock = iter([10.0, 10.125])

        runtime = SimpleNamespace(
            process_runner=SimpleNamespace(
                terminate_process_group=lambda pid, **_kwargs: terminated.append(pid) or True,
            ),
            _emit=lambda event, **payload: events.append((event, payload)),
        )
        registry = TestSuiteInterruptRegistry(
            runtime=runtime,
            emit_status=statuses.append,
            execution_mode="parallel",
            monotonic_fn=lambda: next(clock),
            sleep_fn=lambda _seconds: None,
        )
        registry.register_started_suite(_execution(index=1, source="backend"), 2001)
        registry.register_started_suite(_execution(index=2, source="frontend"), 2002)

        registry.cleanup_interrupted_suites(queued_cancelled=3)

        self.assertTrue(registry.interrupt_received)
        self.assertEqual(statuses, ["Interrupt received, stopping active test suites..."])
        self.assertEqual(terminated, [2001, 2002])
        self.assertEqual(registry.active_suite_count, 0)
        self.assertEqual(events[0], ("test.interrupt.received", {"active_suites": 2, "queued_cancelled": 3, "mode": "parallel"}))
        self.assertEqual(events[1][0], "test.interrupt.cleanup")
        self.assertEqual(events[1][1]["active_suites"], 2)
        self.assertEqual(events[1][1]["queued_cancelled"], 3)
        self.assertEqual(events[1][1]["signaled_pids"], [2001, 2002])
        self.assertEqual(events[1][1]["survivors"], 0)
        self.assertEqual(events[1][1]["cleanup_duration_ms"], 125.0)

    def test_register_started_suite_after_interrupt_terminates_immediately(self) -> None:
        terminated: list[int] = []
        runtime = SimpleNamespace(
            process_runner=SimpleNamespace(
                terminate_process_group=lambda pid, **_kwargs: terminated.append(pid) or True,
            ),
            _emit=lambda *_args, **_kwargs: None,
        )
        registry = TestSuiteInterruptRegistry(
            runtime=runtime,
            emit_status=lambda _message: None,
            execution_mode="parallel",
        )
        registry.interrupt_received = True

        registry.register_started_suite(_execution(index=4), 9004)

        self.assertEqual(terminated, [9004])
        self.assertEqual(registry.active_suite_count, 0)

    def test_termination_result_is_cached_per_pid(self) -> None:
        terminated: list[int] = []
        runtime = SimpleNamespace(
            process_runner=SimpleNamespace(
                terminate_process_group=lambda pid, **_kwargs: terminated.append(pid) or False,
            ),
            _emit=lambda *_args, **_kwargs: None,
        )
        registry = TestSuiteInterruptRegistry(
            runtime=runtime,
            emit_status=lambda _message: None,
            execution_mode="parallel",
        )

        self.assertFalse(registry.terminate_pid(7777))
        self.assertFalse(registry.terminate_pid(7777))
        self.assertEqual(terminated, [7777])
