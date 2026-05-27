from __future__ import annotations

import importlib.util
import unittest
from types import SimpleNamespace

from envctl_engine.ui.dashboard.pr_flow import run_pr_flow
from envctl_engine.ui.dashboard.pr_flow_state import PrFlowState
from envctl_engine.ui.dashboard.pr_flow_state import build_branch_rows
from envctl_engine.ui.dashboard.pr_flow_state import build_project_rows
from envctl_engine.ui.selector_model import SelectorItem


def _branch_option(name: str) -> SelectorItem:
    return SelectorItem(
        id=f"branch:{name}",
        label=name,
        kind="branch",
        token=name,
        scope_signature=(f"branch:{name}",),
    )


class PrFlowTests(unittest.IsolatedAsyncioTestCase):
    def test_project_rows_trim_and_match_initial_selection_case_insensitively(self) -> None:
        rows = build_project_rows(
            [
                SimpleNamespace(name=" Main "),
                SimpleNamespace(name=""),
                SimpleNamespace(name="feature-a-1"),
            ],
            initial_project_names=["main"],
        )

        self.assertEqual([row.token for row in rows], ["Main", "feature-a-1"])
        self.assertEqual([row.selected for row in rows], [True, False])

    def test_branch_rows_fall_back_to_token_label_and_select_default(self) -> None:
        rows = build_branch_rows(
            [
                SelectorItem(
                    id="branch:main",
                    label="",
                    kind="branch",
                    token="main",
                    scope_signature=("branch:main",),
                ),
                _branch_option("release"),
            ],
            default_branch="main",
        )

        self.assertEqual(
            [(row.token, row.label, row.selected) for row in rows],
            [("main", "main", True), ("release", "release", False)],
        )

    def test_state_keeps_selection_rules_outside_textual_app(self) -> None:
        project_rows = build_project_rows(
            [SimpleNamespace(name="Main"), SimpleNamespace(name="feature-a-1")],
            initial_project_names=[],
        )
        branch_rows = build_branch_rows(
            [_branch_option("main"), _branch_option("dev")],
            default_branch="main",
        )
        state = PrFlowState.create(project_rows=project_rows, branch_rows=branch_rows)

        self.assertEqual(state.step, "project")
        state.toggle_row(project_rows[1])
        self.assertEqual(state.selected_projects(), ["feature-a-1"])
        self.assertTrue(state.advance_to_branch_if_ready())
        state.toggle_row(branch_rows[1])

        result = state.result()
        self.assertEqual(result.project_names, ["feature-a-1"])
        self.assertEqual(result.base_branch, "dev")

    def test_single_project_state_starts_at_branch_step_with_selected_project(self) -> None:
        project_rows = build_project_rows([SimpleNamespace(name="Main")], initial_project_names=[])
        branch_rows = build_branch_rows([_branch_option("main")], default_branch="main")

        state = PrFlowState.create(project_rows=project_rows, branch_rows=branch_rows)

        self.assertEqual(state.step, "branch")
        self.assertEqual(state.selected_projects(), ["Main"])
        self.assertFalse(state.can_go_back())
        self.assertEqual(state.result().project_names, ["Main"])

    async def test_space_toggles_project_selection_before_enter(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        app = run_pr_flow(
            projects=[SimpleNamespace(name="Main"), SimpleNamespace(name="feature-a-1")],
            initial_project_names=[],
            branch_options=[
                _branch_option("main"),
                _branch_option("dev"),
            ],
            default_branch="main",
            build_only=True,
        )

        async with app.run_test() as pilot:
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("space")
            await pilot.pause()
            status = app.query_one("#selector-status")
            self.assertIn("1 selected", str(status.render()))

    async def test_space_toggles_the_focused_project_not_the_top_row(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        app = run_pr_flow(
            projects=[SimpleNamespace(name="Main"), SimpleNamespace(name="feature-a-1")],
            initial_project_names=[],
            branch_options=[
                _branch_option("main"),
                _branch_option("dev"),
            ],
            default_branch="main",
            build_only=True,
        )

        async with app.run_test() as pilot:
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("space")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(getattr(app, "return_value", None).project_names, ["feature-a-1"])

    async def test_single_project_flow_creates_for_that_project(self) -> None:
        if importlib.util.find_spec("textual") is None:
            self.skipTest("textual is not installed")

        app = run_pr_flow(
            projects=[SimpleNamespace(name="Main")],
            initial_project_names=[],
            branch_options=[_branch_option("main")],
            default_branch="main",
            build_only=True,
        )

        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()
            result = getattr(app, "return_value", None)
            self.assertEqual(result.project_names, ["Main"])
            self.assertEqual(result.base_branch, "main")
