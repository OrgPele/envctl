from __future__ import annotations

import asyncio
import time
from typing import Callable

from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.textual.list_controller import TextualListController
from envctl_engine.ui.textual.screens.selector.textual_app_chrome import (
    SELECTOR_BINDINGS,
    SELECTOR_CSS,
)
from envctl_engine.ui.textual.screens.selector.textual_app_lifecycle import (
    apply_selector_mount,
)
from envctl_engine.ui.textual.screens.selector.support import (
    _RowRef,
    _emit,
    _emit_selector_debug,
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
):
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical
    from textual.events import Key
    from textual.widgets import Button, Footer, Input, Label, ListItem, ListView, Static

    class SelectorApp(App[list[str] | None]):
            ESCAPE_TO_MINIMIZE = False
            BINDINGS = [
                Binding(*binding[:3], show=binding[3], priority=binding[4])
                if len(binding) == 5
                else Binding(*binding)
                for binding in SELECTOR_BINDINGS
            ]
            CSS = SELECTOR_CSS

            def __init__(self) -> None:
                super().__init__()
                self._rows: list[_RowRef] = []
                self._initial_model_index: int | None = None
                for idx, item in enumerate(options):
                    selected = str(item.token).strip() in initial_token_set
                    if selected and self._initial_model_index is None:
                        self._initial_model_index = idx
                    if selected and not multi:
                        selected = self._initial_model_index == idx
                    self._rows.append(_RowRef(item=item, selected=selected, visible=True))
                self._controller = TextualListController(
                    self._rows,
                    initial_model_index=self._initial_model_index,
                )
                self._render_lock = asyncio.Lock()
                self._last_focus_widget_id = "selector-list"
                self._explicit_cancel = False
                self._nav_event_counter = 0
                self._last_nav_key = ""
                self._edge_hint = ""
                self._handled_key_counts: dict[str, int] = {}
                self._raw_key_counts: dict[str, int] = {}
                self._allow_filter_focus = False
                self._event_key_counts: dict[str, int] = {}
                self._key_snapshot_timer: object | None = None
                self._last_nav_change_ns = time.monotonic_ns()
                self._idle_snapshot_bucket = -1
                self._last_driver_read_calls = -1
                self._driver_idle_snapshot_bucket = -1

            def compose(self) -> ComposeResult:
                filter_input = Input(placeholder="Filter targets...", id="selector-filter")
                filter_input.can_focus = False
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

            def _list(self) -> ListView:
                return self.query_one("#selector-list", ListView)

            def _status(self) -> Static:
                return self.query_one("#selector-status", Static)

            @staticmethod
            def _row_text(row: _RowRef) -> str:
                marker = "●" if row.selected else "○"
                badge = row.item.kind.replace("_", " ")
                return f"{marker} {row.item.label}  ({badge})"

            @staticmethod
            def _row_classes(row: _RowRef) -> str:
                row_classes = [
                    "selector-row",
                    ("selector-row-selected" if row.selected else "selector-row-unselected"),
                    f"kind-{row.item.kind.replace('_', '-')}",
                ]
                return " ".join(row_classes)

            def _focused_model_index(self) -> int | None:
                return self._controller.focused_model_index(self._list().index)

            def _focused_widget_id(self) -> str:
                try:
                    focused = getattr(self, "focused", None)
                except Exception:
                    return "unknown"
                focused_id = str(getattr(focused, "id", "") or "").strip()
                if focused_id:
                    return focused_id
                if self._list().has_focus:
                    return "selector-list"
                if self.query_one("#selector-filter", Input).has_focus:
                    return "selector-filter"
                return "unknown"

            def _emit_focus(self, *, reason: str) -> None:
                current = self._focused_widget_id()
                previous = self._last_focus_widget_id
                if current == previous:
                    return
                self._last_focus_widget_id = current
                _emit_selector_debug(
                    emit,
                    enabled=deep_debug,
                    event="ui.selector.focus",
                    selector_id=selector_id,
                    reason=reason,
                    from_widget_id=previous,
                    to_widget_id=current,
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
                    list_view.index = self._controller.restore_view_index(checkpoint)
                    self._controller.finish_render()
                    self._initial_model_index = None
                    self._sync_status()
                    self._sync_confirm_state()
                    if not checkpoint.filter_has_focus:
                        self.action_focus_list()

            def _sync_status(self) -> None:
                visible = sum(1 for row in self._rows if row.visible)
                selected = sum(1 for row in self._rows if row.visible and row.selected)
                focus_text = "focus: -"
                focused_view_index = self._list().index
                if (
                    focused_view_index is not None
                    and focused_view_index >= 0
                    and focused_view_index < len(self._controller.index_map)
                ):
                    focused_model_index = self._controller.index_map[focused_view_index]
                    focused_row = self._rows[focused_model_index]
                    focus_text = f"focus: {focused_view_index + 1}/{len(self._controller.index_map)} {focused_row.item.label}"
                status = f"{selected} selected • {visible} visible • {len(self._rows)} total • {focus_text}"
                if deep_debug and self._nav_event_counter > 0:
                    status += f" • key#{self._nav_event_counter}:{self._last_nav_key}"
                    if self._edge_hint:
                        status += f" • {self._edge_hint}"
                self._status().update(status)

            def _sync_confirm_state(self) -> None:
                run_button = self.query_one("#btn-run", Button)
                run_button.disabled = not bool(self._controller.index_map)

            def _focused_row(self) -> _RowRef | None:
                return self._controller.focused_row(self._list().index)

            async def _toggle_model_index(self, model_index: int) -> None:
                if model_index < 0 or model_index >= len(self._rows):
                    return
                row = self._rows[model_index]
                if not multi:
                    for candidate in self._rows:
                        candidate.selected = False
                row.selected = not row.selected if multi else True
                _emit(
                    emit,
                    "ui.selection.interaction",
                    prompt=prompt,
                    action="toggle",
                    multi=multi,
                    model_index=model_index,
                    token=row.item.token,
                    selected=row.selected,
                )
                _emit(emit, "ui.selection.toggle", token=row.item.token, selected=row.selected)
                await self._render_rows()
                self.action_focus_list(reason="toggle")

            async def _select_model_index(self, model_index: int) -> None:
                if model_index < 0 or model_index >= len(self._rows):
                    return
                row = self._rows[model_index]
                if row.selected and not multi:
                    return
                if not multi:
                    for candidate in self._rows:
                        candidate.selected = False
                row.selected = True
                _emit(
                    emit,
                    "ui.selection.interaction",
                    prompt=prompt,
                    action="select",
                    multi=multi,
                    model_index=model_index,
                    token=row.item.token,
                    selected=True,
                )
                _emit(emit, "ui.selection.toggle", token=row.item.token, selected=True)
                await self._render_rows()

            async def action_toggle(self) -> None:
                model_index = self._focused_model_index()
                if model_index is None:
                    return
                await self._toggle_model_index(model_index)

            async def action_toggle_visible(self) -> None:
                should_select = self._controller.apply_visible_toggle(
                    is_visible=lambda row: row.visible,
                    is_active=lambda row: row.selected,
                    activate=lambda row: setattr(row, "selected", True),
                    deactivate=lambda row: setattr(row, "selected", False),
                )
                if should_select is None:
                    return
                _emit(emit, "ui.selection.toggle", token="__VISIBLE__", selected=should_select)
                await self._render_rows()
                self.action_focus_list(reason="toggle_visible")

            def action_cursor_up(self) -> None:
                self._list().index = self._controller.cursor_up(self._list().index)

            def action_cursor_down(self) -> None:
                self._list().index = self._controller.cursor_down(self._list().index)

            def _emit_key_debug(
                self,
                *,
                key: str,
                focus_before: str,
                list_index_before: int | None,
                handled: bool,
            ) -> None:
                if key_trace_enabled:
                    self._handled_key_counts[key] = self._handled_key_counts.get(key, 0) + 1
                if not key_trace_enabled or not key_trace_verbose:
                    return
                _emit_selector_debug(
                    emit,
                    enabled=deep_debug,
                    event="ui.selector.key",
                    selector_id=selector_id,
                    key=key,
                    focused_widget_id=focus_before,
                    list_index_before=list_index_before,
                    list_index_after=self._list().index,
                    handled=handled,
                )

            def action_nav_up(self) -> None:
                list_index_before = self._list().index
                focus_before = self._focused_widget_id()
                if not self._list().has_focus:
                    self.action_focus_list(reason="key_recover")
                self.action_cursor_up()
                list_index_after = self._list().index
                self._nav_event_counter += 1
                self._last_nav_change_ns = time.monotonic_ns()
                self._idle_snapshot_bucket = -1
                self._last_nav_key = "up"
                self._edge_hint = (
                    "top boundary"
                    if list_index_before is not None and list_index_after == list_index_before == 0
                    else ""
                )
                self._sync_status()
                self._emit_key_debug(
                    key="up",
                    focus_before=focus_before,
                    list_index_before=list_index_before,
                    handled=True,
                )

            def action_nav_down(self) -> None:
                list_index_before = self._list().index
                focus_before = self._focused_widget_id()
                if not self._list().has_focus:
                    self.action_focus_list(reason="key_recover")
                self.action_cursor_down()
                list_index_after = self._list().index
                self._nav_event_counter += 1
                self._last_nav_change_ns = time.monotonic_ns()
                self._idle_snapshot_bucket = -1
                self._last_nav_key = "down"
                max_view_index = len(self._controller.index_map) - 1
                self._edge_hint = (
                    "bottom boundary"
                    if (
                        list_index_before is not None
                        and max_view_index >= 0
                        and list_index_after == list_index_before == max_view_index
                    )
                    else ""
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

            def action_focus_list(self, *, reason: str = "focus_list") -> None:
                list_view = self._list()
                list_view.index = self._controller.ensure_list_index(list_view.index)
                self._allow_filter_focus = False
                self.query_one("#selector-filter", Input).can_focus = False
                list_view.focus()
                self._emit_focus(reason=reason)

            def action_cycle_focus(self) -> None:
                next_target = self._controller.cycle_focus_target(
                    filter_has_focus=self.query_one("#selector-filter", Input).has_focus
                )
                if next_target == "list":
                    self.action_focus_list(reason="tab_cycle")
                else:
                    self.action_focus_filter(reason="tab_cycle")

            def _selected_values(self) -> list[str]:
                if multi:
                    return [row.item.token for row in self._rows if row.selected and row.visible]
                row = self._focused_row()
                if row is None:
                    return []
                return [row.item.token]

            async def action_submit(self, *, cause: str = "enter") -> None:
                filter_value = str(self.query_one("#selector-filter", Input).value or "").strip()
                if self.query_one("#selector-filter", Input).has_focus:
                    self.action_focus_list(reason="submit_from_filter")
                values = self._selected_values()
                if multi and not values:
                    focused_index = self._focused_model_index()
                    if focused_index is not None:
                        await self._select_model_index(focused_index)
                        values = self._selected_values()
                if not values:
                    _emit(
                        emit,
                        "ui.selection.confirm",
                        prompt=prompt,
                        multi=multi,
                        selected_count=0,
                        blocked=True,
                    )
                    _emit_selector_debug(
                        emit,
                        enabled=deep_debug,
                        event="ui.selector.submit",
                        selector_id=selector_id,
                        selected_count=0,
                        blocked=True,
                        cancelled=False,
                        cause=cause,
                    )
                    return
                _emit(
                    emit,
                    "ui.selection.confirm",
                    prompt=prompt,
                    multi=multi,
                    selected_count=len(values),
                )
                _emit_selector_debug(
                    emit,
                    enabled=deep_debug,
                    event="ui.selector.submit",
                    selector_id=selector_id,
                    selected_count=len(values),
                    blocked=False,
                    cancelled=False,
                    cause=cause,
                )
                self.exit(values)

            def action_cancel(self, *, cause: str = "cancel_key") -> None:
                self._explicit_cancel = True
                _emit(emit, "ui.selection.cancel", prompt=prompt, multi=multi)
                _emit_selector_debug(
                    emit,
                    enabled=deep_debug,
                    event="ui.selector.submit",
                    selector_id=selector_id,
                    selected_count=0,
                    blocked=False,
                    cancelled=True,
                    cause=cause,
                )
                self.exit(None)

            async def on_list_view_selected(self, event: ListView.Selected) -> None:
                _emit(
                    emit,
                    "ui.selection.interaction",
                    prompt=prompt,
                    action="list_selected",
                    multi=multi,
                    list_index=event.index,
                )
                if event.index < 0 or event.index >= len(self._controller.index_map):
                    _emit(
                        emit,
                        "ui.selection.interaction",
                        prompt=prompt,
                        action="list_selected_out_of_range",
                        multi=multi,
                        list_index=event.index,
                        visible_count=len(self._controller.index_map),
                    )
                    return
                model_index = self._controller.index_map[event.index]
                if multi:
                    await self._toggle_model_index(model_index)
                else:
                    await self._select_model_index(model_index)
                    await self.action_submit(cause="list_selected")
                self.action_focus_list(reason="list_selected")

            async def on_key(self, event: Key) -> None:
                if key_trace_enabled:
                    self._raw_key_counts[event.key] = self._raw_key_counts.get(event.key, 0) + 1
                    if key_trace_verbose:
                        _emit_selector_debug(
                            emit,
                            enabled=deep_debug,
                            event="ui.selector.key.raw",
                            selector_id=selector_id,
                            key=event.key,
                            focused_widget_id=self._focused_widget_id(),
                            list_index_before=self._list().index,
                            list_index_after=self._list().index,
                            handled=False,
                        )
                focused_id = self._focused_widget_id()
                filter_focused = focused_id == "selector-filter"
                if event.key == "slash" and not filter_focused:
                    event.stop()
                    event.prevent_default()
                    filter_input = self.query_one("#selector-filter", Input)
                    filter_input.value = ""
                    self.action_focus_filter(reason="slash_focus_filter")
                    _emit_selector_debug(
                        emit,
                        enabled=deep_debug,
                        event="ui.selector.key",
                        selector_id=selector_id,
                        key=event.key,
                        focused_widget_id=focused_id,
                        list_index_before=self._list().index,
                        list_index_after=self._list().index,
                        handled=True,
                    )

            async def on_event(self, event: object) -> None:
                if not mouse_enabled and event.__class__.__name__.startswith("Mouse"):
                    stop = getattr(event, "stop", None)
                    if callable(stop):
                        stop()
                    return
                if key_trace_enabled and isinstance(event, Key):
                    key = str(event.key)
                    self._event_key_counts[key] = self._event_key_counts.get(key, 0) + 1
                    if key_trace_verbose:
                        _emit_selector_debug(
                            emit,
                            enabled=deep_debug,
                            event="ui.selector.key.event",
                            selector_id=selector_id,
                            key=key,
                            focused_widget_id=self._focused_widget_id(),
                            list_index_before=self._list().index,
                            list_index_after=self._list().index,
                            handled=False,
                        )
                await super().on_event(event)  # type: ignore[misc]

            async def on_input_changed(self, event: Input.Changed) -> None:
                query = str(event.value or "").strip().lower()
                for row in self._rows:
                    row.visible = query in row.item.label.lower() if query else True
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
                # Guard against transient default-focus jumps to the filter field.
                if self._focused_widget_id() == "selector-filter" and not self._allow_filter_focus:
                    self.action_focus_list(reason="focus_guard")
                    return
                self._emit_focus(reason="focus_event")

            def on_unmount(self) -> None:
                timer = self._key_snapshot_timer
                if timer is not None:
                    try:
                        timer.stop()  # type: ignore[union-attr]
                    except Exception:
                        pass
                    self._key_snapshot_timer = None
                if key_trace_enabled:
                    self._emit_key_snapshot()
                if key_trace_enabled:
                    _emit_selector_debug(
                        emit,
                        enabled=deep_debug,
                        event="ui.selector.key.summary",
                        selector_id=selector_id,
                        event_counts=dict(self._event_key_counts),
                        handled_counts=dict(self._handled_key_counts),
                        raw_counts=dict(self._raw_key_counts),
                    )
                    _emit_selector_debug(
                        emit,
                        enabled=deep_debug,
                        event="ui.selector.key.driver.thread.final",
                        selector_id=selector_id,
                        **_selector_driver_thread_snapshot(
                            self.app,
                            include_stack=thread_stack_enabled,
                        ),
                    )
                _emit(emit, "ui.screen.exit", screen="selector", prompt=prompt)
                _emit_selector_debug(
                    emit,
                    enabled=deep_debug,
                    event="ui.selector.lifecycle",
                    selector_id=selector_id,
                    prompt=prompt,
                    option_count=len(options),
                    multi=multi,
                    phase="exit",
                    ts_mono_ns=time.monotonic_ns(),
                )

            @property
            def explicit_cancel(self) -> bool:
                return self._explicit_cancel

            def fallback_values(self) -> list[str]:
                selected = self._selected_values()
                if selected:
                    return selected
                try:
                    focused = self._focused_model_index()
                except Exception:
                    focused = None
                if focused is not None and focused < len(self._rows):
                    return [self._rows[focused].item.token]
                visible = [row.item.token for row in self._rows if row.visible]
                if visible:
                    return [visible[0]]
                return []

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
                _emit_selector_debug(
                    emit,
                    enabled=deep_debug,
                    event="ui.selector.key.snapshot",
                    selector_id=selector_id,
                    focused_widget_id=focused_widget_id,
                    list_index=list_index,
                    nav_event_counter=self._nav_event_counter,
                    event_counts=dict(self._event_key_counts),
                    raw_counts=dict(self._raw_key_counts),
                    handled_counts=dict(self._handled_key_counts),
                )
                if self._nav_event_counter > 0:
                    idle_ns = max(0, now_ns - int(self._last_nav_change_ns))
                    idle_ms = int(idle_ns / 1_000_000)
                    # Emit periodic stall evidence when selector had activity then goes idle.
                    if idle_ms >= 2000:
                        bucket = idle_ms // 2000
                        if bucket != self._idle_snapshot_bucket:
                            self._idle_snapshot_bucket = bucket
                            _emit_selector_debug(
                                emit,
                                enabled=deep_debug,
                                event="ui.selector.key.idle_after_activity",
                                selector_id=selector_id,
                                idle_ms=idle_ms,
                                focused_widget_id=focused_widget_id,
                                list_index=list_index,
                                nav_event_counter=self._nav_event_counter,
                                event_counts=dict(self._event_key_counts),
                                raw_counts=dict(self._raw_key_counts),
                                handled_counts=dict(self._handled_key_counts),
                            )
                probe = driver_probe
                if probe is not None:
                    snapshot = probe()
                    thread_snapshot = _selector_driver_thread_snapshot(
                        self.app,
                        include_stack=thread_stack_enabled,
                    )
                    merged_snapshot = dict(snapshot)
                    merged_snapshot.update(thread_snapshot)
                    _emit_selector_debug(
                        emit,
                        enabled=deep_debug,
                        event="ui.selector.key.driver.snapshot",
                        selector_id=selector_id,
                        **merged_snapshot,
                    )
                    read_calls = merged_snapshot.get("read_calls")
                    if isinstance(read_calls, int):
                        if read_calls != self._last_driver_read_calls:
                            self._last_driver_read_calls = read_calls
                            self._driver_idle_snapshot_bucket = -1
                        elif self._nav_event_counter > 0:
                            idle_ns = max(0, now_ns - int(self._last_nav_change_ns))
                            idle_ms = int(idle_ns / 1_000_000)
                            if idle_ms >= 2000:
                                bucket = idle_ms // 2000
                                if bucket != self._driver_idle_snapshot_bucket:
                                    self._driver_idle_snapshot_bucket = bucket
                                    _emit_selector_debug(
                                        emit,
                                        enabled=deep_debug,
                                        event="ui.selector.key.driver.idle_after_activity",
                                        selector_id=selector_id,
                                        idle_ms=idle_ms,
                                        focused_widget_id=focused_widget_id,
                                        list_index=list_index,
                                        nav_event_counter=self._nav_event_counter,
                                        read_calls=read_calls,
                                        read_bytes=merged_snapshot.get("read_bytes"),
                                        key_events_total=merged_snapshot.get("key_events_total"),
                                        non_key_messages=merged_snapshot.get("non_key_messages"),
                                        input_thread_alive=merged_snapshot.get("input_thread_alive"),
                                        input_thread_stack=(
                                            merged_snapshot.get("input_thread_stack")
                                            if thread_stack_enabled
                                            else None
                                        ),
                                    )

    return SelectorApp()
