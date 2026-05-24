from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.actions.action_test_spinner_support import TestSuiteSpinnerGroup as SuiteSpinnerGroup
from envctl_engine.actions.action_test_spinner_support import rich_progress_available


class ActionTestSpinnerSupportTests(unittest.TestCase):
    def test_disabled_spinner_group_still_emits_lifecycle_updates(self) -> None:
        events: list[dict[str, object]] = []
        execution = SimpleNamespace(
            index=3,
            project_name="Main",
            spec=SimpleNamespace(source="backend_pytest"),
        )
        group = SuiteSpinnerGroup(
            execution_specs=[execution],
            enabled=False,
            policy=SimpleNamespace(backend="rich", style="dots"),
            emit=lambda event, **payload: events.append({"event": event, **payload}),
            suite_label_resolver=lambda source: f"label:{source}",
            multi_project=False,
            env={},
        )

        with group:
            group.mark_running(execution)
            group.mark_progress(execution, status_text="12 discovered")
            group.mark_finished(execution, success=True, duration_text="1.2s", parsed=None)

        messages = [str(event.get("message", "")) for event in events]
        self.assertIn("Main / label:backend_pytest: running", messages)
        self.assertIn("Main / label:backend_pytest: 12 discovered", messages)
        self.assertIn("Main / label:backend_pytest: passed (1.2s)", messages)
        self.assertTrue(all(event.get("component") == "action.test.parallel" for event in events))

    def test_markup_helpers_escape_project_and_color_suite_types(self) -> None:
        group = SuiteSpinnerGroup(
            execution_specs=[],
            enabled=False,
            policy=SimpleNamespace(backend="rich", style="dots"),
            emit=None,
            suite_label_resolver=lambda source: source,
            multi_project=False,
            env={},
        )

        self.assertEqual(group._escape_markup(r"a[b]\\c"), r"a\[b\]\\\\c")
        self.assertEqual(group._suite_color("backend_pytest"), "cyan")
        self.assertEqual(group._suite_color("frontend_package_test"), "magenta")
        self.assertEqual(group._suite_color("package_test"), "blue")
        self.assertEqual(group._suite_color("configured"), "yellow")

    def test_rich_progress_available_reports_find_spec_errors(self) -> None:
        with patch("envctl_engine.actions.action_test_spinner_support.importlib.util.find_spec") as find_spec:
            find_spec.side_effect = RuntimeError("boom")

            available, reason = rich_progress_available()

        self.assertFalse(available)
        self.assertEqual(reason, "find_spec_error:RuntimeError")


if __name__ == "__main__":
    unittest.main()
