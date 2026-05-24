from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase

from envctl_engine.actions.action_test_runner_progress import ParallelTestProgressTracker


def _execution(*, index: int = 1, source: str = "backend", project_name: str = "feature-a") -> SimpleNamespace:
    return SimpleNamespace(index=index, spec=SimpleNamespace(source=source), project_name=project_name)


class ParallelTestProgressTrackerTests(TestCase):
    def test_emit_status_renders_queued_running_and_completed_state(self) -> None:
        messages: list[str] = []
        tracker = ParallelTestProgressTracker(
            enabled=True,
            total_suites=3,
            max_workers=2,
            multi_project=True,
            failed_only=False,
            emit_status=messages.append,
            suite_display_name=lambda source, *, failed_only: f"{source}-suite" if not failed_only else source,
        )

        tracker.emit_status(phase="queued")
        tracker.mark_running(_execution(index=1, source="backend", project_name="feature-a"))
        tracker.mark_finished(_execution(index=1, source="backend", project_name="feature-a"), success=True)

        self.assertEqual(
            messages,
            [
                "Tests progress: running 0/2, finished 0/3, queued 3 • running: - • done: -",
                (
                    "Tests progress: running 1/2, finished 0/3, queued 2 • running: feature-a / backend-suite "
                    "• running: feature-a / backend-suite • done: -"
                ),
                (
                    "Tests progress: running 0/2, finished 1/3, queued 2 • completed: feature-a / backend-suite "
                    "• running: - • done: feature-a / backend-suite (PASS)"
                ),
            ],
        )

    def test_disabled_tracker_does_not_emit_or_mutate_status(self) -> None:
        messages: list[str] = []
        tracker = ParallelTestProgressTracker(
            enabled=False,
            total_suites=1,
            max_workers=1,
            multi_project=False,
            failed_only=True,
            emit_status=messages.append,
            suite_display_name=lambda source, *, failed_only: source,
        )

        tracker.emit_status(phase="queued")
        tracker.mark_running(_execution(source="backend"))
        tracker.mark_finished(_execution(source="backend"), success=False)

        self.assertEqual(messages, [])

    def test_label_rendering_compacts_long_running_and_done_lists(self) -> None:
        messages: list[str] = []
        tracker = ParallelTestProgressTracker(
            enabled=True,
            total_suites=5,
            max_workers=4,
            multi_project=False,
            failed_only=False,
            emit_status=messages.append,
            suite_display_name=lambda source, *, failed_only: source,
        )

        for index in range(1, 5):
            tracker.mark_running(_execution(index=index, source=f"suite-{index}"))
        tracker.mark_finished(_execution(index=1, source="suite-1"), success=False)
        tracker.mark_finished(_execution(index=2, source="suite-2"), success=True)
        tracker.mark_finished(_execution(index=3, source="suite-3"), success=True)
        tracker.mark_finished(_execution(index=4, source="suite-4"), success=True)

        self.assertTrue(any("running: suite-1, suite-2, suite-3, +1 more" in message for message in messages))
        self.assertIn(
            "done: suite-1 (FAIL), suite-2 (PASS), suite-3 (PASS), +1 more",
            messages[-1],
        )
