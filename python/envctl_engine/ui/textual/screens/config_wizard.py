from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ....config import LocalConfigState, StartupProfile
from ....requirements.core import dependency_definitions
from envctl_engine.ui.textual.compat import apply_textual_driver_compat, textual_run_policy
from envctl_engine.ui.capabilities import textual_importable as _textual_importable
from ....config.persistence import (
    ConfigSaveResult,
    ManagedConfigValues,
    config_review_text,
    managed_values_from_local_state,
    save_local_config,
    validate_managed_values,
)

def _emit(emit: Callable[..., None] | None, event: str, **payload: object) -> None:
    if callable(emit):
        emit(event, component="ui.textual.config_wizard", **payload)


@dataclass(slots=True)
class ConfigWizardResult:
    values: ManagedConfigValues
    save_result: ConfigSaveResult


_PROFILE_FIELDS: tuple[tuple[str, str], ...] = (
    ("backend_enable", "Backend"),
    ("frontend_enable", "Frontend"),
    *tuple((definition.id, definition.display_name.title()) for definition in dependency_definitions()),
)

_PORT_FIELDS: tuple[tuple[str, str], ...] = (
    ("backend_dir_name", "Backend directory"),
    ("frontend_dir_name", "Frontend directory"),
    ("backend_port_base", "Backend base port"),
    ("frontend_port_base", "Frontend base port"),
    *tuple(
        (f"dependency::{definition.id}::{resource.name}", resource.display_name or f"{definition.display_name} base port")
        for definition in dependency_definitions()
        for resource in definition.resources
    ),
    ("port_spacing", "Port spacing"),
)


