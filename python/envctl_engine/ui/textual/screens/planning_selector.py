from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
from typing import Callable

from envctl_engine.ui.capabilities import textual_importable as _textual_importable
from envctl_engine.ui.textual.compat import (
    apply_textual_driver_compat,
    handle_text_edit_key_alias,
    textual_run_policy,
)
from envctl_engine.ui.textual.list_controller import TextualListController
from envctl_engine.ui.textual.list_row_styles import (
    apply_selectable_list_index,
    focus_selectable_list,
    selectable_list_row_classes,
    selectable_list_row_css,
)
from .selector import (
    _deep_debug_enabled,
    _guard_textual_nonblocking_read,
    _instrument_textual_parser_keys,
    _selector_disable_focus_reporting_enabled,
    _selector_driver_thread_snapshot,
    _selector_driver_trace_enabled,
    _selector_key_trace_enabled,
    _selector_key_trace_verbose_enabled,
    _selector_thread_stack_enabled,
)

PLANNING_ROW_STYLES_CSS = selectable_list_row_css("planning-row")


def _emit(emit: Callable[..., None] | None, event: str, **payload: object) -> None:
    if not callable(emit):
        return
    emit(event, component="ui.textual.planning_selector", **payload)


@dataclass(slots=True)
class _PlanningRow:
    plan_file: str
    count: int
    existing: int
    visible: bool = True


