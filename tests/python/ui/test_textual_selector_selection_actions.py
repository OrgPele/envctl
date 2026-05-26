from __future__ import annotations

import unittest
from types import SimpleNamespace

from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.textual.screens.selector.support import _RowRef
from envctl_engine.ui.textual.screens.selector.textual_app_selection_actions import (
    SelectorSelectionActions,
    selector_row_model_index_from_widget,
)


def _row(label: str, token: str, *, selected: bool = False, visible: bool = True) -> _RowRef:
    return _RowRef(
        item=SelectorItem(
            id=token,
            label=label,
            kind="project",
            token=token,
            scope_signature=(token,),
        ),
        selected=selected,
        visible=visible,
    )


class SelectorSelectionActionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_toggle_model_index_emits_and_rerenders_selection(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        renders = 0
        focus_reasons: list[str] = []
        rows = [_row("Alpha", "alpha"), _row("Beta", "beta")]

        async def render_rows() -> None:
            nonlocal renders
            renders += 1

        actions = SelectorSelectionActions(
            rows=rows,
            prompt="Run tests",
            multi=True,
            exclusive_token=None,
            emit=lambda event, **payload: events.append((event, dict(payload))),
            render_rows=render_rows,
            focus_list=lambda *, reason: focus_reasons.append(reason),
        )

        self.assertTrue(await actions.toggle_model_index(1))

        self.assertFalse(rows[0].selected)
        self.assertTrue(rows[1].selected)
        self.assertEqual(renders, 1)
        self.assertEqual(focus_reasons, ["toggle"])
        self.assertEqual(events[0][0], "ui.selection.interaction")
        self.assertEqual(events[0][1]["action"], "toggle")
        self.assertEqual(events[0][1]["token"], "beta")
        self.assertEqual(events[1][0], "ui.selection.toggle")
        self.assertEqual(events[1][1]["token"], "beta")
        self.assertEqual(events[1][1]["selected"], True)

    async def test_list_selection_reports_out_of_range_without_mutating_rows(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        renders = 0
        focus_reasons: list[str] = []
        rows = [_row("Alpha", "alpha")]

        async def render_rows() -> None:
            nonlocal renders
            renders += 1

        actions = SelectorSelectionActions(
            rows=rows,
            prompt="Run tests",
            multi=False,
            exclusive_token=None,
            emit=lambda event, **payload: events.append((event, dict(payload))),
            render_rows=render_rows,
            focus_list=lambda *, reason: focus_reasons.append(reason),
        )

        self.assertFalse(await actions.handle_list_selection(list_index=2, index_map=[0]))

        self.assertFalse(rows[0].selected)
        self.assertEqual(renders, 0)
        self.assertEqual(focus_reasons, [])
        self.assertEqual(events[0][1]["action"], "list_selected")
        self.assertEqual(events[1][1]["action"], "list_selected_out_of_range")
        self.assertEqual(events[1][1]["visible_count"], 1)

    def test_selector_row_model_index_from_widget_walks_parent_chain(self) -> None:
        row_widget = SimpleNamespace(id="selector-row-3", parent=None)
        child = SimpleNamespace(id="", parent=row_widget)
        root = SimpleNamespace(id="root", parent=child)

        self.assertEqual(selector_row_model_index_from_widget(root, row_count=4), 3)
        self.assertIsNone(selector_row_model_index_from_widget(root, row_count=3))
        self.assertIsNone(selector_row_model_index_from_widget(SimpleNamespace(id="selector-row-x"), row_count=4))


if __name__ == "__main__":
    unittest.main()
