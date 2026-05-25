from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.textual.list_controller import TextualListController
from envctl_engine.ui.textual.list_row_styles import apply_selectable_list_index
from envctl_engine.ui.textual.list_row_styles import focus_selectable_list
from envctl_engine.ui.textual.compat import handle_text_edit_key_alias
from envctl_engine.ui.textual.screens.selector import selection_state
from envctl_engine.ui.textual.screens.selector.textual_app_chrome import (
    SELECTOR_BINDINGS,
    SELECTOR_CSS,
)
from envctl_engine.ui.textual.screens.selector.textual_app_lifecycle import (
    apply_selector_mount,
)
from envctl_engine.ui.textual.screens.selector.textual_app_initial_navigation import (
    SelectorInitialNavigationRunner,
)
from envctl_engine.ui.textual.screens.selector.textual_app_runtime import (
    SelectorEventController,
    SelectorFocusController,
    SelectorStatusController,
)
from envctl_engine.ui.textual.screens.selector.textual_app_key_trace import emit_app_key_trace
from envctl_engine.ui.textual.screens.selector.textual_app_selection_actions import (
    SelectorSelectionActions,
    selector_row_model_index_from_widget,
)
from envctl_engine.ui.textual.screens.selector.textual_key_telemetry import SelectorKeyTelemetry
from envctl_engine.ui.textual.screens.selector.textual_key_policy import (
    SelectorFilterKeyDecision,
    SelectorKeyDecision,
    resolve_selector_filter_key,
    resolve_selector_key,
)
from envctl_engine.ui.textual.screens.selector.support import (
    _RowRef,
    _emit,
    _selector_driver_thread_snapshot,
)


