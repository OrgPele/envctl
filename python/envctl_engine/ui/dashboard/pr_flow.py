from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from envctl_engine.ui.capabilities import textual_importable
from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.textual.compat import apply_textual_driver_compat, textual_run_policy
from envctl_engine.ui.textual.list_controller import TextualListController
from envctl_engine.ui.textual.list_row_styles import apply_selectable_list_index
from envctl_engine.ui.textual.list_row_styles import focus_selectable_list
from envctl_engine.ui.textual.list_row_styles import selectable_list_row_classes
from envctl_engine.ui.textual.screens.selector.textual_app_chrome import SELECTOR_CSS


@dataclass(slots=True)
class PrFlowResult:
    project_names: list[str]
    base_branch: str | None
    cancelled: bool = False
    cancelled_step: str | None = None


@dataclass(slots=True)
class _Row:
    token: str
    label: str
    selected: bool = False


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
    initial_projects = {str(name).strip().lower() for name in (initial_project_names or []) if str(name).strip()}
    project_rows = [
        _Row(
            token=str(getattr(project, "name", "")).strip(),
            label=str(getattr(project, "name", "")).strip(),
            selected=str(getattr(project, "name", "")).strip().lower() in initial_projects,
        )
        for project in projects
        if str(getattr(project, "name", "")).strip()
    ]
    branch_rows = [
        _Row(
            token=str(option.token).strip(),
            label=str(option.label).strip() or str(option.token).strip(),
            selected=str(option.token).strip() == default_branch,
        )
        for option in branch_options
        if str(option.token).strip()
    ]
    if not project_rows or not branch_rows:
        return None

    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical
    from textual.events import Key
    from textual.widgets import Button, Footer, Label, ListItem, ListView, Static

    class PrFlowApp(App[PrFlowResult | None]):
        BINDINGS = [
            Binding("q", "cancel", "Cancel"),
            Binding("ctrl+c", "cancel", "Cancel"),
            Binding("escape", "cancel", "Cancel", False, True),
            Binding("up", "nav_up", "Up", False, True),
            Binding("down", "nav_down", "Down", False, True),
            Binding("j", "nav_down", "Down", False, True),
            Binding("s", "nav_down", "Down", False, True),
            Binding("k", "nav_up", "Up", False, True),
            Binding("w", "nav_up", "Up", False, True),
            Binding("space", "toggle", "Toggle", False, True),
            Binding("enter", "submit", "Confirm", False, True),
        ]
        CSS = SELECTOR_CSS

        def __init__(self) -> None:
            super().__init__()
            self._step = "branch" if len(project_rows) == 1 else "project"
            self._project_rows = project_rows
            self._branch_rows = branch_rows
            self._project_controller = TextualListController(
                self._project_rows,
                initial_model_index=next(
                    (index for index, row in enumerate(self._project_rows) if row.selected),
                    0,
                ),
            )
            self._branch_controller = TextualListController(
                self._branch_rows,
                initial_model_index=next(
                    (index for index, row in enumerate(self._branch_rows) if row.selected),
                    0,
                ),
            )
            self._project_list_index = 0
            self._branch_list_index = 0
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

        def on_mount(self) -> None:
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
            self._refresh()

        def on_unmount(self) -> None:
            _emit(emit, "ui.screen.exit", screen="dashboard_pr_flow")

        def _rows(self) -> list[_Row]:
            return self._branch_rows if self._step == "branch" else self._project_rows

        def _controller(self) -> TextualListController[_Row]:
            return self._branch_controller if self._step == "branch" else self._project_controller

        def _current_index(self) -> int:
            return self._branch_list_index if self._step == "branch" else self._project_list_index

        def _set_current_index(self, value: int | None) -> None:
            index = 0 if value is None else max(0, value)
            if self._step == "branch":
                self._branch_list_index = index
            else:
                self._project_list_index = index

        def _prompt_text(self) -> str:
            if self._step == "branch":
                return "Create PR into"
            return "Create PR for"

        def _status_text(self) -> str:
            rows = self._rows()
            selected_count = sum(1 for row in rows if row.selected)
            focus_index = self._focused_list_index() + 1 if rows else 0
            total = len(rows)
            if self._step == "branch":
                return f"Select base branch • focus: {focus_index}/{total}"
            return f"{selected_count} selected • focus: {focus_index}/{total}"

        def _row_text(self, row: _Row) -> str:
            marker = "●" if row.selected else "○"
            badge = "branch" if self._step == "branch" else "project"
            return f"{marker} {row.label}  ({badge})"

        async def _render_rows(self) -> None:
            list_view = self.query_one("#selector-list", ListView)
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
            index = self._controller().ensure_list_index(self._current_index())
            apply_selectable_list_index(list_view, index)
            self._set_current_index(list_view.index)
            focus_selectable_list(self, list_view, index)

        def _sync_actions(self) -> None:
            back = self.query_one("#btn-back", Button)
            next_button = self.query_one("#btn-next", Button)
            back.display = self._step == "branch" and len(self._project_rows) > 1
            next_button.label = "Create" if self._step == "branch" else "Next"

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

        def _focused_row(self) -> _Row | None:
            return self._controller().focused_row(self._focused_list_index())

        def action_nav_up(self) -> None:
            self._set_current_index(self._controller().cursor_up(self._focused_list_index()))
            self._refresh()

        def action_nav_down(self) -> None:
            self._set_current_index(self._controller().cursor_down(self._focused_list_index()))
            self._refresh()

        def action_toggle(self) -> None:
            self._set_current_index(self._focused_list_index())
            row = self._focused_row()
            if row is None:
                return
            if self._step == "branch":
                for candidate in self._branch_rows:
                    candidate.selected = candidate is row
            else:
                row.selected = not row.selected
            self._refresh()

        def _selected_projects(self) -> list[str]:
            return [row.token for row in self._project_rows if row.selected]

        def _selected_branch(self) -> str | None:
            selected = next((row.token for row in self._branch_rows if row.selected), "")
            if selected:
                return selected
            row = self._focused_row()
            return row.token if row is not None and self._step == "branch" else None

        def action_submit(self) -> None:
            if self._step == "project":
                selected_projects = self._selected_projects()
                if not selected_projects:
                    return
                self._step = "branch"
                self._refresh()
                return
            self.exit(
                PrFlowResult(
                    project_names=self._selected_projects(),
                    base_branch=self._selected_branch(),
                )
            )

        def action_cancel(self) -> None:
            self.exit(
                PrFlowResult(
                    project_names=[],
                    base_branch=None,
                    cancelled=True,
                    cancelled_step=self._step,
                )
            )

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "btn-cancel":
                self.action_cancel()
                return
            if event.button.id == "btn-back":
                if len(self._project_rows) == 1:
                    return
                self._step = "project"
                self._refresh()
                return
            self.action_submit()

        def on_list_view_selected(self, event: ListView.Selected) -> None:
            if self._suppress_list_selected_once:
                self._suppress_list_selected_once = False
                return
            self._set_current_index(event.index)
            self.action_toggle()

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
