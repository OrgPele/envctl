from __future__ import annotations

import asyncio
import time
from typing import Callable

from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.textual.list_controller import TextualListController
from envctl_engine.ui.textual.list_row_styles import apply_selectable_list_index
from envctl_engine.ui.textual.list_row_styles import focus_selectable_list
from envctl_engine.ui.textual.list_row_styles import selectable_list_row_classes
from envctl_engine.ui.textual.compat import handle_text_edit_key_alias
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
    initial_navigation: tuple[str, ...] = (),
    exclusive_token: str | None = None,
):
    status_error_timeout_seconds = 3.0
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical
    from textual.events import Click, Key
    from textual.widgets import Button, Footer, Input, Label, ListItem, ListView, Static

    class SelectorApp(App[list[str] | None]):
        ESCAPE_TO_MINIMIZE = False
        BINDINGS = [
            Binding(*binding[:3], show=binding[3], priority=binding[4]) if len(binding) == 5 else Binding(*binding)
            for binding in SELECTOR_BINDINGS
        ]
        CSS = SELECTOR_CSS

        def __init__(self) -> None:
            super().__init__()
            self._rows: list[_RowRef] = []
            self._initial_model_index: int | None = None
            self._last_focused_model_index: int | None = None
            self._last_user_model_index: int | None = None
            for idx, item in enumerate(options):
                selected = str(item.token).strip() in initial_token_set
                if selected and self._initial_model_index is None:
                    self._initial_model_index = idx
                if selected and not multi:
                    selected = self._initial_model_index == idx
                self._rows.append(_RowRef(item=item, selected=selected, visible=True))
            self._last_user_model_index = self._initial_model_index
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
            self._status_error_message = ""
            self._status_error_timer: object | None = None
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
                self.call_after_refresh(self._apply_initial_navigation)

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
            base_classes = selectable_list_row_classes("selector-row", selected=row.selected)
            return f"{base_classes} kind-{row.item.kind.replace('_', '-')}"

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
                apply_selectable_list_index(list_view, self._controller.restore_view_index(checkpoint))
                self._controller.finish_render()
                self._initial_model_index = None
                self._sync_status()
                self._sync_confirm_state()
                if not checkpoint.filter_has_focus:
                    self.action_focus_list()

        def _sync_status(self) -> None:
            visible = sum(1 for row in self._rows if row.visible)
            selected = sum(1 for row in self._rows if row.visible and row.selected)
            if selected:
                self._clear_status_error()
            focus_text = "focus: -"
            focused_view_index = self._list().index
            if (
                focused_view_index is not None
                and focused_view_index >= 0
                and focused_view_index < len(self._controller.index_map)
            ):
                focused_model_index = self._controller.index_map[focused_view_index]
                self._last_focused_model_index = focused_model_index
                focused_row = self._rows[focused_model_index]
                focus_text = (
                    f"focus: {focused_view_index + 1}/{len(self._controller.index_map)} {focused_row.item.label}"
                )
            status = f"{selected} selected • {visible} visible • {len(self._rows)} total • {focus_text}"
            if deep_debug and self._nav_event_counter > 0:
                status += f" • key#{self._nav_event_counter}:{self._last_nav_key}"
                if self._edge_hint:
                    status += f" • {self._edge_hint}"
            if self._status_error_message:
                status = self._status_error_message
            status_widget = self._status()
            status_widget.set_class(bool(self._status_error_message), "selector-status-error")
            status_widget.update(status)

        def _clear_status_error(self) -> None:
            if not self._status_error_message:
                return
            self._status_error_message = ""
            timer = self._status_error_timer
            if timer is not None:
                try:
                    timer.stop()  # type: ignore[union-attr]
                except Exception:
                    pass
                self._status_error_timer = None
            try:
                self._sync_status()
            except Exception:
                pass

        def _schedule_status_error_clear(self) -> None:
            timer = self._status_error_timer
            if timer is not None:
                try:
                    timer.stop()  # type: ignore[union-attr]
                except Exception:
                    pass
            self._status_error_timer = self.set_timer(status_error_timeout_seconds, self._clear_status_error)

        def _touch_status_error_timeout(self) -> None:
            if not self._status_error_message:
                return
            self._schedule_status_error_clear()

        def _show_status_error(self, message: str) -> None:
            self._status_error_message = message.strip()
            self._schedule_status_error_clear()
            self._sync_status()

        def _sync_confirm_state(self) -> None:
            run_button = self.query_one("#btn-run", Button)
            run_button.disabled = not bool(self._controller.index_map)

        def _apply_initial_navigation(self) -> None:
            if not initial_navigation:
                return
            self.action_focus_list(reason="initial_navigation")

            async def _run_initial_navigation() -> None:
                for action in initial_navigation:
                    if action == "down":
                        await self.action_nav_down()
                    elif action == "up":
                        await self.action_nav_up()

            asyncio.create_task(_run_initial_navigation())

        def _focused_row(self) -> _RowRef | None:
            return self._controller.focused_row(self._list().index)

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
            if model_index < 0 or model_index >= len(self._rows):
                return
            row = self._rows[model_index]
            row_token = str(row.item.token)
            if not multi:
                for candidate in self._rows:
                    candidate.selected = False
            row.selected = not row.selected if multi else True
            if multi and row.selected and exclusive_token:
                if row_token == exclusive_token:
                    for idx, candidate in enumerate(self._rows):
                        if idx != model_index:
                            candidate.selected = False
                else:
                    for candidate in self._rows:
                        if str(candidate.item.token) == exclusive_token:
                            candidate.selected = False
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
            if multi and exclusive_token:
                visible_indexes = [idx for idx, row in enumerate(self._rows) if row.visible]
                selectable_indexes = [
                    idx for idx in visible_indexes if str(self._rows[idx].item.token) != exclusive_token
                ]
                if not selectable_indexes:
                    selectable_indexes = visible_indexes
                should_select = any(not self._rows[idx].selected for idx in selectable_indexes)
                for idx in visible_indexes:
                    self._rows[idx].selected = should_select and idx in selectable_indexes
                _emit(emit, "ui.selection.toggle", token="__VISIBLE__", selected=should_select)
                await self._render_rows()
                self.action_focus_list(reason="toggle_visible")
                return
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

        async def action_nav_up(self) -> None:
            list_index_before = self._controller.ensure_list_index(self._list().index)
            focus_before = self._focused_widget_id()
            if not self._list().has_focus:
                target_index = self._controller.cursor_up(list_index_before)
                self.action_focus_list(reason="key_recover", target_index=target_index)
            else:
                self.action_cursor_up()
            list_index_after = self._list().index
            focused_model_index = self._focused_model_index()
            if focused_model_index is not None:
                self._last_user_model_index = focused_model_index
            await self._sync_single_select_focus_selection(reason="nav_up")
            self._nav_event_counter += 1
            self._last_nav_change_ns = time.monotonic_ns()
            self._idle_snapshot_bucket = -1
            self._last_nav_key = "up"
            self._edge_hint = (
                "top boundary" if list_index_before is not None and list_index_after == list_index_before == 0 else ""
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
                self.action_cursor_down()
            list_index_after = self._list().index
            focused_model_index = self._focused_model_index()
            if focused_model_index is not None:
                self._last_user_model_index = focused_model_index
            await self._sync_single_select_focus_selection(reason="nav_down")
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

        def action_focus_list(self, *, reason: str = "focus_list", target_index: int | None = None) -> None:
            list_view = self._list()
            index = self._controller.ensure_list_index(target_index if target_index is not None else list_view.index)
            apply_selectable_list_index(list_view, index)
            self._allow_filter_focus = False
            focus_selectable_list(self, list_view, index)
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
            return [row.item.token for row in self._rows if row.selected and row.visible]

        async def action_submit(self, *, cause: str = "enter") -> None:
            if self.query_one("#selector-filter", Input).has_focus:
                self.action_focus_list(reason="submit_from_filter")
            values = self._selected_values()
            if not values and not multi:
                focused = self._focused_model_index()
                if focused is not None and 0 <= focused < len(self._rows):
                    row = self._rows[focused]
                    if row.visible:
                        values = [row.item.token]
                        row.selected = True
            if not values:
                self._show_status_error("No items were selected. Press Space or click to select at least one.")
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
            if self._suppress_list_selected_once:
                self._suppress_list_selected_once = False
                return
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
            self.action_focus_list(reason="list_selected")

        async def on_click(self, event: Click) -> None:
            if multi:
                return
            widget = getattr(event, "widget", None)
            while widget is not None:
                widget_id = str(getattr(widget, "id", "") or "").strip()
                if widget_id.startswith("selector-row-"):
                    try:
                        model_index = int(widget_id.rsplit("-", 1)[1])
                    except (TypeError, ValueError):
                        return
                    if model_index < 0 or model_index >= len(self._rows):
                        return
                    event.stop()
                    await self._select_model_index(model_index)
                    await self.action_submit(cause="mouse_click")
                    return
                widget = getattr(widget, "parent", None)

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
            if event.key == "tab":
                event.stop()
                event.prevent_default()
                self.action_cycle_focus()
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
                return
            if filter_focused and handle_text_edit_key_alias(
                widget=self.query_one("#selector-filter", Input), event=event
            ):
                return
            if event.key == "enter":
                event.stop()
                event.prevent_default()
                self._suppress_list_selected_once = True
                await self.action_submit(cause="enter_key")
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
                return
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

        async def _maybe_handle_filter_focus_key(self, event: Key) -> bool:
            if self._focused_widget_id() != "selector-filter":
                return False
            if event.key not in {"up", "down", "j", "k", "w", "s", "space"}:
                return False
            event.stop()
            event.prevent_default()
            self.action_focus_list(reason="filter_key_recover")
            if event.key in {"up", "k", "w"}:
                await self.action_nav_up()
            elif event.key in {"down", "j", "s"}:
                await self.action_nav_down()
            else:
                await self.action_toggle()
            return True

        async def on_event(self, event: object) -> None:
            if isinstance(event, Key) or event.__class__.__name__.startswith("Mouse"):
                self._touch_status_error_timeout()
            if not mouse_enabled and event.__class__.__name__.startswith("Mouse"):
                stop = getattr(event, "stop", None)
                if callable(stop):
                    stop()
                return
            if isinstance(event, Key) and await self._maybe_handle_filter_focus_key(event):
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
            self._emit_focus(reason="focus_event")

        def on_unmount(self) -> None:
            self._clear_status_error()
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
            if focused is None:
                focused = self._last_user_model_index
            if focused is None:
                focused = self._last_focused_model_index
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
                                        merged_snapshot.get("input_thread_stack") if thread_stack_enabled else None
                                    ),
                                )

    return SelectorApp()