def create_selector_app(
    *,
    prompt: str,
    options: list[SelectorItem],
    multi: bool,
    initial_token_set: set[str],
    emit: Callable[..., None] | None,
    deep_debug: bool,
    key_trace_enabled: bool,
    key_trace_verbose: bool,
    driver_trace_enabled: bool,
    driver_probe: Callable[[], dict[str, object]] | None,
    thread_stack_enabled: bool,
    disable_focus_reporting: bool,
    mouse_enabled: bool,
    selector_id: str,
    initial_navigation: tuple[str, ...] = (),
    exclusive_token: str | None = None,
):
    status_error_timeout_seconds = 3.0
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical
    from textual.events import Click, Key
    from textual.widgets import Button, Footer, Input, Label, ListItem, ListView, Static

    def trace_key(**payload: Any) -> None:
        emit_app_key_trace(emit=emit, deep_debug=deep_debug, selector_id=selector_id, **payload)

    class SelectorApp(App[list[str] | None]):
        ESCAPE_TO_MINIMIZE = False
        BINDINGS = [
            Binding(*binding[:3], show=binding[3], priority=binding[4]) if len(binding) == 5 else Binding(*binding)
            for binding in SELECTOR_BINDINGS
        ]
        CSS = SELECTOR_CSS

        def __init__(self) -> None:
            super().__init__()
            self._rows: list[_RowRef]
            self._initial_model_index: int | None
            self._last_focused_model_index: int | None = None
            self._last_user_model_index: int | None = None
            self._rows, self._initial_model_index = selection_state.build_selector_rows(
                options,
                initial_token_set,
                multi=multi,
            )
            self._last_user_model_index = self._initial_model_index
            self._controller = TextualListController(
                self._rows,
                initial_model_index=self._initial_model_index,
            )
            self._render_lock = asyncio.Lock()
            self._focus_controller = SelectorFocusController(
                emit=emit,
                deep_debug=deep_debug,
                selector_id=selector_id,
                initial_widget_id="selector-list",
            )
            self._event_controller = SelectorEventController(
                emit=emit,
                deep_debug=deep_debug,
                selector_id=selector_id,
                prompt=prompt,
                option_count=len(options),
                multi=multi,
            )
            self._explicit_cancel = False
            self._key_telemetry = SelectorKeyTelemetry(enabled=key_trace_enabled)
            self._allow_filter_focus = False
            self._key_snapshot_timer: object | None = None
            self._status_controller = SelectorStatusController(
                timeout_seconds=status_error_timeout_seconds,
                set_timer=self.set_timer,
                sync_status=self._sync_status,
            )
            self._selection_actions = SelectorSelectionActions(
                rows=self._rows,
                prompt=prompt,
                multi=multi,
                exclusive_token=exclusive_token,
                emit=emit,
                render_rows=self._render_rows,
                focus_list=self.action_focus_list,
            )
            self._suppress_list_selected_once = False

        def compose(self) -> ComposeResult:
            filter_input = Input(placeholder="Filter targets...", id="selector-filter")
            with Vertical(id="selector-shell"):
                yield Static(prompt, id="selector-prompt")
                yield filter_input
                yield Static("", id="selector-status")
                yield ListView(id="selector-list")
                with Horizontal(id="selector-actions"):
                    yield Button("Cancel", variant="default", id="btn-cancel")
                    yield Button("Run", variant="success", id="btn-run")
                yield Footer()

        async def on_mount(self) -> None:
            await apply_selector_mount(
                self,
                emit=emit,
                deep_debug=deep_debug,
                disable_focus_reporting=disable_focus_reporting,
                key_trace_enabled=key_trace_enabled,
                selector_id=selector_id,
                prompt=prompt,
                option_count=len(options),
                multi=multi,
                Input=Input,
                mouse_enabled=mouse_enabled,
            )
            if initial_navigation:
                self._apply_initial_navigation()

        def _list(self) -> ListView:
            return self.query_one("#selector-list", ListView)

        def _status(self) -> Static:
            return self.query_one("#selector-status", Static)

        @staticmethod
        def _row_text(row: _RowRef) -> str:
            return selection_state.selector_row_text(row)

        @staticmethod
        def _row_classes(row: _RowRef) -> str:
            return selection_state.selector_row_classes(row)

        def _focused_model_index(self) -> int | None:
            return self._controller.focused_model_index(self._list().index)

        def _focused_widget_id(self) -> str:
            try:
                focused = getattr(self, "focused", None)
            except Exception:
                focused = None
            return self._focus_controller.widget_id(
                focused=focused,
                list_has_focus=self._list().has_focus,
                filter_has_focus=self.query_one("#selector-filter", Input).has_focus,
            )

        def _focus_order(self) -> tuple[str, ...]:
            return self._focus_controller.focus_order(
                run_enabled=not self.query_one("#btn-run", Button).disabled,
            )

        def _emit_focus(self, *, reason: str) -> None:
            self._focus_controller.emit_focus(
                reason=reason,
                current_widget_id=self._focused_widget_id(),
            )

        async def _render_rows(self) -> None:
            async with self._render_lock:
                list_view = self._list()
                filter_has_focus = self.query_one("#selector-filter", Input).has_focus
                checkpoint = self._controller.capture_render_checkpoint(
                    view_index=list_view.index,
                    filter_has_focus=filter_has_focus,
                )
                await list_view.clear()
                self._controller.index_map = []
                rendered_items: list[ListItem] = []
                for idx, row in enumerate(self._rows):
                    if not row.visible:
                        continue
                    self._controller.index_map.append(idx)
                    item_widget = ListItem(
                        Label(self._row_text(row), markup=False),
                        id=f"selector-row-{idx}",
                        classes=self._row_classes(row),
                    )
                    rendered_items.append(item_widget)
                if rendered_items:
                    await list_view.extend(rendered_items)
                apply_selectable_list_index(list_view, self._controller.restore_view_index(checkpoint))
                self._controller.finish_render()
                self._initial_model_index = None
                self._sync_status()
                self.query_one("#btn-run", Button).disabled = not bool(self._controller.index_map)
                if not checkpoint.filter_has_focus:
                    self.action_focus_list()

        def _sync_status(self) -> None:
            visible, selected = selection_state.selector_visibility_counts(self._rows)
            if selected:
                self._status_controller.clear_error()
            focused_view_index: int | None = None
            focused_label: str | None = None
            focused_view_index = self._list().index
            if (
                focused_view_index is not None
                and focused_view_index >= 0
                and focused_view_index < len(self._controller.index_map)
            ):
                focused_model_index = self._controller.index_map[focused_view_index]
                self._last_focused_model_index = focused_model_index
                focused_row = self._rows[focused_model_index]
                focused_label = focused_row.item.label
            else:
                focused_view_index = None
            status = self._status_controller.status_text(
                visible_count=visible,
                selected_count=selected,
                total_count=len(self._rows),
                focused_view_index=focused_view_index,
                focused_label=focused_label,
                focusable_count=len(self._controller.index_map),
                deep_debug=deep_debug,
                nav_event_counter=self._key_telemetry.nav_event_counter,
                last_nav_key=self._key_telemetry.last_nav_key,
                edge_hint=self._key_telemetry.edge_hint,
            )
            status_widget = self._status()
            status_widget.set_class(self._status_controller.has_error, "selector-status-error")
            status_widget.update(status)

        def _show_status_error(self, message: str) -> None:
            self._status_controller.show_error(message)

        def _apply_initial_navigation(self) -> None:
            SelectorInitialNavigationRunner(
                actions=initial_navigation,
                rows=self._rows,
                multi=multi,
                controller=self._controller,
                list_view=self._list(),
                focus_list=self.action_focus_list,
                mark_navigation=self._key_telemetry.mark_navigation,
                focused_model_index=self._focused_model_index,
                set_last_user_model_index=lambda index: setattr(self, "_last_user_model_index", index),
                sync_status=self._sync_status,
                schedule_render=lambda: self.call_after_refresh(lambda: asyncio.create_task(self._render_rows())),
                schedule_submit=lambda: self.call_after_refresh(
                    lambda: asyncio.create_task(self.action_submit(cause="initial_navigation_submit"))
                ),
            ).apply()

        async def _sync_single_select_focus_selection(self, *, reason: str) -> None:
            if multi:
                return
            model_index = self._focused_model_index()
            if model_index is None or model_index < 0 or model_index >= len(self._rows):
                return
            changed = False
            for idx, row in enumerate(self._rows):
                selected = idx == model_index
                if row.selected != selected:
                    row.selected = selected
                    changed = True
            if not changed:
                return
            await self._render_rows()
            self.action_focus_list(reason=reason)

        async def _toggle_model_index(self, model_index: int) -> None:
            await self._selection_actions.toggle_model_index(model_index)

        async def _select_model_index(self, model_index: int) -> None:
            await self._selection_actions.select_model_index(model_index)

        async def action_toggle(self) -> None:
            model_index = self._focused_model_index()
            if model_index is None:
                return
            await self._toggle_model_index(model_index)

        async def action_toggle_visible(self) -> None:
            await self._selection_actions.toggle_visible()

        def _emit_key_debug(
            self,
            *,
            key: str,
            focus_before: str,
            list_index_before: int | None,
            handled: bool,
        ) -> None:
            self._key_telemetry.record_handled_key(key)
            if not key_trace_enabled or not key_trace_verbose:
                return
            self._key_telemetry.emit_verbose_key(
                emit=emit,
                deep_debug=deep_debug,
                selector_id=selector_id,
                key=key,
                focused_widget_id=focus_before,
                list_index_before=list_index_before,
                list_index_after=self._list().index,
                handled=handled,
            )

        async def action_nav_up(self) -> None:
            list_index_before = self._controller.ensure_list_index(self._list().index)
            focus_before = self._focused_widget_id()
            if not self._list().has_focus:
                target_index = self._controller.cursor_up(list_index_before)
                self.action_focus_list(reason="key_recover", target_index=target_index)
            else:
                self._list().index = self._controller.cursor_up(self._list().index)
            list_index_after = self._list().index
            focused_model_index = self._focused_model_index()
            if focused_model_index is not None:
                self._last_user_model_index = focused_model_index
            await self._sync_single_select_focus_selection(reason="nav_up")
            at_top_edge = list_index_before is not None and list_index_after == list_index_before == 0
            self._key_telemetry.mark_navigation(
                "up",
                edge_hint="top boundary" if at_top_edge else "",
            )
            self._sync_status()
            self._emit_key_debug(
                key="up",
                focus_before=focus_before,
                list_index_before=list_index_before,
                handled=True,
            )

        async def action_nav_down(self) -> None:
            list_index_before = self._controller.ensure_list_index(self._list().index)
            focus_before = self._focused_widget_id()
            if not self._list().has_focus:
                target_index = self._controller.cursor_down(list_index_before)
                self.action_focus_list(reason="key_recover", target_index=target_index)
            else:
                self._list().index = self._controller.cursor_down(self._list().index)
            list_index_after = self._list().index
            focused_model_index = self._focused_model_index()
            if focused_model_index is not None:
                self._last_user_model_index = focused_model_index
            await self._sync_single_select_focus_selection(reason="nav_down")
            max_view_index = len(self._controller.index_map) - 1
            self._key_telemetry.mark_navigation(
                "down",
                edge_hint=(
                    "bottom boundary"
                    if (
                        list_index_before is not None
                        and max_view_index >= 0
                        and list_index_after == list_index_before == max_view_index
                    )
                    else ""
                )
            )
            self._sync_status()
            self._emit_key_debug(
                key="down",
                focus_before=focus_before,
                list_index_before=list_index_before,
                handled=True,
            )

        def action_ignore_escape(self) -> None:
            list_index_before = self._list().index
            focus_before = self._focused_widget_id()
            if not self._list().has_focus:
                self.action_focus_list(reason="escape_recover")
            self._emit_key_debug(
                key="escape",
                focus_before=focus_before,
                list_index_before=list_index_before,
                handled=True,
            )

        def action_focus_filter(self, *, reason: str = "focus_filter") -> None:
            filter_input = self.query_one("#selector-filter", Input)
            self._allow_filter_focus = True
            filter_input.can_focus = True
            filter_input.focus()
            self._emit_focus(reason=reason)

        def action_focus_list(self, *, reason: str = "focus_list", target_index: int | None = None) -> None:
            list_view = self._list()
            index = self._controller.ensure_list_index(target_index if target_index is not None else list_view.index)
            apply_selectable_list_index(list_view, index)
            self._allow_filter_focus = False
            focus_selectable_list(self, list_view, index)
            self._emit_focus(reason=reason)

        def action_focus_button(self, button_id: str, *, reason: str) -> None:
            self._allow_filter_focus = False
            self.query_one(f"#{button_id}", Button).focus()
            self._emit_focus(reason=reason)

        def action_cycle_focus(self) -> None:
            next_target = self._controller.cycle_focus_target(
                current_target=self._focused_widget_id(),
                focus_order=self._focus_order(),
            )
            if next_target == "selector-list":
                self.action_focus_list(reason="tab_cycle")
            elif next_target == "selector-filter":
                self.action_focus_filter(reason="tab_cycle")
            else:
                self.action_focus_button(next_target, reason="tab_cycle")

        async def action_submit(self, *, cause: str = "enter") -> None:
            if self.query_one("#selector-filter", Input).has_focus:
                self.action_focus_list(reason="submit_from_filter")
            values = self._selection_actions.submit_values(focused_index=self._focused_model_index())
            if not values:
                self._show_status_error("No items were selected. Press Space or click to select at least one.")
                self._event_controller.submit_blocked(cause=cause)
                return
            self._event_controller.submit_confirmed(selected_count=len(values), cause=cause)
            self.exit(values)

        def action_cancel(self, *, cause: str = "cancel_key") -> None:
            self._explicit_cancel = True
            self._event_controller.cancel(cause=cause)
            self.exit(None)

        async def on_list_view_selected(self, event: ListView.Selected) -> None:
            if self._suppress_list_selected_once:
                self._suppress_list_selected_once = False
                return
            await self._selection_actions.handle_list_selection(
                list_index=event.index,
                index_map=self._controller.index_map,
            )

        async def on_click(self, event: Click) -> None:
            if multi:
                return
            model_index = selector_row_model_index_from_widget(
                getattr(event, "widget", None),
                row_count=len(self._rows),
            )
            if model_index is None:
                return
            event.stop()
            await self._select_model_index(model_index)
            await self.action_submit(cause="mouse_click")

        async def on_key(self, event: Key) -> None:
            if self._key_telemetry.record_raw_key(event.key) and key_trace_verbose:
                trace_key(
                    event="ui.selector.key.raw",
                    key=event.key,
                    focused_widget_id=self._focused_widget_id(),
                    list_index_before=self._list().index,
                    list_index_after=self._list().index,
                    handled=False,
                )
            focused_id = self._focused_widget_id()
            filter_focused = focused_id == "selector-filter"
            decision = resolve_selector_key(event.key, filter_focused=filter_focused)
            if decision is SelectorKeyDecision.CYCLE_FOCUS:
                event.stop()
                event.prevent_default()
                self.action_cycle_focus()
                trace_key(
                    key=event.key,
                    focused_widget_id=focused_id,
                    list_index_before=self._list().index,
                    list_index_after=self._list().index,
                    handled=True,
                )
                return
            if filter_focused and handle_text_edit_key_alias(
                widget=self.query_one("#selector-filter", Input), event=event
            ):
                return
            if decision is SelectorKeyDecision.SUBMIT:
                event.stop()
                event.prevent_default()
                self._suppress_list_selected_once = True
                await self.action_submit(cause="enter_key")
                trace_key(
                    key=event.key,
                    focused_widget_id=focused_id,
                    list_index_before=self._list().index,
                    list_index_after=self._list().index,
                    handled=True,
                )
                return
            if decision is SelectorKeyDecision.FOCUS_FILTER:
                event.stop()
                event.prevent_default()
                filter_input = self.query_one("#selector-filter", Input)
                filter_input.value = ""
                self.action_focus_filter(reason="slash_focus_filter")
                trace_key(
                    key=event.key,
                    focused_widget_id=focused_id,
                    list_index_before=self._list().index,
                    list_index_after=self._list().index,
                    handled=True,
                )

        async def _maybe_handle_filter_focus_key(self, event: Key) -> bool:
            if self._focused_widget_id() != "selector-filter":
                return False
            decision = resolve_selector_filter_key(event.key)
            if decision is SelectorFilterKeyDecision.NOOP:
                return False
            event.stop()
            event.prevent_default()
            self.action_focus_list(reason="filter_key_recover")
            if decision is SelectorFilterKeyDecision.NAV_UP:
                await self.action_nav_up()
            elif decision is SelectorFilterKeyDecision.NAV_DOWN:
                await self.action_nav_down()
            else:
                await self.action_toggle()
            return True

        async def on_event(self, event: object) -> None:
            if isinstance(event, Key) or event.__class__.__name__.startswith("Mouse"):
                self._status_controller.touch_timeout()
            if not mouse_enabled and event.__class__.__name__.startswith("Mouse"):
                stop = getattr(event, "stop", None)
                if callable(stop):
                    stop()
                return
            if isinstance(event, Key) and await self._maybe_handle_filter_focus_key(event):
                return
            if key_trace_enabled and isinstance(event, Key):
                key = str(event.key)
                self._key_telemetry.record_event_key(key)
                if key_trace_verbose:
                    trace_key(
                        event="ui.selector.key.event",
                        key=key,
                        focused_widget_id=self._focused_widget_id(),
                        list_index_before=self._list().index,
                        list_index_after=self._list().index,
                        handled=False,
                    )
            await super().on_event(event)  # type: ignore[misc]

        async def on_input_changed(self, event: Input.Changed) -> None:
            query = selection_state.apply_selector_filter(self._rows, event.value)
            _emit(emit, "ui.selection.filter.changed", prompt=prompt, query=query)
            await self._render_rows()

        def on_input_submitted(self, _event: Input.Submitted) -> None:
            # Enter in filter should keep interaction on selection list, not accidentally no-op.
            self.action_focus_list(reason="input_submitted")

        async def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "btn-run":
                await self.action_submit(cause="button_run")
            elif event.button.id == "btn-cancel":
                self.action_cancel(cause="button_cancel")

        def on_focus(self, _event: object) -> None:
            self._emit_focus(reason="focus_event")

        def on_unmount(self) -> None:
            self._status_controller.dispose()
            timer = self._key_snapshot_timer
            if timer is not None:
                try:
                    timer.stop()  # type: ignore[union-attr]
                except Exception:
                    pass
                self._key_snapshot_timer = None
            self._emit_key_snapshot()
            self._key_telemetry.emit_summary(
                emit=emit,
                deep_debug=deep_debug,
                selector_id=selector_id,
                thread_snapshot=lambda: _selector_driver_thread_snapshot(
                    self.app,
                    include_stack=thread_stack_enabled,
                ),
            )
            self._event_controller.exit()

        @property
        def explicit_cancel(self) -> bool:
            return self._explicit_cancel

        def fallback_values(self) -> list[str]:
            try:
                focused = self._focused_model_index()
            except Exception:
                focused = None
            return selection_state.fallback_selector_values(
                self._rows,
                focused_indexes=(focused, self._last_user_model_index, self._last_focused_model_index),
            )

        def _emit_key_snapshot(self) -> None:
            if not key_trace_enabled:
                return
            now_ns = time.monotonic_ns()
            try:
                focused_widget_id = self._focused_widget_id()
            except Exception:
                focused_widget_id = "unknown"
            try:
                list_index = self._list().index
            except Exception:
                list_index = None
            self._key_telemetry.emit_snapshot(
                emit=emit,
                deep_debug=deep_debug,
                selector_id=selector_id,
                focused_widget_id=focused_widget_id,
                list_index=list_index,
                driver_snapshot=driver_probe,
                thread_snapshot=lambda: _selector_driver_thread_snapshot(
                    self.app,
                    include_stack=thread_stack_enabled,
                ),
                include_thread_stack=thread_stack_enabled,
                now_ns=now_ns,
            )

    return SelectorApp()
