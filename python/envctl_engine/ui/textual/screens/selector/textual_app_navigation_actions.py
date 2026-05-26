from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from envctl_engine.ui.textual.list_controller import TextualListController
from envctl_engine.ui.textual.screens.selector.support import _RowRef


@dataclass(slots=True)
class SelectorNavigationActions:
    rows: Sequence[_RowRef]
    multi: bool
    controller: TextualListController[_RowRef]
    list_view: Any
    render_rows: Callable[[], Awaitable[None]]
    focus_list: Callable[..., None]
    focused_widget_id: Callable[[], str]
    set_last_user_model_index: Callable[[int], None]
    mark_navigation: Callable[..., None]
    sync_status: Callable[[], None]
    emit_key_debug: Callable[..., None]

    async def nav_up(self) -> None:
        list_index_before = self.controller.ensure_list_index(self.list_view.index)
        focus_before = self.focused_widget_id()
        if not bool(getattr(self.list_view, "has_focus", False)):
            target_index = self.controller.cursor_up(list_index_before)
            self.focus_list(reason="key_recover", target_index=target_index)
        else:
            self.list_view.index = self.controller.cursor_up(self.list_view.index)
        list_index_after = self.list_view.index
        at_top_edge = list_index_before is not None and list_index_after == list_index_before == 0
        await self._after_navigation(
            key="up",
            edge_hint="top boundary" if at_top_edge else "",
            focus_before=focus_before,
            list_index_before=list_index_before,
            sync_reason="nav_up",
        )

    async def nav_down(self) -> None:
        list_index_before = self.controller.ensure_list_index(self.list_view.index)
        focus_before = self.focused_widget_id()
        if not bool(getattr(self.list_view, "has_focus", False)):
            target_index = self.controller.cursor_down(list_index_before)
            self.focus_list(reason="key_recover", target_index=target_index)
        else:
            self.list_view.index = self.controller.cursor_down(self.list_view.index)
        list_index_after = self.list_view.index
        max_view_index = len(self.controller.index_map) - 1
        at_bottom_edge = (
            list_index_before is not None
            and max_view_index >= 0
            and list_index_after == list_index_before == max_view_index
        )
        await self._after_navigation(
            key="down",
            edge_hint="bottom boundary" if at_bottom_edge else "",
            focus_before=focus_before,
            list_index_before=list_index_before,
            sync_reason="nav_down",
        )

    async def sync_single_select_focus_selection(self, *, reason: str) -> None:
        if self.multi:
            return
        model_index = self._focused_model_index()
        if model_index is None or model_index < 0 or model_index >= len(self.rows):
            return
        changed = False
        for idx, row in enumerate(self.rows):
            selected = idx == model_index
            if row.selected != selected:
                row.selected = selected
                changed = True
        if not changed:
            return
        await self.render_rows()
        self.focus_list(reason=reason)

    def ignore_escape(self) -> None:
        list_index_before = self.list_view.index
        focus_before = self.focused_widget_id()
        if not bool(getattr(self.list_view, "has_focus", False)):
            self.focus_list(reason="escape_recover")
        self.emit_key_debug(
            key="escape",
            focus_before=focus_before,
            list_index_before=list_index_before,
            handled=True,
        )

    async def _after_navigation(
        self,
        *,
        key: str,
        edge_hint: str,
        focus_before: str,
        list_index_before: int | None,
        sync_reason: str,
    ) -> None:
        focused_model_index = self._focused_model_index()
        if focused_model_index is not None:
            self.set_last_user_model_index(focused_model_index)
        await self.sync_single_select_focus_selection(reason=sync_reason)
        self.mark_navigation(key, edge_hint=edge_hint)
        self.sync_status()
        self.emit_key_debug(
            key=key,
            focus_before=focus_before,
            list_index_before=list_index_before,
            handled=True,
        )

    def _focused_model_index(self) -> int | None:
        return self.controller.focused_model_index(self.list_view.index)
