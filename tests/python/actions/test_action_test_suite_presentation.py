from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from envctl_engine.actions.action_test_suite_presentation import TestSuitePresenter, render_command


class _Runtime:
    env: dict[str, str] = {}


class _Orchestrator:
    def __init__(self) -> None:
        self.runtime = _Runtime()
        self.statuses: list[str] = []

    def _emit_status(self, message: str) -> None:
        self.statuses.append(message)

    @staticmethod
    def _suite_display_name(source: str, *, failed_only: bool = False) -> str:
        return f"failed {source}" if failed_only else source

    @staticmethod
    def _test_execution_status(command, *, args, source, cwd):  # noqa: ANN001, ANN202
        return f"{source}: {render_command([*command, *args])} @ {cwd}"

    @staticmethod
    def _colorize(text: str, **_kwargs) -> str:  # noqa: ANN003
        return text


class _ProgressTracker:
    def __init__(self) -> None:
        self.finished: list[tuple[object, bool]] = []

    def mark_finished(self, execution: object, *, success: bool) -> None:
        self.finished.append((execution, success))


class _SpinnerGroup:
    def __init__(self) -> None:
        self.finished: list[dict[str, object]] = []

    def mark_finished(self, execution: object, *, success: bool, duration_text: str, parsed: object | None) -> None:
        self.finished.append(
            {
                "execution": execution,
                "success": success,
                "duration_text": duration_text,
                "parsed": parsed,
            }
        )


class _Events:
    def __init__(self) -> None:
        self.summaries: list[tuple[object, object]] = []

    def emit_summary(self, execution: object, *, parsed: object) -> None:
        self.summaries.append((execution, parsed))


class TestSuitePresentationTests(unittest.TestCase):
    def _execution(self) -> SimpleNamespace:
        return SimpleNamespace(
            index=1,
            spec=SimpleNamespace(command=["python", "-m", "pytest"], cwd=Path("/repo/api"), source="backend_pytest"),
            args=["tests/api"],
            resolved_source="backend_pytest",
            project_name="api",
            project_root=Path("/repo/api"),
        )

    def test_render_command_joins_command_parts(self) -> None:
        self.assertEqual(render_command(["python", "-m", "pytest"]), "python -m pytest")

    def test_failure_label_includes_project_source_and_suite_index(self) -> None:
        execution = self._execution()
        presenter = TestSuitePresenter(
            orchestrator=_Orchestrator(),
            execution_specs=[execution, object()],
            failed_only=False,
            interactive_command=False,
            parallel=False,
            multi_project=True,
            use_suite_spinner_group=False,
            progress_tracker=_ProgressTracker(),
            suite_spinner_group=_SpinnerGroup(),
            events=_Events(),
        )

        self.assertEqual(presenter.failure_label(execution), "api:backend_pytest [1/2]")

    def test_emit_suite_summary_reports_counts_and_emits_event(self) -> None:
        execution = self._execution()
        orchestrator = _Orchestrator()
        events = _Events()
        presenter = TestSuitePresenter(
            orchestrator=orchestrator,
            execution_specs=[execution],
            failed_only=False,
            interactive_command=False,
            parallel=False,
            multi_project=False,
            use_suite_spinner_group=False,
            progress_tracker=_ProgressTracker(),
            suite_spinner_group=_SpinnerGroup(),
            events=events,
        )
        parsed = SimpleNamespace(counts_detected=True, passed=3, failed=1, skipped=0)

        presenter.emit_suite_summary(execution, parsed)

        self.assertEqual(orchestrator.statuses, ["api / backend_pytest summary: 3 passed, 1 failed, 0 skipped"])
        self.assertEqual(events.summaries, [(execution, parsed)])

    def test_mark_finished_routes_to_spinner_or_progress_owner(self) -> None:
        execution = self._execution()
        progress = _ProgressTracker()
        spinner = _SpinnerGroup()
        presenter = TestSuitePresenter(
            orchestrator=_Orchestrator(),
            execution_specs=[execution],
            failed_only=False,
            interactive_command=False,
            parallel=False,
            multi_project=False,
            use_suite_spinner_group=True,
            progress_tracker=progress,
            suite_spinner_group=spinner,
            events=_Events(),
        )

        presenter.mark_finished(execution, completed=SimpleNamespace(returncode=0), parsed=None, duration_ms=1250.0)

        self.assertEqual(progress.finished, [])
        self.assertEqual(len(spinner.finished), 1)
        self.assertTrue(spinner.finished[0]["success"])

    def test_announce_suite_start_suppresses_status_when_suite_spinner_group_is_active(self) -> None:
        execution = self._execution()
        orchestrator = _Orchestrator()
        presenter = TestSuitePresenter(
            orchestrator=orchestrator,
            execution_specs=[execution],
            failed_only=False,
            interactive_command=False,
            parallel=False,
            multi_project=True,
            use_suite_spinner_group=True,
            progress_tracker=_ProgressTracker(),
            suite_spinner_group=_SpinnerGroup(),
            events=_Events(),
        )

        presenter.announce_suite_start(execution, suite_label="backend_pytest", resolved_source="backend_pytest")

        self.assertEqual(orchestrator.statuses, [])

    def test_print_interactive_suite_finish_reports_unparsed_success_note(self) -> None:
        execution = self._execution()
        presenter = TestSuitePresenter(
            orchestrator=_Orchestrator(),
            execution_specs=[execution],
            failed_only=False,
            interactive_command=True,
            parallel=False,
            multi_project=False,
            use_suite_spinner_group=False,
            progress_tracker=_ProgressTracker(),
            suite_spinner_group=_SpinnerGroup(),
            events=_Events(),
        )

        with patch("builtins.print") as print_mock:
            presenter.print_interactive_suite_finish(
                execution,
                suite_label="backend_pytest",
                completed=SimpleNamespace(returncode=0),
                parsed=SimpleNamespace(counts_detected=False),
                duration_ms=10.0,
            )

        rendered = "\n".join(str(call.args[0]) for call in print_mock.call_args_list)
        self.assertIn("backend_pytest passed", rendered)
        self.assertIn("could not extract test counts", rendered)


if __name__ == "__main__":
    unittest.main()