def run_config_wizard_textual(
    *,
    local_state: LocalConfigState,
    initial_values: ManagedConfigValues | None = None,
    emit: Callable[..., None] | None = None,
    build_only: bool = False,
) -> ConfigWizardResult | None | object:
    if not _textual_importable():
        _emit(emit, "ui.fallback.non_interactive", reason="textual_missing", command="config_wizard")
        return None

    values = initial_values or managed_values_from_local_state(local_state)
    source_label = _source_label(local_state)
    run_policy = textual_run_policy(screen="config_wizard")

    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical
    from textual.events import Key
    from textual.widgets import Button, Footer, Input, Label, ListItem, ListView, Static

    class ConfigWizardApp(App[ConfigWizardResult | None]):
        BINDINGS = [
            Binding("enter", "submit_or_next", "Next"),
            Binding("q", "cancel", "Cancel"),
            Binding("ctrl+c", "cancel", "Cancel"),
            Binding("escape", "cancel", "Cancel"),
            Binding("up", "cursor_up", "Up"),
            Binding("down", "cursor_down", "Down"),
            Binding("space", "toggle_item", "Toggle"),
            Binding("tab", "focus_next", "Next"),
            Binding("shift+tab", "focus_previous", "Prev"),
        ]
        CSS = """
        Screen {
            align: center middle;
        }
        #config-shell {
            width: 94%;
            max-width: 140;
            height: 94%;
            border: round $accent;
            padding: 1 2;
        }
        #config-title {
            text-style: bold;
            margin-bottom: 1;
        }
        #config-source {
            color: $text-muted;
            margin-bottom: 1;
        }
        #config-step-title {
            text-style: bold;
            margin-bottom: 1;
        }
        #config-body {
            height: 1fr;
            border: round $surface;
            padding: 0 1;
        }
        #config-list {
            height: 1fr;
            border: tall $surface;
        }
        .config-row-selected {
            background: $accent 18%;
            border-left: wide $success;
        }
        .config-row-selected.-highlight {
            background: $accent 30%;
            border-left: wide $accent;
        }
        .config-row-unselected.-highlight {
            background: $warning 18%;
            border-left: wide $warning;
        }
        #config-ports {
            height: auto;
        }
        .port-field {
            margin-bottom: 1;
        }
        #config-review {
            height: 1fr;
            overflow: auto;
        }
        #config-status {
            margin-top: 1;
            color: $text-muted;
        }
        #config-actions {
            margin-top: 1;
            align-horizontal: right;
            height: auto;
        }
        """

        def __init__(self) -> None:
            super().__init__()
            self.step_index = 0
            self.values = ManagedConfigValues(
                default_mode=values.default_mode,
                main_profile=StartupProfile(
                    backend_enable=values.main_profile.backend_enable,
                    frontend_enable=values.main_profile.frontend_enable,
                    dependencies=dict(values.main_profile.dependencies),
                ),
                trees_profile=StartupProfile(
                    backend_enable=values.trees_profile.backend_enable,
                    frontend_enable=values.trees_profile.frontend_enable,
                    dependencies=dict(values.trees_profile.dependencies),
                ),
                port_defaults=type(values.port_defaults)(
                    backend_port_base=values.port_defaults.backend_port_base,
                    frontend_port_base=values.port_defaults.frontend_port_base,
                    dependency_ports={key: dict(resource_map) for key, resource_map in values.port_defaults.dependency_ports.items()},
                    port_spacing=values.port_defaults.port_spacing,
                ),
                backend_dir_name=values.backend_dir_name,
                frontend_dir_name=values.frontend_dir_name,
            )
            self._save_result: ConfigSaveResult | None = None
            self._steps = [
                "Welcome / Source",
                "Default Mode",
                "Main Startup Profile",
                "Trees Startup Profile",
                "Port Defaults",
                "Review / Save",
            ]

        def compose(self) -> ComposeResult:
            with Vertical(id="config-shell"):
                yield Static("envctl Startup Configuration", id="config-title")
                yield Static("", id="config-source")
                yield Static("", id="config-step-title")
                with Vertical(id="config-body"):
                    yield Static("", id="config-welcome")
                    yield ListView(id="config-list")
                    with Vertical(id="config-ports"):
                        for field_name, label in _PORT_FIELDS:
                            yield Label(label)
                            yield Input(value=str(self._port_value(field_name)), id=f"port-{field_name}", classes="port-field")
                    yield Static("", id="config-review")
                yield Static("", id="config-status")
                with Horizontal(id="config-actions"):
                    yield Button("Back", id="btn-back")
                    yield Button("Cancel", id="btn-cancel")
                    yield Button("Next", variant="success", id="btn-next")
                yield Footer()

        def on_mount(self) -> None:
            _emit(emit, "ui.screen.enter", screen="config_wizard", source=local_state.config_source)
            try:
                apply_textual_driver_compat(
                    driver=getattr(self.app, "_driver", None),
                    screen="config_wizard",
                    mouse_enabled=run_policy.mouse,
                    disable_focus_reporting=True,
                    emit=emit,
                )
            except Exception:
                pass
            self._refresh_all()

        def on_unmount(self) -> None:
            _emit(emit, "ui.screen.exit", screen="config_wizard")

        def on_key(self, event: Key) -> None:
            _emit(emit, "ui.key", screen="config_wizard", key=event.key, character=event.character)

        def _refresh_all(self) -> None:
            self.query_one("#config-source", Static).update(
                f"Path: {local_state.config_file_path} | Source: {source_label} | CLI/env overrides still apply"
            )
            self.query_one("#config-step-title", Static).update(self._steps[self.step_index])
            self._refresh_body()
            self._refresh_status()
            self._refresh_actions()
            self._focus_current_step()

        def _refresh_body(self) -> None:
            welcome = self.query_one("#config-welcome", Static)
            list_view = self.query_one("#config-list", ListView)
            ports = self.query_one("#config-ports", Vertical)
            review = self.query_one("#config-review", Static)
            welcome.display = self.step_index == 0
            list_view.display = self.step_index in {1, 2, 3}
            ports.display = self.step_index == 4
            review.display = self.step_index == 5
            if self.step_index == 0:
                message = (
                    f"envctl will write a managed startup config to {local_state.config_file_path}.\n\n"
                    f"Current source: {source_label}.\n"
                    "Legacy config is imported for prefill only.\n"
                    "Running services are not changed until the next start/restart."
                )
                welcome.update(message)
            elif self.step_index == 1:
                self._render_mode_step(list_view)
            elif self.step_index == 2:
                self._render_profile_step(list_view, profile=self.values.main_profile)
            elif self.step_index == 3:
                self._render_profile_step(list_view, profile=self.values.trees_profile)
            elif self.step_index == 5:
                preview = config_review_text(
                    path=local_state.config_file_path,
                    values=self.values,
                    source_label=source_label,
                    ignore_warning=".envctl will be added to .git/info/exclude on save when possible.",
                )
                review.update(preview)

        def _render_mode_step(self, list_view: ListView) -> None:
            list_view.clear()
            items: list[ListItem] = []
            for value, label in (("main", "Main"), ("trees", "Trees")):
                marker = "●" if self.values.default_mode == value else "○"
                classes = "config-row-selected" if self.values.default_mode == value else "config-row-unselected"
                items.append(ListItem(Label(f"{marker} {label}", markup=False), classes=classes))
            list_view.extend(items)
            list_view.index = 0 if self.values.default_mode == "main" else 1

        def _render_profile_step(self, list_view: ListView, *, profile: StartupProfile) -> None:
            list_view.clear()
            items: list[ListItem] = []
            for field_name, label in _PROFILE_FIELDS:
                enabled = bool(getattr(profile, field_name)) if field_name in {"backend_enable", "frontend_enable"} else profile.dependency_enabled(field_name)
                marker = "●" if enabled else "○"
                classes = "config-row-selected" if enabled else "config-row-unselected"
                items.append(ListItem(Label(f"{marker} {label}", markup=False), classes=classes))
            list_view.extend(items)
            list_view.index = 0

        def _refresh_actions(self) -> None:
            back = self.query_one("#btn-back", Button)
            next_button = self.query_one("#btn-next", Button)
            back.disabled = self.step_index == 0
            next_button.label = "Save" if self.step_index == len(self._steps) - 1 else "Next"

        def _refresh_status(self, message: str | None = None) -> None:
            status = self.query_one("#config-status", Static)
            if message is not None:
                status.update(message)
                return
            if self.step_index in {2, 3, 5}:
                validation = validate_managed_values(self.values)
                if validation.valid:
                    status.update("Configuration is valid.")
                else:
                    status.update(validation.errors[0])
                return
            if self.step_index == 4:
                status.update("Set backend/frontend directories and positive integer base ports.")
                return
            status.update("Use Enter for Next/Save, Space to toggle, Escape to cancel.")

        def _focus_current_step(self) -> None:
            if self.step_index in {1, 2, 3}:
                self.query_one("#config-list", ListView).focus()
            elif self.step_index == 4:
                self.query_one("#port-backend_port_base", Input).focus()
            else:
                self.query_one("#btn-next", Button).focus()

        def _port_value(self, field_name: str) -> int | str:
            if field_name == "backend_dir_name":
                return self.values.backend_dir_name
            if field_name == "frontend_dir_name":
                return self.values.frontend_dir_name
            if field_name == "backend_port_base":
                return self.values.port_defaults.backend_port_base
            if field_name == "frontend_port_base":
                return self.values.port_defaults.frontend_port_base
            if field_name == "port_spacing":
                return self.values.port_defaults.port_spacing
            if field_name.startswith("dependency::"):
                _, dependency_id, resource_name = field_name.split("::", 2)
                return self.values.port_defaults.dependency_port(dependency_id, resource_name)
            return 0

        def _current_profile(self) -> StartupProfile | None:
            if self.step_index == 2:
                return self.values.main_profile
            if self.step_index == 3:
                return self.values.trees_profile
            return None

        def action_cursor_up(self) -> None:
            if self.step_index not in {1, 2, 3}:
                return
            list_view = self.query_one("#config-list", ListView)
            if list_view.index is None:
                list_view.index = 0
                return
            list_view.index = max(list_view.index - 1, 0)

        def action_cursor_down(self) -> None:
            if self.step_index not in {1, 2, 3}:
                return
            list_view = self.query_one("#config-list", ListView)
            count = len(list_view.children)
            if count <= 0:
                return
            if list_view.index is None:
                list_view.index = 0
                return
            list_view.index = min(list_view.index + 1, count - 1)

        def action_toggle_item(self) -> None:
            if self.step_index == 1:
                list_view = self.query_one("#config-list", ListView)
                if list_view.index == 1:
                    self.values.default_mode = "trees"
                else:
                    self.values.default_mode = "main"
                self._refresh_body()
                self._refresh_status()
                return
            profile = self._current_profile()
            if profile is None:
                return
            list_view = self.query_one("#config-list", ListView)
            index = list_view.index or 0
            field_name = _PROFILE_FIELDS[index][0]
            if field_name in {"backend_enable", "frontend_enable"}:
                setattr(profile, field_name, not bool(getattr(profile, field_name)))
            else:
                profile.dependencies[field_name] = not profile.dependency_enabled(field_name)
            self._refresh_body()
            self._refresh_status()

        def action_focus_next(self) -> None:
            self.focus_next()

        def action_focus_previous(self) -> None:
            self.focus_previous()

        def action_cancel(self) -> None:
            self.exit(None)

        def action_submit_or_next(self) -> None:
            self._advance()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            button_id = event.button.id or ""
            if button_id == "btn-cancel":
                self.action_cancel()
                return
            if button_id == "btn-back":
                self._go_back()
                return
            if button_id == "btn-next":
                self._advance()

        def _go_back(self) -> None:
            if self.step_index <= 0:
                return
            self.step_index -= 1
            self._refresh_all()

        def _advance(self) -> None:
            if self.step_index == 4:
                if not self._apply_port_inputs():
                    return
            if self.step_index in {2, 3, 4, 5}:
                validation = validate_managed_values(self.values)
                if not validation.valid:
                    self._refresh_status(validation.errors[0])
                    return
            if self.step_index == len(self._steps) - 1:
                validation = validate_managed_values(self.values)
                if not validation.valid:
                    self._refresh_status(validation.errors[0])
                    return
                save_result = save_local_config(local_state=local_state, values=self.values)
                self._save_result = save_result
                self.exit(ConfigWizardResult(values=self.values, save_result=save_result))
                return
            self.step_index += 1
            self._refresh_all()

        def _apply_port_inputs(self) -> bool:
            new_values: dict[str, int] = {}
            for field_name, label in _PORT_FIELDS:
                raw = self.query_one(f"#port-{field_name}", Input).value.strip()
                if field_name in {"backend_dir_name", "frontend_dir_name"}:
                    if not raw:
                        self._refresh_status(f"{label} must not be empty.")
                        self.query_one(f"#port-{field_name}", Input).focus()
                        return False
                    setattr(self.values, field_name, raw)
                    continue
                if not raw.isdigit() or int(raw) < 1:
                    self._refresh_status(f"{label} must be a positive integer.")
                    self.query_one(f"#port-{field_name}", Input).focus()
                    return False
                new_values[field_name] = int(raw)
            for field_name, value in new_values.items():
                if field_name == "backend_port_base":
                    self.values.port_defaults.backend_port_base = value
                elif field_name == "frontend_port_base":
                    self.values.port_defaults.frontend_port_base = value
                elif field_name == "port_spacing":
                    self.values.port_defaults.port_spacing = value
                elif field_name.startswith("dependency::"):
                    _, dependency_id, resource_name = field_name.split("::", 2)
                    self.values.port_defaults.dependency_ports.setdefault(dependency_id, {})[resource_name] = value
            validation = validate_managed_values(self.values)
            if not validation.valid:
                self._refresh_status(validation.errors[0])
                return False
            return True

    app = ConfigWizardApp()
    if build_only:
        return app
    _emit(
        emit,
        "ui.textual.run_policy",
        screen="config_wizard",
        mouse_enabled=run_policy.mouse,
        reason=run_policy.reason,
        term_program=run_policy.term_program,
    )
    return app.run(mouse=run_policy.mouse)


def _source_label(local_state: LocalConfigState) -> str:
    if local_state.config_source == "envctl":
        return "existing .envctl"
    if local_state.config_source == "legacy_prefill":
        source_path = local_state.legacy_source_path or local_state.active_source_path
        if source_path is not None:
            return f"legacy import from {source_path.name}"
        return "legacy import"
    return "defaults"
