from __future__ import annotations

import unittest

from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.textual.list_controller import TextualListController
from envctl_engine.ui.textual.screens.selector.support import _RowRef
from envctl_engine.ui.textual.screens.selector.textual_app_focus_actions import SelectorFocusActions
from envctl_engine.ui.textual.screens.selector.textual_app_runtime import SelectorFocusController


class _Widget:
    def __init__(self, *, widget_id: str = "", disabled: bool = False, has_focus: bool = False) -> None:
        self.id = widget_id
        self.can_focus = False
        self.disabled = disabled
        self.has_focus = has_focus
        self.focused = False

    def focus(self) -> None:
        self.focused = True
        self.has_focus = True


class _ListWidget(_Widget):
    def __init__(self, *, index: int | None = None, has_focus: bool = False) -> None:
        super().__init__(widget_id="selector-list", has_focus=has_focus)
        self.index = index


class _App:
    def __init__(self) -> None:
        self.focused_widget: object | None = None

    def set_focus(self, widget: object | None, scroll_visible: bool = False) -> None:
        self.focused_widget = widget
        setattr(widget, "has_focus", True)


def _rows(count: int) -> list[_RowRef]:
    return [
        _RowRef(
            item=SelectorItem(
                id=f"item-{idx}",
                label=f"Item {idx}",
                kind="project",
                token=f"item-{idx}",
                scope_signature=(f"item-{idx}",),
            )
        )
        for idx in range(count)
    ]


class SelectorFocusActionsTests(unittest.TestCase):
    def test_focus_filter_enables_filter_focus_and_emits_reason(self) -> None:
        filter_input = _Widget(widget_id="selector-filter")
        list_view = _ListWidget(index=0)
        run_button = _Widget()
        emitted: list[str] = []
        allow_values: list[bool] = []

        actions = SelectorFocusActions(
            app=_App(),
            controller=TextualListController(_rows(1), initial_model_index=0),
            focus_controller=SelectorFocusController(
                emit=lambda _event, **payload: emitted.append(str(payload["reason"])),
                deep_debug=True,
                selector_id="selector",
                initial_widget_id="selector-list",
            ),
            list_view=lambda: list_view,
            filter_input=lambda: filter_input,
            button=lambda _button_id: run_button,
            run_button=lambda: run_button,
            current_focused=lambda: filter_input,
            set_allow_filter_focus=allow_values.append,
        )

        actions.focus_filter(reason="slash_focus_filter")

        self.assertEqual(allow_values, [True])
        self.assertTrue(filter_input.can_focus)
        self.assertTrue(filter_input.focused)
        self.assertEqual(emitted, ["slash_focus_filter"])

    def test_focus_list_restores_index_and_disables_filter_focus(self) -> None:
        app = _App()
        list_view = _ListWidget(index=None)
        run_button = _Widget(widget_id="btn-run")
        emitted: list[str] = []
        allow_values: list[bool] = []

        actions = SelectorFocusActions(
            app=app,
            controller=TextualListController(_rows(2), initial_model_index=1),
            focus_controller=SelectorFocusController(
                emit=lambda _event, **payload: emitted.append(str(payload["reason"])),
                deep_debug=True,
                selector_id="selector",
                initial_widget_id="selector-filter",
            ),
            list_view=lambda: list_view,
            filter_input=lambda: _Widget(widget_id="selector-filter"),
            button=lambda _button_id: run_button,
            run_button=lambda: run_button,
            current_focused=lambda: list_view,
            set_allow_filter_focus=allow_values.append,
        )
        actions.controller.index_map = [0, 1]

        actions.focus_list(reason="nav_down", target_index=1)

        self.assertEqual(list_view.index, 1)
        self.assertTrue(list_view.focused)
        self.assertEqual(allow_values, [False])
        self.assertEqual(emitted, ["nav_down"])

    def test_cycle_focus_uses_focus_order_and_run_button_state(self) -> None:
        list_view = _ListWidget(index=0, has_focus=True)
        filter_input = _Widget(widget_id="selector-filter")
        run_button = _Widget(widget_id="btn-run", disabled=False)
        cancel_button = _Widget(widget_id="btn-cancel")
        emitted: list[str] = []

        actions = SelectorFocusActions(
            app=_App(),
            controller=TextualListController(_rows(1), initial_model_index=0),
            focus_controller=SelectorFocusController(
                emit=lambda _event, **payload: emitted.append(str(payload["reason"])),
                deep_debug=True,
                selector_id="selector",
                initial_widget_id="selector-list",
            ),
            list_view=lambda: list_view,
            filter_input=lambda: filter_input,
            button=lambda button_id: run_button if button_id == "btn-run" else cancel_button,
            run_button=lambda: run_button,
            current_focused=lambda: (
                filter_input
                if filter_input.has_focus
                else cancel_button
                if cancel_button.has_focus
                else list_view
            ),
            set_allow_filter_focus=lambda _value: None,
        )

        actions.cycle_focus()
        run_button.disabled = True
        list_view.has_focus = False
        cancel_button.has_focus = True
        actions.cycle_focus()

        self.assertTrue(cancel_button.focused)
        self.assertTrue(filter_input.focused)
        self.assertEqual(emitted, ["tab_cycle", "tab_cycle"])


if __name__ == "__main__":
    unittest.main()
