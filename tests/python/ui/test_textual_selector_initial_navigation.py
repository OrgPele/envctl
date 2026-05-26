from __future__ import annotations

import unittest

from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.textual.list_controller import TextualListController
from envctl_engine.ui.textual.screens.selector.support import _RowRef
from envctl_engine.ui.textual.screens.selector.textual_app_initial_navigation import (
    SelectorInitialNavigationRunner,
)


def _item(value: str, label: str) -> SelectorItem:
    return SelectorItem(
        id=value,
        label=label,
        kind="project",
        token=value,
        scope_signature=(f"project:{value}",),
    )


class _ListView:
    index: int | None = 0


class SelectorInitialNavigationRunnerTests(unittest.TestCase):
    def test_single_select_navigation_updates_focus_selection_and_status(self) -> None:
        rows = [
            _RowRef(_item("a", "Alpha"), selected=True),
            _RowRef(_item("b", "Beta"), selected=False),
            _RowRef(_item("c", "Gamma"), selected=False),
        ]
        list_view = _ListView()
        controller = TextualListController(rows, initial_model_index=0)
        focused_indexes: list[int] = []
        nav_keys: list[str] = []
        focus_reasons: list[str] = []
        sync_calls = 0
        render_calls = 0
        submit_calls = 0

        def sync_status() -> None:
            nonlocal sync_calls
            sync_calls += 1

        def schedule_render() -> None:
            nonlocal render_calls
            render_calls += 1

        def schedule_submit() -> None:
            nonlocal submit_calls
            submit_calls += 1

        SelectorInitialNavigationRunner(
            actions=("down", "down", "up"),
            rows=rows,
            multi=False,
            controller=controller,
            list_view=list_view,
            focus_list=lambda *, reason: focus_reasons.append(reason),
            mark_navigation=nav_keys.append,
            focused_model_index=lambda: controller.focused_model_index(list_view.index),
            set_last_user_model_index=focused_indexes.append,
            sync_status=sync_status,
            schedule_render=schedule_render,
            schedule_submit=schedule_submit,
        ).apply()

        self.assertEqual(list_view.index, 1)
        self.assertEqual([row.selected for row in rows], [False, True, False])
        self.assertEqual(focused_indexes, [1, 2, 1])
        self.assertEqual(nav_keys, ["down", "down", "up"])
        self.assertEqual(focus_reasons, ["initial_navigation"])
        self.assertEqual(sync_calls, 1)
        self.assertEqual(render_calls, 1)
        self.assertEqual(submit_calls, 0)

    def test_submit_action_schedules_submit_without_forcing_multi_selection_change(self) -> None:
        rows = [
            _RowRef(_item("a", "Alpha"), selected=True),
            _RowRef(_item("b", "Beta"), selected=True),
        ]
        list_view = _ListView()
        controller = TextualListController(rows, initial_model_index=0)
        render_calls = 0
        submit_calls = 0

        def schedule_render() -> None:
            nonlocal render_calls
            render_calls += 1

        def schedule_submit() -> None:
            nonlocal submit_calls
            submit_calls += 1

        SelectorInitialNavigationRunner(
            actions=("down", "submit", "ignored"),
            rows=rows,
            multi=True,
            controller=controller,
            list_view=list_view,
            focus_list=lambda *, reason: None,
            mark_navigation=lambda _key: None,
            focused_model_index=lambda: controller.focused_model_index(list_view.index),
            set_last_user_model_index=lambda _index: None,
            sync_status=lambda: None,
            schedule_render=schedule_render,
            schedule_submit=schedule_submit,
        ).apply()

        self.assertEqual(list_view.index, 1)
        self.assertEqual([row.selected for row in rows], [True, True])
        self.assertEqual(render_calls, 0)
        self.assertEqual(submit_calls, 1)


if __name__ == "__main__":
    unittest.main()
