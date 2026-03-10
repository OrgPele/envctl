from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.startup.startup_progress import report_progress, suppress_timing_output


class StartupProgressTests(unittest.TestCase):
    def test_report_progress_deduplicates_per_project(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))
        route = SimpleNamespace(flags={"interactive_command": True})
        progress_lock = threading.Lock()
        cache: dict[str | None, str] = {}

        report_progress(
            runtime,
            route,
            progress_lock=progress_lock,
            last_progress_message_by_project=cache,
            message="Starting project Main...",
            project="Main",
        )
        report_progress(
            runtime,
            route,
            progress_lock=progress_lock,
            last_progress_message_by_project=cache,
            message="Starting project Main...",
            project="Main",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][0], "ui.status")

    def test_suppress_timing_output_when_spinner_callbacks_present(self) -> None:
        route = SimpleNamespace(flags={"_spinner_update": lambda _msg: None})
        self.assertTrue(suppress_timing_output(route))


if __name__ == "__main__":
    unittest.main()