def select_planning_counts_textual(
    *,
    planning_files: list[str],
    selected_counts: dict[str, int],
    existing_counts: dict[str, int],
    emit: Callable[..., None] | None = None,
) -> dict[str, int] | None:
    if not planning_files:
        return {}
    if not _textual_importable():
        _emit(emit, "ui.fallback.non_interactive", reason="textual_missing", command="planning_selector")
        return None

    deep_debug = _deep_debug_enabled(emit)
    key_trace_enabled = _selector_key_trace_enabled(emit)
    key_trace_verbose = _selector_key_trace_verbose_enabled(emit)
    driver_trace_enabled = _selector_driver_trace_enabled(emit)
    thread_stack_enabled = _selector_thread_stack_enabled(emit)
    disable_focus_reporting = _selector_disable_focus_reporting_enabled(emit)
    selector_id = "planning_selector"
    driver_probe: Callable[[], dict[str, object]] | None = None
    run_policy = textual_run_policy(screen="planning_selector")

    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical
    from textual.events import Key
    from textual.widgets import Button, Footer, Input, Label, ListItem, ListView, Static

    rows = [
        _PlanningRow(
            plan_file=plan_file,
            count=max(0, int(selected_counts.get(plan_file, 0))),
            existing=max(0, int(existing_counts.get(plan_file, 0))),
        )
        for plan_file in planning_files
    ]

    class PlanningSelectorApp(App[dict[str, int] | None]):
        BINDINGS = [
            Binding("enter", "submit", "Run"),
            Binding("q", "cancel", "Cancel"),
            Binding("ctrl+c", "cancel", "Cancel"),
            Binding("escape", "cancel", "Cancel"),
            Binding("up", "cursor_up", "Up"),
            Binding("down", "cursor_down", "Down"),
            Binding("space", "increment", "Increment"),
            Binding("left", "decrement", "Decrement"),
            Binding("right", "increment", "Increment"),
            Binding("+", "increment", "Increment"),
            Binding("-", "decrement", "Decrement"),
            Binding("ctrl+a", "toggle_visible", "Toggle visible"),
            Binding("/", "focus_filter", "Filter"),
            Binding("tab", "cycle_focus", "Focus"),
        ]
        CSS = (
            """
        Screen {
            align: center middle;
        }
        #planning-shell {
            width: 94%;
            max-width: 140;
            height: 94%;
            border: round $accent;
            padding: 1 2;
        }
        #planning-title {
            text-style: bold;
            margin-bottom: 1;
        }
        #planning-filter {
            margin-bottom: 1;
        }
        #planning-status {
            margin-bottom: 1;
            color: $text-muted;
        }
        #planning-list {
            height: 1fr;
            border: round $surface;
        }
        #planning-actions {
            margin-top: 1;
            align-horizontal: right;
            height: auto;
        }
        """
            + PLANNING_ROW_STYLES_CSS
        )

        def __init__(self) -> None:
            super().__init__()
            self._rows: list[_PlanningRow] = rows
            self._controller = TextualListController(self._rows)
            self._render_lock = asyncio.Lock()
            self._event_key_counts: dict[str, int] = {}
            self._key_snapshot_timer: object | None = None
            self._shutdown_emitted = False
            self._suppress_list_selected_once = False

        def compose(self) -> ComposeResult:
            filter_input = Input(placeholder="Filter planning files...", id="planning-filter")
            filter_input.can_focus = False
            with Vertical(id="planning-shell"):
                yield Static("Planning Selection", id="planning-title")
                yield filter_input
                yield Static("", id="planning-status")
                yield ListView(id="planning-list")
                with Horizontal(id="planning-actions"):
                    yield Button("Cancel", variant="default", id="btn-cancel")
                    yield Button("Run", variant="success", id="btn-run")
                yield Footer()

        async def on_mount(self) -> None:
            _emit(emit, "ui.screen.enter", screen="planning_selector", option_count=len(self._rows))
            await self._render_rows()
            self.action_focus_list()
            if disable_focus_reporting or not run_policy.mouse:
                try:
                    driver = getattr(self.app, "_driver", None)
                    apply_textual_driver_compat(
                        driver=driver,
                        screen="planning_selector",
                        mouse_enabled=run_policy.mouse,
                        disable_focus_reporting=disable_focus_reporting,
                        emit=emit,
                        selector_id=selector_id,
                    )
                    if disable_focus_reporting:
                        _emit(
                            emit,
                            "ui.selector.key.driver.focus_reporting",
                            selector_id=selector_id,
                            screen="planning_selector",
                            disabled=True,
                        )
                except Exception as exc:
                    _emit(
                        emit,
                        "ui.selector.key.driver.focus_reporting",
                        selector_id=selector_id,
                        screen="planning_selector",
                        disabled=False,
                        error=type(exc).__name__,
                    )
            if key_trace_enabled:
                self._key_snapshot_timer = self.set_interval(0.75, self._emit_key_snapshot)

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
                _emit(
                    emit,
                    "ui.selector.key.driver.thread.final",
                    selector_id=selector_id,
                    screen="planning_selector",
                    **_selector_driver_thread_snapshot(
                        self.app,
                        include_stack=thread_stack_enabled,
                    ),
                )
            _emit(emit, "ui.screen.exit", screen="planning_selector")
            self._shutdown_emitted = True

        def _list(self) -> ListView:
            return self.query_one("#planning-list", ListView)

        def _status(self) -> Static:
            return self.query_one("#planning-status", Static)

        def _focused_row(self) -> _PlanningRow | None:
            return self._controller.focused_row(self._list().index)

        async def _toggle_model_index(self, model_index: int) -> None:
            if model_index < 0 or model_index >= len(self._rows):
                return
            row = self._rows[model_index]
            _emit(
                emit,
                "ui.selection.interaction",
                screen="planning_selector",
                action="toggle",
                model_index=model_index,
                plan_file=row.plan_file,
                current_count=row.count,
            )
            if row.count > 0:
                await self._set_count(row, 0)
            else:
                await self._set_count(row, self._default_count(row))

        async def _render_rows(self) -> None:
            async with self._render_lock:
                list_view = self._list()
                filter_has_focus = self.query_one("#planning-filter", Input).has_focus
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
                    existing = f" (existing {row.existing}x)" if row.existing > 0 else ""
                    marker = "●" if row.count > 0 else "○"
                    text = f"{marker} [{row.count}x] {row.plan_file}{existing}"
                    rendered_items.append(
                        ListItem(
                            Label(text, markup=False),
                            id=f"planning-row-{idx}",
                            classes=selectable_list_row_classes("planning-row", selected=row.count > 0),
                        )
                    )
                if rendered_items:
                    await list_view.extend(rendered_items)
                apply_selectable_list_index(list_view, self._controller.restore_view_index(checkpoint))
                self._controller.finish_render()
                self._sync_status()
                self._sync_run_state()
                if not checkpoint.filter_has_focus:
                    self.action_focus_list()

        def _sync_status(self) -> None:
            visible = [row for row in self._rows if row.visible]
            selected = sum(1 for row in visible if row.count > 0)
            total_selected = sum(1 for row in self._rows if row.count > 0)
            self._status().update(
                f"{selected} selected visible • {total_selected} selected total • {len(visible)} visible"
            )

        def _sync_run_state(self) -> None:
            run_button = self.query_one("#btn-run", Button)
            run_button.disabled = not any((row.count > 0) or (row.existing > 0) for row in self._rows)

        @staticmethod
        def _default_count(row: _PlanningRow) -> int:
            return row.existing if row.existing > 0 else 1

        async def _set_count(self, row: _PlanningRow, count: int) -> None:
            row.count = max(0, int(count))
            _emit(emit, "ui.selection.toggle", target=row.plan_file, count=row.count)
            await self._render_rows()

        async def action_increment(self) -> None:
            row = self._focused_row()
            if row is None:
                return
            await self._set_count(row, row.count + 1)

        async def action_decrement(self) -> None:
            row = self._focused_row()
            if row is None:
                return
            await self._set_count(row, row.count - 1)

        async def action_toggle(self) -> None:
            model_index = self._focused_model_index()
            if model_index is None:
                return
            await self._toggle_model_index(model_index)

        def _focused_model_index(self) -> int | None:
            return self._controller.focused_model_index(self._list().index)

        async def action_toggle_visible(self) -> None:
            should_enable = self._controller.apply_visible_toggle(
                is_visible=lambda row: row.visible,
                is_active=lambda row: row.count > 0,
                activate=lambda row: setattr(row, "count", self._default_count(row)),
                deactivate=lambda row: setattr(row, "count", 0),
            )
            if should_enable is None:
                return
            _emit(emit, "ui.selection.toggle", target="__VISIBLE__", enabled=should_enable)
            await self._render_rows()

        def action_cursor_up(self) -> None:
            self._list().index = self._controller.cursor_up(self._list().index)

        def action_cursor_down(self) -> None:
            self._list().index = self._controller.cursor_down(self._list().index)

        def action_focus_filter(self) -> None:
            filter_input = self.query_one("#planning-filter", Input)
            filter_input.can_focus = True
            filter_input.focus()

        def action_focus_list(self) -> None:
            list_view = self._list()
            index = self._controller.ensure_list_index(list_view.index)
            apply_selectable_list_index(list_view, index)
            self.query_one("#planning-filter", Input).can_focus = False
            focus_selectable_list(self, list_view, index)

        def action_cycle_focus(self) -> None:
            next_target = self._controller.cycle_focus_target(
                filter_has_focus=self.query_one("#planning-filter", Input).has_focus
            )
            if next_target == "list":
                self.action_focus_list()
            else:
                self.action_focus_filter()

        def _result(self) -> dict[str, int]:
            has_existing = any(row.existing > 0 for row in self._rows)
            if has_existing:
                return {row.plan_file: int(row.count) for row in self._rows}
            return {row.plan_file: int(row.count) for row in self._rows if row.count > 0}

        def action_submit(self) -> None:
            result = self._result()
            if not result and not any(row.existing > 0 for row in self._rows):
                return
            _emit(emit, "ui.selection.confirm", selected_count=len(result), screen="planning_selector")
            self.exit(result)

        def action_cancel(self) -> None:
            _emit(emit, "ui.selection.cancel", screen="planning_selector")
            self.exit(None)

        async def on_list_view_selected(self, event: ListView.Selected) -> None:
            if self._suppress_list_selected_once:
                self._suppress_list_selected_once = False
                return
            _emit(
                emit,
                "ui.selection.interaction",
                screen="planning_selector",
                action="list_selected",
                list_index=event.index,
            )
            if event.index < 0 or event.index >= len(self._controller.index_map):
                _emit(
                    emit,
                    "ui.selection.interaction",
                    screen="planning_selector",
                    action="list_selected_out_of_range",
                    list_index=event.index,
                    visible_count=len(self._controller.index_map),
                )
                return
            model_index = self._controller.index_map[event.index]
            await self._toggle_model_index(model_index)

        async def on_key(self, event: Key) -> None:
            if self.focused is self.query_one("#planning-filter", Input) and handle_text_edit_key_alias(
                widget=self.query_one("#planning-filter", Input),
                event=event,
            ):
                return
            if event.key != "enter":
                return
            if self._list().has_focus:
                self._suppress_list_selected_once = True
                event.stop()
                self.action_submit()

        async def on_event(self, event: object) -> None:
            if not run_policy.mouse and event.__class__.__name__.startswith("Mouse"):
                stop = getattr(event, "stop", None)
                if callable(stop):
                    stop()
                return
            if key_trace_enabled and isinstance(event, Key):
                key = str(event.key)
                self._event_key_counts[key] = self._event_key_counts.get(key, 0) + 1
                if key_trace_verbose:
                    _emit(
                        emit,
                        "ui.selector.key.event",
                        selector_id=selector_id,
                        screen="planning_selector",
                        key=key,
                        list_index=self._list().index,
                    )
            await super().on_event(event)  # type: ignore[misc]

        def _emit_key_snapshot(self) -> None:
            if not key_trace_enabled:
                return
            _emit(
                emit,
                "ui.selector.key.snapshot",
                selector_id=selector_id,
                screen="planning_selector",
                event_counts=dict(self._event_key_counts),
                list_index=self._list().index,
            )
            probe = driver_probe
            if probe is not None:
                thread_snapshot = _selector_driver_thread_snapshot(
                    self.app,
                    include_stack=thread_stack_enabled,
                )
                snapshot = dict(probe())
                snapshot.update(thread_snapshot)
                _emit(
                    emit,
                    "ui.selector.key.driver.snapshot",
                    selector_id=selector_id,
                    screen="planning_selector",
                    **snapshot,
                )

        async def on_input_changed(self, event: Input.Changed) -> None:
            query = str(event.value or "").strip().lower()
            for row in self._rows:
                row.visible = query in row.plan_file.lower() if query else True
            _emit(emit, "ui.selection.filter.changed", query=query, screen="planning_selector")
            await self._render_rows()

        def on_input_submitted(self, _event: Input.Submitted) -> None:
            self.action_focus_list()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "btn-run":
                self.action_submit()
            elif event.button.id == "btn-cancel":
                self.action_cancel()

    with _guard_textual_nonblocking_read(
        emit=emit,
        selector_id=selector_id,
        deep_debug=deep_debug,
    ):
        with _instrument_textual_parser_keys(
            emit=emit,
            enabled=driver_trace_enabled,
            selector_id=selector_id,
            deep_debug=deep_debug,
            esc_delay_env_ms=0,
        ) as _driver_probe:
            driver_probe = _driver_probe
            _emit(
                emit,
                "ui.textual.run_policy",
                screen="planning_selector",
                mouse_enabled=run_policy.mouse,
                reason=run_policy.reason,
                term_program=run_policy.term_program,
            )
            app = PlanningSelectorApp()
            try:
                return app.run(mouse=run_policy.mouse)
            finally:

                def _emit_shutdown_snapshot() -> None:
                    if not key_trace_enabled:
                        return
                    _emit(
                        emit,
                        "ui.selector.key.driver.thread.final",
                        selector_id=selector_id,
                        screen="planning_selector",
                        **_selector_driver_thread_snapshot(
                            app,
                            include_stack=thread_stack_enabled,
                        ),
                    )
                    _emit(emit, "ui.screen.exit", screen="planning_selector")

                driver = getattr(app, "_driver", None)
                thread_snapshot = _selector_driver_thread_snapshot(
                    app,
                    include_stack=thread_stack_enabled,
                )
                if bool(thread_snapshot.get("input_thread_alive")) and driver is not None:
                    disable_input = getattr(driver, "disable_input", None)
                    if callable(disable_input):
                        try:
                            disable_input()
                        except Exception as exc:
                            _emit(
                                emit,
                                "ui.selector.driver_shutdown",
                                selector_id=selector_id,
                                screen="planning_selector",
                                action="disable_input",
                                error=type(exc).__name__,
                            )
                    deadline = time.monotonic() + 0.75
                    while time.monotonic() < deadline:
                        thread_snapshot = _selector_driver_thread_snapshot(
                            app,
                            include_stack=False,
                        )
                        if not bool(thread_snapshot.get("input_thread_alive")):
                            break
                        time.sleep(0.01)
                if not app._shutdown_emitted:
                    _emit_shutdown_snapshot()
