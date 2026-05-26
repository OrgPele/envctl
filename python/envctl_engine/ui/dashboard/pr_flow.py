from __future__ import annotations

from typing import Callable, ClassVar, Sequence

from envctl_engine.ui.dashboard.pr_flow_state import PrFlowResult
from envctl_engine.ui.dashboard.pr_flow_state import PrFlowRow
from envctl_engine.ui.dashboard.pr_flow_state import PrFlowState
from envctl_engine.ui.dashboard.pr_flow_state import build_branch_rows
from envctl_engine.ui.dashboard.pr_flow_state import build_project_rows
from envctl_engine.ui.capabilities import textual_importable
from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.textual.compat import apply_textual_driver_compat, textual_run_policy
from envctl_engine.ui.textual.list_controller import TextualListController
from envctl_engine.ui.textual.list_row_styles import apply_selectable_list_index
from envctl_engine.ui.textual.list_row_styles import selectable_list_row_classes
from envctl_engine.ui.textual.screens.selector.textual_app_chrome import SELECTOR_CSS


def _emit(emit: Callable[..., None] | None, event: str, **payload: object) -> None:
    if callable(emit):
        emit(event, component="ui.dashboard.pr_flow", **payload)


def run_pr_flow(
    *,
    projects: Sequence[object],
    initial_project_names: Sequence[str] | None,
    branch_options: Sequence[SelectorItem],
    default_branch: str,
    emit: Callable[..., None] | None = None,
    build_only: bool = False,
) -> PrFlowResult | None | object:
    if not textual_importable():
        return None

    run_policy = textual_run_policy(screen="selector")
    project_rows = build_project_rows(projects, initial_project_names)
    branch_rows = build_branch_rows(branch_options, default_branch)
    if not project_rows or not branch_rows:
        return None
    state = PrFlowState.create(project_rows=project_rows, branch_rows=branch_rows)

    from textual.app import App, ComposeResult
    from textual.binding import Binding, BindingType
    from textual.containers import Horizontal, Vertical
    from textual.events import Key
    from textual.widgets import Button, Footer, Label, ListItem, ListView, Static

    class PrFlowApp(App[PrFlowResult | None]):
        BINDINGS: ClassVar[list[BindingType]] = [
            Binding("q", "cancel", "Cancel"),
            Binding("ctrl+c", "cancel", "Cancel"),
            Binding("escape", "cancel", "Cancel", show=False, priority=True),
            Binding("up", "nav_up", "Up", show=False, priority=True),
            Binding("down", "nav_down", "Down", show=False, priority=True),
            Binding("j", "nav_down", "Down", show=False, priority=True),
            Binding("s", "nav_down", "Down", show=False, priority=True),
            Binding("k", "nav_up", "Up", show=False, priority=True),
            Binding("w", "nav_up", "Up", show=False, priority=True),
            Binding("space", "toggle_selection", "Toggle", show=False, priority=True),
            Binding("enter", "submit", "Confirm", show=False, priority=True),
        ]
        CSS = SELECTOR_CSS

        def __init__(self) -> None:
            super().__init__()
            self._state = state
            self._project_controller = TextualListController(
                self._state.project_rows,
                initial_model_index=next(
                    (index for index, row in enumerate(self._state.project_rows) if row.selected),
                    0,
                ),
            )
            self._branch_controller = TextualListController(
                self._state.branch_rows,
                initial_model_index=next(
                    (index for index, row in enumerate(self._state.branch_rows) if row.selected),
                    0,
                ),
            )
            self._suppress_list_selected_once = False

        def compose(self) -> ComposeResult:
            with Vertical(id="selector-shell"):
                yield Static("", id="selector-prompt")
                yield Static("", id="selector-status")
                yield ListView(id="selector-list")
                with Horizontal(id="selector-actions"):
                    yield Button("Back", id="btn-back")
                    yield Button("Cancel", variant="default", id="btn-cancel")
                    yield Button("Next", variant="success", id="btn-next")
                yield Footer()

        async def on_mount(self) -> None:
            _emit(emit, "ui.screen.enter", screen="dashboard_pr_flow")
            try:
                apply_textual_driver_compat(
                    driver=getattr(self.app, "_driver", None),
                    screen="selector",
                    mouse_enabled=run_policy.mouse,
                    disable_focus_reporting=True,
                    emit=lambda event, **payload: _emit(emit, event, **payload),
                )
            except Exception:
                pass
            self.query_one("#selector-prompt", Static).update(self._prompt_text())
            self.query_one("#selector-status", Static).update(self._status_text())
            self._sync_actions()
            await self._render_rows()

        def on_unmount(self) -> None:
            _emit(emit, "ui.screen.exit", screen="dashboard_pr_flow")

        def _rows(self) -> list[PrFlowRow]:
            return self._state.rows()

        def _controller(self) -> TextualListController[PrFlowRow]:
            return self._branch_controller if self._state.step == "branch" else self._project_controller

        def _current_index(self) -> int:
            return self._state.current_index()

        def _set_current_index(self, value: int | None) -> None:
            self._state.set_current_index(value)

        def _prompt_text(self) -> str:
            return self._state.prompt_text()

        def _status_text(self) -> str:
            rows = self._rows()
            focus_index = self._focused_list_index() + 1 if rows else 0
            return self._state.status_text(focus_index=focus_index)

        def _row_text(self, row: PrFlowRow) -> str:
            return self._state.row_text(row)

        async def _render_rows(self) -> None:
            list_view = self.query_one("#selector-list", ListView)
            live_index = self._current_index()
            await list_view.clear()
            rows = self._rows()
            items = [
                ListItem(
                    Label(self._row_text(row), markup=False),
                    classes=selectable_list_row_classes("selector-row", selected=row.selected),
                )
                for row in rows
            ]
            if items:
                await list_view.extend(items)
            index = self._controller().ensure_list_index(live_index)
            apply_selectable_list_index(list_view, index)
            self._set_current_index(index)
            list_view.focus()
            apply_selectable_list_index(list_view, index)

        def _sync_actions(self) -> None:
            back = self.query_one("#btn-back", Button)
            next_button = self.query_one("#btn-next", Button)
            back.display = self._state.can_go_back()
            next_button.label = "Create" if self._state.step == "branch" else "Next"

        def _refresh(self) -> None:
            self.query_one("#selector-prompt", Static).update(self._prompt_text())
            self.query_one("#selector-status", Static).update(self._status_text())
            self._sync_actions()
            self.run_worker(self._render_rows(), exclusive=True)

        def _focused_list_index(self) -> int:
            try:
                list_view = self.query_one("#selector-list", ListView)
            except Exception:
                return self._current_index()
            if list_view.index is not None and list_view.index >= 0:
                return int(list_view.index)
            return self._current_index()

        def _focused_row(self) -> PrFlowRow | None:
            return self._controller().focused_row(self._focused_list_index())

        def action_nav_up(self) -> None:
            self._set_current_index(self._controller().cursor_up(self._current_index()))
            self._refresh()

        def action_nav_down(self) -> None:
            self._set_current_index(self._controller().cursor_down(self._current_index()))
            self._refresh()

        def action_toggle_selection(self) -> None:
            self._set_current_index(self._focused_list_index())
            row = self._focused_row()
            if row is None:
                return
            self._state.toggle_row(row)
            self._refresh()

        def action_submit(self) -> None:
            if self._state.step == "project":
                if not self._state.advance_to_branch_if_ready():
                    return
                self._refresh()
                return
            self.exit(self._state.result(focused_row=self._focused_row()))

        def action_cancel(self) -> None:
            self.exit(self._state.cancel_result())

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "btn-cancel":
                self.action_cancel()
                return
            if event.button.id == "btn-back":
                if not self._state.back_to_project_step():
                    return
                self._refresh()
                return
            self.action_submit()

        def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
            self._set_current_index(event.list_view.index)
            self.query_one("#selector-status", Static).update(self._status_text())

        def on_list_view_selected(self, event: ListView.Selected) -> None:
            if self._suppress_list_selected_once:
                self._suppress_list_selected_once = False
                return
            self._set_current_index(event.index)
            self.action_toggle_selection()

        def on_key(self, event: Key) -> None:
            list_view = self.query_one("#selector-list", ListView)
            if event.key == "enter" and list_view.has_focus:
                self._suppress_list_selected_once = True
                event.stop()
                event.prevent_default()
                self.action_submit()
                return

    app = PrFlowApp()
    if build_only:
        return app
    return app.run(mouse=run_policy.mouse)
