from __future__ import annotations

import time
from collections.abc import Callable

from envctl_engine.ui.textual.screens.selector.support import _emit_selector_debug

TimerHandle = object
TimerFactory = Callable[[float, Callable[[], None]], TimerHandle]
SyncStatus = Callable[[], None]
EmitEvent = Callable[..., None]


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


class SelectorKeyTelemetry:
    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self.nav_event_counter = 0
        self.last_nav_key = ""
        self.edge_hint = ""
        self._last_nav_change_ns = time.monotonic_ns()
        self._idle_snapshot_bucket = -1
        self._last_driver_read_calls = -1
        self._driver_idle_snapshot_bucket = -1
        self._handled_key_counts: dict[str, int] = {}
        self._raw_key_counts: dict[str, int] = {}
        self._event_key_counts: dict[str, int] = {}

    @property
    def handled_counts(self) -> dict[str, int]:
        return dict(self._handled_key_counts)

    @property
    def raw_counts(self) -> dict[str, int]:
        return dict(self._raw_key_counts)

    @property
    def event_counts(self) -> dict[str, int]:
        return dict(self._event_key_counts)

    def mark_navigation(self, key: str, *, edge_hint: str = "", now_ns: int | None = None) -> None:
        self.nav_event_counter += 1
        self.last_nav_key = key
        self.edge_hint = edge_hint
        self._last_nav_change_ns = time.monotonic_ns() if now_ns is None else now_ns
        self._idle_snapshot_bucket = -1

    def record_raw_key(self, key: str) -> bool:
        if not self.enabled:
            return False
        self._raw_key_counts[key] = self._raw_key_counts.get(key, 0) + 1
        return True

    def record_event_key(self, key: str) -> bool:
        if not self.enabled:
            return False
        self._event_key_counts[key] = self._event_key_counts.get(key, 0) + 1
        return True

    def record_handled_key(self, key: str) -> bool:
        if not self.enabled:
            return False
        self._handled_key_counts[key] = self._handled_key_counts.get(key, 0) + 1
        return True

    def emit_verbose_key(
        self,
        *,
        emit: Callable[..., None] | None,
        deep_debug: bool,
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
            event="ui.selector.key",
            selector_id=selector_id,
            key=key,
            focused_widget_id=focused_widget_id,
            list_index_before=list_index_before,
            list_index_after=list_index_after,
            handled=handled,
        )

    def emit_snapshot(
        self,
        *,
        emit: Callable[..., None] | None,
        deep_debug: bool,
        selector_id: str,
        focused_widget_id: str,
        list_index: int | None,
        driver_snapshot: Callable[[], dict[str, object]] | None,
        thread_snapshot: Callable[[], dict[str, object]],
        include_thread_stack: bool = True,
        now_ns: int | None = None,
    ) -> None:
        if not self.enabled:
            return
        snapshot_ns = time.monotonic_ns() if now_ns is None else now_ns
        _emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.snapshot",
            selector_id=selector_id,
            focused_widget_id=focused_widget_id,
            list_index=list_index,
            nav_event_counter=self.nav_event_counter,
            event_counts=self.event_counts,
            raw_counts=self.raw_counts,
            handled_counts=self.handled_counts,
        )
        self._emit_idle_after_activity(
            emit=emit,
            deep_debug=deep_debug,
            selector_id=selector_id,
            focused_widget_id=focused_widget_id,
            list_index=list_index,
            now_ns=snapshot_ns,
        )
        if driver_snapshot is not None:
            self._emit_driver_snapshot(
                emit=emit,
                deep_debug=deep_debug,
                selector_id=selector_id,
                focused_widget_id=focused_widget_id,
                list_index=list_index,
                driver_snapshot=driver_snapshot,
                thread_snapshot=thread_snapshot,
                include_thread_stack=include_thread_stack,
                now_ns=snapshot_ns,
            )

    def emit_summary(
        self,
        *,
        emit: Callable[..., None] | None,
        deep_debug: bool,
        selector_id: str,
        thread_snapshot: Callable[[], dict[str, object]],
    ) -> None:
        if not self.enabled:
            return
        _emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.summary",
            selector_id=selector_id,
            event_counts=self.event_counts,
            handled_counts=self.handled_counts,
            raw_counts=self.raw_counts,
        )
        _emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.thread.final",
            selector_id=selector_id,
            **thread_snapshot(),
        )

    def _emit_idle_after_activity(
        self,
        *,
        emit: Callable[..., None] | None,
        deep_debug: bool,
        selector_id: str,
        focused_widget_id: str,
        list_index: int | None,
        now_ns: int,
    ) -> None:
        if self.nav_event_counter <= 0:
            return
        idle_ms = self._idle_ms(now_ns)
        if idle_ms < 2000:
            return
        bucket = idle_ms // 2000
        if bucket == self._idle_snapshot_bucket:
            return
        self._idle_snapshot_bucket = bucket
        _emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.idle_after_activity",
            selector_id=selector_id,
            idle_ms=idle_ms,
            focused_widget_id=focused_widget_id,
            list_index=list_index,
            nav_event_counter=self.nav_event_counter,
            event_counts=self.event_counts,
            raw_counts=self.raw_counts,
            handled_counts=self.handled_counts,
        )

    def _emit_driver_snapshot(
        self,
        *,
        emit: Callable[..., None] | None,
        deep_debug: bool,
        selector_id: str,
        focused_widget_id: str,
        list_index: int | None,
        driver_snapshot: Callable[[], dict[str, object]],
        thread_snapshot: Callable[[], dict[str, object]],
        include_thread_stack: bool,
        now_ns: int,
    ) -> None:
        merged_snapshot = dict(driver_snapshot())
        merged_snapshot.update(thread_snapshot())
        _emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.snapshot",
            selector_id=selector_id,
            **merged_snapshot,
        )
        read_calls = merged_snapshot.get("read_calls")
        if not isinstance(read_calls, int):
            return
        if read_calls != self._last_driver_read_calls:
            self._last_driver_read_calls = read_calls
            self._driver_idle_snapshot_bucket = -1
            return
        if self.nav_event_counter <= 0:
            return
        idle_ms = self._idle_ms(now_ns)
        if idle_ms < 2000:
            return
        bucket = idle_ms // 2000
        if bucket == self._driver_idle_snapshot_bucket:
            return
        self._driver_idle_snapshot_bucket = bucket
        _emit_selector_debug(
            emit,
            enabled=deep_debug,
            event="ui.selector.key.driver.idle_after_activity",
            selector_id=selector_id,
            idle_ms=idle_ms,
            focused_widget_id=focused_widget_id,
            list_index=list_index,
            nav_event_counter=self.nav_event_counter,
            read_calls=read_calls,
            read_bytes=merged_snapshot.get("read_bytes"),
            key_events_total=merged_snapshot.get("key_events_total"),
            non_key_messages=merged_snapshot.get("non_key_messages"),
            input_thread_alive=merged_snapshot.get("input_thread_alive"),
            input_thread_stack=merged_snapshot.get("input_thread_stack") if include_thread_stack else None,
        )

    def _idle_ms(self, now_ns: int) -> int:
        idle_ns = max(0, now_ns - int(self._last_nav_change_ns))
        return int(idle_ns / 1_000_000)
