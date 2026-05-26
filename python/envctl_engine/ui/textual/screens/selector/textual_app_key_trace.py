from __future__ import annotations

from collections.abc import Callable

from envctl_engine.ui.textual.screens.selector.textual_key_policy import emit_selector_key_trace


def emit_app_key_trace(
    *,
    emit: Callable[..., None] | None,
    deep_debug: bool,
    selector_id: str,
    key: str,
    focused_widget_id: str,
    list_index_before: int | None,
    list_index_after: int | None,
    handled: bool,
    event: str = "ui.selector.key",
) -> None:
    emit_selector_key_trace(
        emit=emit,
        deep_debug=deep_debug,
        event=event,
        selector_id=selector_id,
        key=key,
        focused_widget_id=focused_widget_id,
        list_index_before=list_index_before,
        list_index_after=list_index_after,
        handled=handled,
    )
