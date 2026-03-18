from __future__ import annotations

import unittest
from unittest.mock import patch

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.ui.textual.screens.selector import (
    select_grouped_targets_textual,
    select_project_targets_textual,
)


class _Project:
    def __init__(self, name: str) -> None:
        self.name = name


class TextualSelectorFlowTests(unittest.TestCase):
    def test_project_selector_maps_untested_token_without_visible_all_shortcut(self) -> None:
        projects = [_Project("alpha"), _Project("beta")]
        captured = {}

        def fake_selector(*, prompt, options, multi, initial_tokens=None, emit=None):  # noqa: ANN001
            _ = prompt, multi, initial_tokens, emit
            captured["labels"] = [option.label for option in options]
            return ["__UNTESTED__"]

        with patch(
            "envctl_engine.ui.textual.screens.selector._run_selector_with_impl",
            side_effect=fake_selector,
        ):
            selection = select_project_targets_textual(
                prompt="Select test target",
                projects=projects,
                allow_all=True,
                allow_untested=True,
                multi=True,
            )

        self.assertEqual(captured["labels"], ["alpha", "beta"])
        self.assertFalse(selection.all_selected)
        self.assertTrue(selection.untested_selected)
        self.assertFalse(selection.cancelled)

    def test_project_selector_hides_all_for_single_project(self) -> None:
        projects = [_Project("alpha")]
        captured = {}

        def fake_selector(*, prompt, options, multi, initial_tokens=None, emit=None):  # noqa: ANN001
            _ = prompt, multi, initial_tokens, emit
            captured["labels"] = [option.label for option in options]
            return ["__PROJECT__:alpha"]

        with patch("envctl_engine.ui.textual.screens.selector._run_selector_with_impl", side_effect=fake_selector):
            selection = select_project_targets_textual(
                prompt="Select test target",
                projects=projects,
                allow_all=True,
                allow_untested=False,
                multi=True,
            )

        self.assertEqual(captured["labels"], ["alpha"])
        self.assertEqual(selection.project_names, ["alpha"])

    def test_grouped_selector_maps_project_and_service_tokens(self) -> None:
        projects = [_Project("Main")]
        with patch(
            "envctl_engine.ui.textual.screens.selector._run_selector_with_impl",
            return_value=["__PROJECT__:Main", "Main Backend"],
        ):
            selection = select_grouped_targets_textual(
                prompt="Restart",
                projects=projects,
                services=["Main Backend", "Main Frontend"],
                allow_all=True,
                multi=True,
            )

        self.assertEqual(selection.project_names, ["Main"])
        self.assertEqual(selection.service_names, ["Main Backend"])
        self.assertFalse(selection.cancelled)

    def test_grouped_selector_hides_duplicate_all_services_scope(self) -> None:
        projects = [_Project("Main")]
        captured = {}

        def fake_selector(*, prompt, options, multi, initial_tokens=None, emit=None):  # noqa: ANN001
            _ = prompt, multi, initial_tokens, emit
            captured["labels"] = [option.label for option in options]
            return ["__PROJECT__:Main"]

        with patch("envctl_engine.ui.textual.screens.selector._run_selector_with_impl", side_effect=fake_selector):
            selection = select_grouped_targets_textual(
                prompt="Restart",
                projects=projects,
                services=["Main Backend", "Main Frontend"],
                allow_all=True,
                multi=True,
            )

        self.assertNotIn("All services", captured["labels"])
        self.assertIn("Main - ALL", captured["labels"])
        self.assertEqual(selection.project_names, ["Main"])

    def test_selector_cancel_returns_cancelled_selection(self) -> None:
        projects = [_Project("alpha")]
        with patch(
            "envctl_engine.ui.textual.screens.selector._run_selector_with_impl",
            return_value=None,
        ):
            selection = select_project_targets_textual(
                prompt="Select test target",
                projects=projects,
                allow_all=True,
                allow_untested=False,
                multi=False,
            )

        self.assertTrue(selection.cancelled)
        self.assertFalse(selection.all_selected)

    def test_project_selector_passes_initial_project_tokens(self) -> None:
        projects = [_Project("alpha"), _Project("beta")]
        captured: dict[str, object] = {}

        def fake_selector(*, prompt, options, multi, initial_tokens=None, emit=None):  # noqa: ANN001
            _ = prompt, options, multi, emit
            captured["initial_tokens"] = list(initial_tokens or [])
            return ["__PROJECT__:beta"]

        with patch("envctl_engine.ui.textual.screens.selector._run_selector_with_impl", side_effect=fake_selector):
            selection = select_project_targets_textual(
                prompt="Select worktrees",
                projects=projects,
                allow_all=True,
                allow_untested=False,
                multi=True,
                initial_project_names=["beta"],
            )

        self.assertEqual(captured.get("initial_tokens"), ["__PROJECT__:beta"])
        self.assertEqual(selection.project_names, ["beta"])


if __name__ == "__main__":
    unittest.main()
