from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from envctl_engine.ui.textual.list_row_styles import apply_selectable_list_index


@dataclass(slots=True)
class SelectorInitialNavigationRunner:
    actions: Sequence[str]
    rows: Sequence[Any]
    multi: bool
    controller: Any
    list_view: object
    focus_list: Callable[..., None]
    mark_navigation: Callable[[str], None]
    focused_model_index: Callable[[], int | None]
    set_last_user_model_index: Callable[[int], None]
    sync_status: Callable[[], None]
    schedule_render: Callable[[], None]
    schedule_submit: Callable[[], None]

    def apply(self) -> None:
        if not self.actions:
            return
        self.focus_list(reason="initial_navigation")
        submit_requested = False
        selection_changed = False
        for action in self.actions:
            if action == "submit":
                submit_requested = True
                continue
            selection_changed = self._apply_cursor_action(action) or selection_changed
        self.sync_status()
        if selection_changed:
            self.schedule_render()
        if submit_requested:
            self.schedule_submit()

    def _apply_cursor_action(self, action: str) -> bool:
        list_index_before = self.controller.ensure_list_index(getattr(self.list_view, "index", None))
        if action == "down":
            target_index = self.controller.cursor_down(list_index_before)
        elif action == "up":
            target_index = self.controller.cursor_up(list_index_before)
        else:
            return False
        apply_selectable_list_index(self.list_view, target_index)
        self.mark_navigation(action)
        return self._sync_single_select_focus()

    def _sync_single_select_focus(self) -> bool:
        model_index = self.focused_model_index()
        if model_index is not None:
            self.set_last_user_model_index(model_index)
        if self.multi or model_index is None or model_index < 0 or model_index >= len(self.rows):
            return False
        selection_changed = False
        for idx, row in enumerate(self.rows):
            selected = idx == model_index
            if bool(getattr(row, "selected", False)) != selected:
                setattr(row, "selected", selected)
                selection_changed = True
        return selection_changed
