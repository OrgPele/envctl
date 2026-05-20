from __future__ import annotations

import unittest

from envctl_engine.actions.action_summary_support import (
    format_summary_error_lines,
    migrate_failure_headline,
)


class ActionSummarySupportTests(unittest.TestCase):
    def test_format_summary_error_lines_omits_terminal_chrome_and_compacts_long_assertions(self) -> None:
        lines = format_summary_error_lines(
            "\n".join(
                [
                    "----------------------------------------------------------------------",
                    "Traceback (most recent call last):",
                    'AssertionError: Regex didn\'t match: something not found in "\\x1b[48;2;39;39;39m..."',
                    "  ╭────────────────────────────────────────────────────╮",
                    "  │  Run tests for                                    │",
                    "RESULT_SERVICES=Main Admin",
                    'File "/tmp/test.py", line 10, in test_case',
                ]
            )
        )
        rendered = "\n".join(lines)

        self.assertIn("Traceback (most recent call last):", rendered)
        self.assertIn("AssertionError: Regex didn't match: something not found in <omitted output>", rendered)
        self.assertIn('File "/tmp/test.py", line 10, in test_case', rendered)
        self.assertNotIn("------", rendered)
        self.assertNotIn("Run tests for", rendered)
        self.assertNotIn("RESULT_SERVICES=", rendered)

    def test_format_summary_error_lines_keeps_user_frames_exception_body_and_captured_output(self) -> None:
        lines = format_summary_error_lines(
            "\n".join(
                [
                    "Traceback (most recent call last):",
                    'File "/Users/kfiramar/projects/envctl/python/envctl_engine/ui/foo.py", line 10, in helper',
                    "do_the_thing()",
                    'File "/Users/kfiramar/projects/envctl/tests/python/ui/test_selector.py", line 274, in test_click',
                    'self.assertEqual(app.return_value, ["beta"])',
                    "AssertionError: None != ['beta']",
                    "Captured stdout call",
                    "selector state before click: focused=selector-row-1",
                    "Captured stderr call",
                    "mouse event propagated",
                ]
            )
        )
        rendered = "\n".join(lines)

        self.assertIn('File "/Users/kfiramar/projects/envctl/python/envctl_engine/ui/foo.py", line 10, in helper', rendered)
        self.assertIn('File "/Users/kfiramar/projects/envctl/tests/python/ui/test_selector.py", line 274, in test_click', rendered)
        self.assertIn('self.assertEqual(app.return_value, ["beta"])', rendered)
        self.assertIn("AssertionError: None != ['beta']", rendered)
        self.assertIn("Captured stdout call", rendered)
        self.assertIn("selector state before click: focused=selector-row-1", rendered)
        self.assertIn("Captured stderr call", rendered)
        self.assertIn("mouse event propagated", rendered)

    def test_migrate_failure_headline_prefers_exception_line(self) -> None:
        headline = migrate_failure_headline(
            "\n".join(
                [
                    "Traceback (most recent call last):",
                    'File "/tmp/repo/backend/alembic/env.py", line 10, in <module>',
                    "load_settings()",
                    "pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings",
                ]
            )
        )

        self.assertEqual(
            headline,
            "pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings",
        )


if __name__ == "__main__":
    unittest.main()
