from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from envctl_engine.ui.textual.compat import handle_text_edit_key_alias
from envctl_engine.ui.textual.screens.selector.textual_key_policy import (
    SelectorFilterKeyDecision,
    SelectorKeyDecision,
    resolve_selector_filter_key,
    resolve_selector_key,
)
from envctl_engine.ui.textual.screens.selector.textual_key_telemetry import SelectorKeyTelemetry


async def _noop_async(*_args: object, **_kwargs: object) -> None:
    return None


@dataclass(slots=True)
class SelectorKeyActions:
    key_telemetry: SelectorKeyTelemetry
    key_trace_verbose: bool
    trace_key: Callable[..., None]
    focused_widget_id: Callable[[], str]
    list_index: Callable[[], int | None]
    filter_input: Callable[[], Any]
    handle_text_edit_key_alias: Callable[..., bool] = handle_text_edit_key_alias
    cycle_focus: Callable[[], None] = lambda: None
    submit: Callable[..., Awaitable[None]] = lambda *, cause: _noop_async()
    focus_filter: Callable[..., None] = lambda *, reason: None
    focus_list: Callable[..., None] = lambda *, reason: None
    nav_up: Callable[[], Awaitable[None]] = _noop_async
    nav_down: Callable[[], Awaitable[None]] = _noop_async
    toggle: Callable[[], Awaitable[None]] = _noop_async
    suppress_list_selected_once: Callable[[bool], None] = lambda _value: None

    async def handle_key(self, event: Any) -> None:
        key = str(event.key)
        if self.key_telemetry.record_raw_key(key) and self.key_trace_verbose:
            self._trace(event="ui.selector.key.raw", key=key, handled=False)

        focused_id = self.focused_widget_id()
        filter_focused = focused_id == "selector-filter"
        decision = resolve_selector_key(key, filter_focused=filter_focused)
        if decision is SelectorKeyDecision.CYCLE_FOCUS:
            self._stop(event)
            self.cycle_focus()
            self._trace(key=key, focused_widget_id=focused_id, handled=True)
            return

        if filter_focused and self.handle_text_edit_key_alias(widget=self.filter_input(), event=event):
            return

        if decision is SelectorKeyDecision.SUBMIT:
            self._stop(event)
            self.suppress_list_selected_once(True)
            await self.submit(cause="enter_key")
            self._trace(key=key, focused_widget_id=focused_id, handled=True)
            return

        if decision is SelectorKeyDecision.FOCUS_FILTER:
            self._stop(event)
            self.filter_input().value = ""
            self.focus_filter(reason="slash_focus_filter")
            self._trace(key=key, focused_widget_id=focused_id, handled=True)

    async def handle_filter_focus_key(self, event: Any) -> bool:
        if self.focused_widget_id() != "selector-filter":
            return False
        decision = resolve_selector_filter_key(str(event.key))
        if decision is SelectorFilterKeyDecision.NOOP:
            return False
        self._stop(event)
        self.focus_list(reason="filter_key_recover")
        if decision is SelectorFilterKeyDecision.NAV_UP:
            await self.nav_up()
        elif decision is SelectorFilterKeyDecision.NAV_DOWN:
            await self.nav_down()
        else:
            await self.toggle()
        return True

    def record_event_key(self, event: Any) -> None:
        key = str(event.key)
        self.key_telemetry.record_event_key(key)
        if self.key_trace_verbose:
            self._trace(event="ui.selector.key.event", key=key, handled=False)

    def _trace(
        self,
        *,
        key: str,
        handled: bool,
        event: str = "ui.selector.key",
        focused_widget_id: str | None = None,
    ) -> None:
        list_index = self.list_index()
        self.trace_key(
            event=event,
            key=key,
            focused_widget_id=focused_widget_id or self.focused_widget_id(),
            list_index_before=list_index,
            list_index_after=list_index,
            handled=handled,
        )

    @staticmethod
    def _stop(event: Any) -> None:
        event.stop()
        event.prevent_default()
