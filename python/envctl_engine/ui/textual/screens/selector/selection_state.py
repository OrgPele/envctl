from __future__ import annotations

from collections.abc import Iterable, Sequence

from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.textual.list_row_styles import selectable_list_row_classes
from envctl_engine.ui.textual.screens.selector.support import _RowRef


def build_selector_rows(
    options: Sequence[SelectorItem],
    initial_token_set: set[str],
    *,
    multi: bool,
) -> tuple[list[_RowRef], int | None]:
    rows: list[_RowRef] = []
    initial_model_index: int | None = None
    for idx, item in enumerate(options):
        selected = str(item.token).strip() in initial_token_set
        if selected and initial_model_index is None:
            initial_model_index = idx
        if selected and not multi:
            selected = initial_model_index == idx
        rows.append(_RowRef(item=item, selected=selected, visible=True))
    return rows, initial_model_index


def selector_row_text(row: _RowRef) -> str:
    marker = "●" if row.selected else "○"
    badge = str(row.item.kind or "").replace("_", " ").strip()
    if not badge:
        return f"{marker} {row.item.label}"
    return f"{marker} {row.item.label}  ({badge})"


def selector_row_classes(row: _RowRef) -> str:
    base_classes = selectable_list_row_classes("selector-row", selected=row.selected)
    kind = str(row.item.kind or "").replace("_", "-").strip("-")
    if not kind:
        return base_classes
    return f"{base_classes} kind-{kind}"


def selected_selector_values(rows: Sequence[_RowRef]) -> list[str]:
    return [row.item.token for row in rows if row.selected and row.visible]


def select_selector_model_index(rows: Sequence[_RowRef], model_index: int, *, multi: bool) -> _RowRef | None:
    if model_index < 0 or model_index >= len(rows):
        return None
    row = rows[model_index]
    if row.selected and not multi:
        return None
    if not multi:
        for candidate in rows:
            candidate.selected = False
    row.selected = True
    return row


def toggle_selector_model_index(
    rows: Sequence[_RowRef],
    model_index: int,
    *,
    multi: bool,
    exclusive_token: str | None,
) -> _RowRef | None:
    if model_index < 0 or model_index >= len(rows):
        return None
    row = rows[model_index]
    row_token = str(row.item.token)
    if not multi:
        for candidate in rows:
            candidate.selected = False
    row.selected = not row.selected if multi else True
    if multi and row.selected and exclusive_token:
        _apply_exclusive_selection(
            rows,
            selected_index=model_index,
            selected_token=row_token,
            exclusive_token=exclusive_token,
        )
    return row


def toggle_visible_selector_rows(
    rows: Sequence[_RowRef],
    *,
    multi: bool,
    exclusive_token: str | None,
) -> bool | None:
    visible_indexes = [idx for idx, row in enumerate(rows) if row.visible]
    if not visible_indexes:
        return None
    selectable_indexes = visible_indexes
    if multi and exclusive_token:
        selectable_indexes = [idx for idx in visible_indexes if str(rows[idx].item.token) != exclusive_token]
        if not selectable_indexes:
            selectable_indexes = visible_indexes
    should_select = not all(rows[idx].selected for idx in selectable_indexes)
    for idx in visible_indexes:
        rows[idx].selected = should_select and idx in selectable_indexes
    return should_select


def fallback_selector_values(rows: Sequence[_RowRef], *, focused_indexes: Iterable[int | None]) -> list[str]:
    selected = selected_selector_values(rows)
    if selected:
        return selected
    for focused in focused_indexes:
        if focused is not None and 0 <= focused < len(rows):
            row = rows[focused]
            if row.visible:
                return [row.item.token]
    visible = [row.item.token for row in rows if row.visible]
    if visible:
        return [visible[0]]
    return []


def _apply_exclusive_selection(
    rows: Sequence[_RowRef],
    *,
    selected_index: int,
    selected_token: str,
    exclusive_token: str,
) -> None:
    if selected_token == exclusive_token:
        for idx, candidate in enumerate(rows):
            if idx != selected_index:
                candidate.selected = False
        return
    for candidate in rows:
        if str(candidate.item.token) == exclusive_token:
            candidate.selected = False
