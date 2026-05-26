from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from envctl_engine.ui.textual.list_controller import TextualListController
from envctl_engine.ui.textual.list_row_styles import apply_selectable_list_index, focus_selectable_list
from envctl_engine.ui.textual.screens.selector.textual_app_runtime import SelectorFocusController


@dataclass(slots=True)
class SelectorFocusActions:
    app: Any
    controller: TextualListController[Any]
    focus_controller: SelectorFocusController
    list_view: Callable[[], Any]
    filter_input: Callable[[], Any]
    button: Callable[[str], Any]
    run_button: Callable[[], Any]
    current_focused: Callable[[], Any]
    set_allow_filter_focus: Callable[[bool], None]

    def focus_filter(self, *, reason: str = "focus_filter") -> None:
        filter_input = self.filter_input()
        self.set_allow_filter_focus(True)
        filter_input.can_focus = True
        filter_input.focus()
        self._emit_focus(reason=reason)

    def focus_list(self, *, reason: str = "focus_list", target_index: int | None = None) -> None:
        list_view = self.list_view()
        index = self.controller.ensure_list_index(target_index if target_index is not None else list_view.index)
        apply_selectable_list_index(list_view, index)
        self.set_allow_filter_focus(False)
        focus_selectable_list(self.app, list_view, index)
        self._emit_focus(reason=reason)

    def focus_button(self, button_id: str, *, reason: str) -> None:
        self.set_allow_filter_focus(False)
        self.button(button_id).focus()
        self._emit_focus(reason=reason)

    def cycle_focus(self) -> None:
        next_target = self.controller.cycle_focus_target(
            current_target=self.focused_widget_id(),
            focus_order=self.focus_order(),
        )
        if next_target == "selector-list":
            self.focus_list(reason="tab_cycle")
        elif next_target == "selector-filter":
            self.focus_filter(reason="tab_cycle")
        else:
            self.focus_button(next_target, reason="tab_cycle")

    def focused_widget_id(self) -> str:
        return self.focus_controller.widget_id(
            focused=self.current_focused(),
            list_has_focus=bool(getattr(self.list_view(), "has_focus", False)),
            filter_has_focus=bool(getattr(self.filter_input(), "has_focus", False)),
        )

    def focus_order(self) -> tuple[str, ...]:
        return self.focus_controller.focus_order(
            run_enabled=not bool(getattr(self.run_button(), "disabled", False)),
        )

    def _emit_focus(self, *, reason: str) -> None:
        self.focus_controller.emit_focus(
            reason=reason,
            current_widget_id=self.focused_widget_id(),
        )
