from __future__ import annotations

from pathlib import Path
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.ui.textual.screens import selector  # noqa: E402
from envctl_engine.ui.textual.screens.selector import implementation  # noqa: E402


class SelectorPackageExportTests(unittest.TestCase):
    def test_package_reexports_private_debug_helpers(self) -> None:
        helper_names = [
            "_deep_debug_enabled",
            "_guard_textual_nonblocking_read",
            "_instrument_textual_parser_keys",
            "_selector_disable_focus_reporting_enabled",
            "_selector_driver_thread_snapshot",
            "_selector_driver_trace_enabled",
            "_selector_key_trace_enabled",
            "_selector_key_trace_verbose_enabled",
            "_selector_thread_stack_enabled",
        ]

        for helper_name in helper_names:
            with self.subTest(helper_name=helper_name):
                self.assertIs(getattr(selector, helper_name), getattr(implementation, helper_name))

    def test_package_reexports_public_selector_entrypoints(self) -> None:
        self.assertIs(selector.select_grouped_targets_textual, implementation.select_grouped_targets_textual)
        self.assertIs(selector.select_project_targets_textual, implementation.select_project_targets_textual)


if __name__ == "__main__":
    unittest.main()
