from __future__ import annotations

from collections.abc import Callable
from enum import Enum

from envctl_engine.ui.textual.screens.selector.support import _emit_selector_debug


class SelectorKeyDecision(Enum):
    NOOP = "noop"
    CYCLE_FOCUS = "cycle_focus"
    SUBMIT = "submit"
    FOCUS_FILTER = "focus_filter"


class SelectorFilterKeyDecision(Enum):
    NOOP = "noop"
    NAV_UP = "nav_up"
    NAV_DOWN = "nav_down"
    TOGGLE = "toggle"


def resolve_selector_key(key: str, *, filter_focused: bool) -> SelectorKeyDecision:
    if key == "tab":
        return SelectorKeyDecision.CYCLE_FOCUS
    if key == "enter":
        return SelectorKeyDecision.SUBMIT
    if key == "slash" and not filter_focused:
        return SelectorKeyDecision.FOCUS_FILTER
    return SelectorKeyDecision.NOOP


def resolve_selector_filter_key(key: str) -> SelectorFilterKeyDecision:
    if key in {"up", "k", "w"}:
        return SelectorFilterKeyDecision.NAV_UP
    if key in {"down", "j", "s"}:
        return SelectorFilterKeyDecision.NAV_DOWN
    if key == "space":
        return SelectorFilterKeyDecision.TOGGLE
    return SelectorFilterKeyDecision.NOOP


def emit_selector_key_trace(
    *,
    emit: Callable[..., None] | None,
    deep_debug: bool,
    event: str = "ui.selector.key",
    selector_id: str,
    key: str,
    focused_widget_id: str,
    list_index_before: int | None,
    list_index_after: int | None,
    handled: bool,
) -> None:
    _emit_selector_debug(
        emit,
        enabled=deep_debug,
        event=event,
        selector_id=selector_id,
        key=key,
        focused_widget_id=focused_widget_id,
        list_index_before=list_index_before,
        list_index_after=list_index_after,
        handled=handled,
    )
