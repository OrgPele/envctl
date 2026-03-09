from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.ui.target_selector import TargetSelection, TargetSelector


class TargetSelectorTests(unittest.TestCase):
    def test_project_target_all_selection_sets_all(self) -> None:
        projects = [SimpleNamespace(name="alpha"), SimpleNamespace(name="beta")]
        selector = TargetSelector()

        with patch(
            "envctl_engine.ui.target_selector.select_project_targets_textual",
            return_value=TargetSelection(all_selected=True, project_names=[]),
        ):
            selection = selector.select_project_targets(
                prompt="Run tests for",
                projects=projects,
                allow_all=True,
                allow_untested=False,
                multi=True,
            )

        self.assertTrue(selection.all_selected)
        self.assertEqual(selection.project_names, [])

    def test_project_target_specific_project(self) -> None:
        projects = [SimpleNamespace(name="alpha"), SimpleNamespace(name="beta")]
        selector = TargetSelector()

        with patch(
            "envctl_engine.ui.target_selector.select_project_targets_textual",
            return_value=TargetSelection(all_selected=False, project_names=["alpha"]),
        ):
            selection = selector.select_project_targets(
                prompt="Create PR for",
                projects=projects,
                allow_all=True,
                allow_untested=False,
                multi=False,
            )

        self.assertFalse(selection.all_selected)
        self.assertEqual(selection.project_names, ["alpha"])

    def test_grouped_target_service_selection(self) -> None:
        projects = [SimpleNamespace(name="alpha")]
        services = ["alpha backend", "alpha frontend"]
        selector = TargetSelector()

        with patch(
            "envctl_engine.ui.target_selector.select_grouped_targets_textual",
            return_value=TargetSelection(service_names=["alpha backend"], project_names=[]),
        ):
            selection = selector.select_grouped_targets(
                prompt="Tail logs for",
                projects=projects,
                services=services,
                allow_all=True,
                multi=True,
            )

        self.assertEqual(selection.service_names, ["alpha backend"])
        self.assertEqual(selection.project_names, [])

    def test_selection_cancelled(self) -> None:
        projects = [SimpleNamespace(name="alpha")]
        selector = TargetSelector()

        with patch(
            "envctl_engine.ui.target_selector.select_project_targets_textual",
            return_value=TargetSelection(cancelled=True),
        ):
            selection = selector.select_project_targets(
                prompt="Review changes for",
                projects=projects,
                allow_all=True,
                allow_untested=False,
                multi=False,
            )

        self.assertTrue(selection.cancelled)


if __name__ == "__main__":
    unittest.main()
