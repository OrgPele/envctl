from __future__ import annotations

import unittest

from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.textual.list_controller import TextualListController
from envctl_engine.ui.textual.screens.selector.support import _RowRef
from envctl_engine.ui.textual.screens.selector.textual_app_navigation_actions import (
    SelectorNavigationActions,
)


def _row(label: str, token: str, *, selected: bool = False) -> _RowRef:
    return _RowRef(
        item=SelectorItem(
            id=token,
            label=label,
            kind="project",
            token=token,
            scope_signature=(token,),
        ),
        selected=selected,
    )


class _ListView:
    def __init__(self, *, index: int | None = 0, has_focus: bool = True) -> None:
        self.index = index
        self.has_focus = has_focus


class SelectorNavigationActionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_nav_down_syncs_single_select_focus_and_emits_navigation_debug(self) -> None:
        rows = [_row("Alpha", "alpha", selected=True), _row("Beta", "beta"), _row("Gamma", "gamma")]
        list_view = _ListView(index=0, has_focus=True)
        controller = TextualListController(rows, initial_model_index=0)
        rendered = 0
        focus_calls: list[tuple[str, int | None]] = []
        last_user_indexes: list[int] = []
        nav_events: list[tuple[str, str]] = []
        debug_events: list[tuple[str, str, int | None]] = []
        sync_calls = 0

        async def render_rows() -> None:
            nonlocal rendered
            rendered += 1

        def sync_status() -> None:
            nonlocal sync_calls
            sync_calls += 1

        actions = SelectorNavigationActions(
            rows=rows,
            multi=False,
            controller=controller,
            list_view=list_view,
            render_rows=render_rows,
            focus_list=lambda *, reason, target_index=None: focus_calls.append((reason, target_index)),
            focused_widget_id=lambda: "selector-list",
            set_last_user_model_index=last_user_indexes.append,
            mark_navigation=lambda key, *, edge_hint="": nav_events.append((key, edge_hint)),
            sync_status=sync_status,
            emit_key_debug=lambda *, key, focus_before, list_index_before, handled: debug_events.append(
                (key, focus_before, list_index_before)
            ),
        )

        await actions.nav_down()

        self.assertEqual(list_view.index, 1)
        self.assertEqual([row.selected for row in rows], [False, True, False])
        self.assertEqual(rendered, 1)
        self.assertEqual(focus_calls, [("nav_down", None)])
        self.assertEqual(last_user_indexes, [1])
        self.assertEqual(nav_events, [("down", "")])
        self.assertEqual(debug_events, [("down", "selector-list", 0)])
        self.assertEqual(sync_calls, 1)

    async def test_nav_up_recovers_focus_and_reports_top_edge(self) -> None:
        rows = [_row("Alpha", "alpha", selected=True), _row("Beta", "beta")]
        list_view = _ListView(index=0, has_focus=False)
        controller = TextualListController(rows, initial_model_index=0)
        focus_calls: list[tuple[str, int | None]] = []
        nav_events: list[tuple[str, str]] = []

        actions = SelectorNavigationActions(
            rows=rows,
            multi=True,
            controller=controller,
            list_view=list_view,
            render_rows=lambda: _completed(),
            focus_list=lambda *, reason, target_index=None: focus_calls.append((reason, target_index)),
            focused_widget_id=lambda: "btn-run",
            set_last_user_model_index=lambda _index: None,
            mark_navigation=lambda key, *, edge_hint="": nav_events.append((key, edge_hint)),
            sync_status=lambda: None,
            emit_key_debug=lambda **_payload: None,
        )

        await actions.nav_up()

        self.assertEqual(focus_calls, [("key_recover", 0)])
        self.assertEqual(nav_events, [("up", "top boundary")])


async def _completed() -> None:
    return None


if __name__ == "__main__":
    unittest.main()
