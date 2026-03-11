from __future__ import annotations


def selectable_list_row_css(row_prefix: str) -> str:
    return f"""
ListItem.-highlight {{
    background: $accent 8%;
    border-left: wide $accent 35%;
    color: $text;
}}
.{row_prefix} {{
    padding: 0 1;
    width: 100%;
}}
.{row_prefix}-selected {{
    background: $success 22%;
    border-left: wide $success;
}}
.{row_prefix}-unselected.-highlight {{
    background: $accent 18%;
    border-left: wide $accent;
}}
.{row_prefix}-selected.-highlight {{
    background: $success 34%;
    border-left: wide $success;
}}
.{row_prefix}-selected Label {{
    color: $success;
    text-style: bold;
}}
.{row_prefix}-selected.-highlight Label {{
    color: $text;
    text-style: bold underline;
}}
.{row_prefix}-unselected Label {{
    color: $text;
}}
""".strip()


def selectable_list_row_classes(row_prefix: str, *, selected: bool) -> str:
    state = f"{row_prefix}-selected" if selected else f"{row_prefix}-unselected"
    return f"{row_prefix} {state}"


def selectable_list_default_index(selected_flags: list[bool] | tuple[bool, ...]) -> int:
    for index, selected in enumerate(selected_flags):
        if selected:
            return index
    return 0


def apply_selectable_list_index(list_view: object, index: int | None) -> None:
    """Force Textual to restore the highlighted row after the list is rebuilt."""
    setattr(list_view, "index", None)
    setattr(list_view, "index", index)


def focus_selectable_list(owner: object, list_view: object, index: int | None) -> None:
    getattr(list_view, "focus")()

    def _sync() -> None:
        apply_selectable_list_index(list_view, index)

    call_after_refresh = getattr(owner, "call_after_refresh", None)
    if callable(call_after_refresh):
        call_after_refresh(_sync)
        return
    _sync()
