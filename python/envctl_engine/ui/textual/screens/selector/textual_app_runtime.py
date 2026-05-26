from __future__ import annotations

import time
from collections.abc import Callable

from envctl_engine.ui.textual.screens.selector.support import _emit, _emit_selector_debug
from envctl_engine.ui.textual.screens.selector.textual_key_telemetry import SelectorKeyTelemetry

TimerHandle = object
TimerFactory = Callable[[float, Callable[[], None]], TimerHandle]
SyncStatus = Callable[[], None]
EmitEvent = Callable[..., None]

__all__ = [
    "SelectorEventController",
    "SelectorFocusController",
    "SelectorKeyTelemetry",
    "SelectorStatusController",
    "SelectorStatusPresenter",
]


class SelectorStatusPresenter:
    def __init__(self) -> None:
        self._error_message = ""

    @property
    def has_error(self) -> bool:
        return bool(self._error_message)

    def show_error(self, message: str) -> None:
        self._error_message = message.strip()

    def clear_error(self) -> bool:
        if not self._error_message:
            return False
        self._error_message = ""
        return True

    def status_text(
        self,
        *,
        visible_count: int,
        selected_count: int,
        total_count: int,
        focused_view_index: int | None,
        focused_label: str | None,
        focusable_count: int,
        deep_debug: bool,
        nav_event_counter: int,
        last_nav_key: str,
        edge_hint: str,
    ) -> str:
        if self._error_message:
            return self._error_message
        focus_text = "focus: -"
        if focused_view_index is not None and focused_label is not None:
            focus_text = f"focus: {focused_view_index + 1}/{focusable_count} {focused_label}"
        status = f"{selected_count} selected • {visible_count} visible • {total_count} total • {focus_text}"
        if deep_debug and nav_event_counter > 0:
            status += f" • key#{nav_event_counter}:{last_nav_key}"
            if edge_hint:
                status += f" • {edge_hint}"
        return status


class SelectorStatusController:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        set_timer: TimerFactory,
        sync_status: SyncStatus | None = None,
        presenter: SelectorStatusPresenter | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._set_timer = set_timer
        self._sync_status = sync_status
        self._presenter = presenter or SelectorStatusPresenter()
        self._timer: TimerHandle | None = None

    @property
    def has_error(self) -> bool:
        return self._presenter.has_error

    def status_text(
        self,
        *,
        visible_count: int,
        selected_count: int,
        total_count: int,
        focused_view_index: int | None,
        focused_label: str | None,
        focusable_count: int,
        deep_debug: bool,
        nav_event_counter: int,
        last_nav_key: str,
        edge_hint: str,
    ) -> str:
        return self._presenter.status_text(
            visible_count=visible_count,
            selected_count=selected_count,
            total_count=total_count,
            focused_view_index=focused_view_index,
            focused_label=focused_label,
            focusable_count=focusable_count,
            deep_debug=deep_debug,
            nav_event_counter=nav_event_counter,
            last_nav_key=last_nav_key,
            edge_hint=edge_hint,
        )

    def show_error(self, message: str) -> None:
        self._presenter.show_error(message)
        self._schedule_clear()
        self._sync()

    def touch_timeout(self) -> None:
        if self._presenter.has_error:
            self._schedule_clear()

    def clear_error(self) -> None:
        if not self._presenter.clear_error():
            return
        self._stop_timer()
        self._sync()

    def dispose(self) -> None:
        self.clear_error()
        self._stop_timer()

    def _schedule_clear(self) -> None:
        self._stop_timer()
        self._timer = self._set_timer(self._timeout_seconds, self.clear_error)

    def _stop_timer(self) -> None:
        timer = self._timer
        if timer is None:
            return
        try:
            stop = getattr(timer, "stop")
            if callable(stop):
                stop()
        except Exception:
            pass
        self._timer = None

    def _sync(self) -> None:
        if self._sync_status is None:
            return
        try:
            self._sync_status()
        except Exception:
            pass


class SelectorFocusController:
    def __init__(
        self,
        *,
        emit: EmitEvent | None,
        deep_debug: bool,
        selector_id: str,
        initial_widget_id: str = "unknown",
    ) -> None:
        self._emit = emit
        self._deep_debug = deep_debug
        self._selector_id = selector_id
        self._last_widget_id = initial_widget_id

    @staticmethod
    def widget_id(*, focused: object, list_has_focus: bool, filter_has_focus: bool) -> str:
        focused_id = str(getattr(focused, "id", "") or "").strip()
        if focused_id:
            return focused_id
        if list_has_focus:
            return "selector-list"
        if filter_has_focus:
            return "selector-filter"
        return "unknown"

    @staticmethod
    def focus_order(*, run_enabled: bool) -> tuple[str, ...]:
        focus_order = ["selector-filter", "selector-list", "btn-cancel"]
        if run_enabled:
            focus_order.append("btn-run")
        return tuple(focus_order)

    def emit_focus(self, *, reason: str, current_widget_id: str) -> None:
        previous = self._last_widget_id
        if current_widget_id == previous:
            return
        self._last_widget_id = current_widget_id
        _emit_selector_debug(
            self._emit,
            enabled=self._deep_debug,
            event="ui.selector.focus",
            selector_id=self._selector_id,
            reason=reason,
            from_widget_id=previous,
            to_widget_id=current_widget_id,
        )


class SelectorEventController:
    def __init__(
        self,
        *,
        emit: EmitEvent | None,
        deep_debug: bool,
        selector_id: str,
        prompt: str,
        option_count: int,
        multi: bool,
    ) -> None:
        self._emit = emit
        self._deep_debug = deep_debug
        self._selector_id = selector_id
        self._prompt = prompt
        self._option_count = option_count
        self._multi = multi

    def submit_blocked(self, *, cause: str) -> None:
        _emit(
            self._emit,
            "ui.selection.confirm",
            prompt=self._prompt,
            multi=self._multi,
            selected_count=0,
            blocked=True,
        )
        self._emit_submit_debug(selected_count=0, blocked=True, cancelled=False, cause=cause)

    def submit_confirmed(self, *, selected_count: int, cause: str) -> None:
        _emit(
            self._emit,
            "ui.selection.confirm",
            prompt=self._prompt,
            multi=self._multi,
            selected_count=selected_count,
        )
        self._emit_submit_debug(selected_count=selected_count, blocked=False, cancelled=False, cause=cause)

    def cancel(self, *, cause: str) -> None:
        _emit(self._emit, "ui.selection.cancel", prompt=self._prompt, multi=self._multi)
        self._emit_submit_debug(selected_count=0, blocked=False, cancelled=True, cause=cause)

    def exit(self) -> None:
        _emit(self._emit, "ui.screen.exit", screen="selector", prompt=self._prompt)
        _emit_selector_debug(
            self._emit,
            enabled=self._deep_debug,
            event="ui.selector.lifecycle",
            selector_id=self._selector_id,
            prompt=self._prompt,
            option_count=self._option_count,
            multi=self._multi,
            phase="exit",
            ts_mono_ns=time.monotonic_ns(),
        )

    def _emit_submit_debug(
        self,
        *,
        selected_count: int,
        blocked: bool,
        cancelled: bool,
        cause: str,
    ) -> None:
        _emit_selector_debug(
            self._emit,
            enabled=self._deep_debug,
            event="ui.selector.submit",
            selector_id=self._selector_id,
            selected_count=selected_count,
            blocked=blocked,
            cancelled=cancelled,
            cause=cause,
        )
