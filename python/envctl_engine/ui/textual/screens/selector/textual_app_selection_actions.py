from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from envctl_engine.ui.textual.screens.selector import selection_state
from envctl_engine.ui.textual.screens.selector.support import _RowRef, _emit


@dataclass(slots=True)
class SelectorSelectionActions:
    rows: Sequence[_RowRef]
    prompt: str
    multi: bool
    exclusive_token: str | None
    emit: Callable[..., None] | None
    render_rows: Callable[[], Awaitable[None]]
    focus_list: Callable[..., None]

    async def toggle_model_index(self, model_index: int) -> bool:
        row = selection_state.toggle_selector_model_index(
            self.rows,
            model_index,
            multi=self.multi,
            exclusive_token=self.exclusive_token,
        )
        if row is None:
            return False
        self._emit_selection_action(
            action="toggle",
            model_index=model_index,
            token=row.item.token,
            selected=row.selected,
        )
        _emit(self.emit, "ui.selection.toggle", token=row.item.token, selected=row.selected)
        await self.render_rows()
        self.focus_list(reason="toggle")
        return True

    async def select_model_index(self, model_index: int) -> bool:
        row = selection_state.select_selector_model_index(self.rows, model_index, multi=self.multi)
        if row is None:
            return False
        self._emit_selection_action(
            action="select",
            model_index=model_index,
            token=row.item.token,
            selected=True,
        )
        _emit(self.emit, "ui.selection.toggle", token=row.item.token, selected=True)
        await self.render_rows()
        return True

    async def toggle_visible(self) -> bool:
        should_select = selection_state.toggle_visible_selector_rows(
            self.rows,
            multi=self.multi,
            exclusive_token=self.exclusive_token,
        )
        if should_select is None:
            return False
        _emit(self.emit, "ui.selection.toggle", token="__VISIBLE__", selected=should_select)
        await self.render_rows()
        self.focus_list(reason="toggle_visible")
        return True

    async def handle_list_selection(self, *, list_index: int, index_map: Sequence[int]) -> bool:
        _emit(
            self.emit,
            "ui.selection.interaction",
            prompt=self.prompt,
            action="list_selected",
            multi=self.multi,
            list_index=list_index,
        )
        if list_index < 0 or list_index >= len(index_map):
            _emit(
                self.emit,
                "ui.selection.interaction",
                prompt=self.prompt,
                action="list_selected_out_of_range",
                multi=self.multi,
                list_index=list_index,
                visible_count=len(index_map),
            )
            return False
        model_index = index_map[list_index]
        changed = (
            await self.toggle_model_index(model_index)
            if self.multi
            else await self.select_model_index(model_index)
        )
        if changed:
            self.focus_list(reason="list_selected")
        return changed

    def submit_values(self, *, focused_index: int | None) -> list[str]:
        return selection_state.selector_submit_values(
            self.rows,
            multi=self.multi,
            focused_index=focused_index,
        )

    def _emit_selection_action(
        self,
        *,
        action: str,
        model_index: int,
        token: str,
        selected: bool,
    ) -> None:
        _emit(
            self.emit,
            "ui.selection.interaction",
            prompt=self.prompt,
            action=action,
            multi=self.multi,
            model_index=model_index,
            token=token,
            selected=selected,
        )


def selector_row_model_index_from_widget(widget: Any, *, row_count: int) -> int | None:
    current = widget
    while current is not None:
        widget_id = str(getattr(current, "id", "") or "").strip()
        if widget_id.startswith("selector-row-"):
            try:
                model_index = int(widget_id.rsplit("-", 1)[1])
            except (TypeError, ValueError):
                return None
            if 0 <= model_index < row_count:
                return model_index
            return None
        current = getattr(current, "parent", None)
    return None
