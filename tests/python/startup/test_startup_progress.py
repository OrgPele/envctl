from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.startup.startup_progress import report_progress, suppress_timing_output
from envctl_engine.startup.startup_progress import ProjectSpinnerGroup


class _ProgressStub:
    def __init__(self) -> None:
        self.updates: list[dict[str, object]] = []
        self.stopped: list[object] = []

    def update(self, task_id: object, **payload: object) -> None:
        self.updates.append({"task_id": task_id, **payload})

    def stop_task(self, task_id: object) -> None:
        self.stopped.append(task_id)


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

    def test_project_spinner_finished_descriptions_do_not_keep_legacy_status_prefixes(self) -> None:
        group = ProjectSpinnerGroup(
            projects=["Main"],
            enabled=False,
            policy=SimpleNamespace(enabled=True, backend="rich", style="dots"),
            emit=lambda *_args, **_kwargs: None,
            component="startup_orchestrator",
            op_id="startup.execute",
            env={},
        )
        progress = _ProgressStub()
        group._progress = progress  # noqa: SLF001
        group._tasks = {"Main": "task-main"}  # noqa: SLF001

        group.mark_success("Main", "startup completed")
        group.mark_failure("Main", "startup failed")

        descriptions = [str(update["description"]) for update in progress.updates]
        self.assertEqual(descriptions, ["Main: startup completed", "Main: startup failed"])
        self.assertFalse(any(description.startswith(("+ ", "! ")) for description in descriptions))
        self.assertEqual(progress.updates[0]["finished_symbol"], "[green]✓[/green]")
        self.assertEqual(progress.updates[1]["finished_symbol"], "[red]✗[/red]")


if __name__ == "__main__":
    unittest.main()
