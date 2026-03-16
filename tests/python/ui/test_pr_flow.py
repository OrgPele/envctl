from __future__ import annotations

import importlib.util
import unittest
from types import SimpleNamespace

from envctl_engine.ui.dashboard.pr_flow import run_pr_flow
from envctl_engine.ui.selector_model import SelectorItem


class PrFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_space_toggles_project_selection_before_enter(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        app = run_pr_flow(
            projects=[SimpleNamespace(name="Main"), SimpleNamespace(name="feature-a-1")],
            initial_project_names=[],
            branch_options=[
                SelectorItem(token="main", label="main"),
                SelectorItem(token="dev", label="dev"),
            ],
            default_branch="main",
            build_only=True,
        )

        async with app.run_test() as pilot:
            await pilot.press("down")
            await pilot.press("space")
            await pilot.pause()
            status = app.query_one("#selector-status")
            self.assertIn("1 selected", str(getattr(status, "renderable", "")))

    async def test_space_toggles_the_focused_project_not_the_top_row(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        app = run_pr_flow(
            projects=[SimpleNamespace(name="Main"), SimpleNamespace(name="feature-a-1")],
            initial_project_names=[],
            branch_options=[
                SelectorItem(token="main", label="main"),
                SelectorItem(token="dev", label="dev"),
            ],
            default_branch="main",
            build_only=True,
        )

        async with app.run_test() as pilot:
            await pilot.press("down")
            await pilot.press("space")
            await pilot.press("enter")
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(getattr(app, "return_value", None).project_names, ["feature-a-1"])
