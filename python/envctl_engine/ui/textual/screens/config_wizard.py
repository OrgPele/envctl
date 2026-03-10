from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable

from ....config import LocalConfigState, StartupProfile
from ....requirements.core import dependency_definitions
from ....config.persistence import (
    ConfigSaveResult,
    ManagedConfigValues,
    config_review_text,
    managed_values_from_local_state,
    save_local_config,
    validate_managed_values,
)
from envctl_engine.ui.capabilities import textual_importable as _textual_importable
from envctl_engine.ui.textual.compat import apply_textual_driver_compat, textual_run_policy


def _emit(emit: Callable[..., None] | None, event: str, **payload: object) -> None:
    if callable(emit):
        emit(event, component="ui.textual.config_wizard", **payload)


@dataclass(slots=True)
class ConfigWizardResult:
    values: ManagedConfigValues
    save_result: ConfigSaveResult


_ADVANCED_PROFILE_FIELDS: tuple[tuple[str, str], ...] = (
    ("backend_enable", "Backend"),
    ("frontend_enable", "Frontend"),
    *tuple((definition.id, definition.display_name.title()) for definition in dependency_definitions()),
)

_ADVANCED_STARTUP_FIELDS: tuple[tuple[str, str], ...] = (
    ("main", "Main: Enabled for envctl runs"),
    ("trees", "Trees: Enabled for envctl runs"),
)

_DIRECTORY_FIELDS: tuple[tuple[str, str], ...] = (
    ("backend_dir_name", "Backend directory"),
    ("frontend_dir_name", "Frontend directory"),
)

_PORT_FIELDS: tuple[tuple[str, str], ...] = (
    ("backend_port_base", "Backend base port"),
    ("frontend_port_base", "Frontend base port"),
    *tuple(
        (
            f"dependency::{definition.id}::{resource.name}",
            resource.display_name or f"{definition.display_name} base port",
        )
        for definition in dependency_definitions()
        for resource in definition.resources
    ),
    ("port_spacing", "Port spacing"),
)

_WIZARD_TYPES: tuple[tuple[str, str], ...] = (
    ("simple", "Simple"),
    ("advanced", "Advanced"),
)

_PRESET_OPTIONS: tuple[tuple[str, str], ...] = (
    ("standard", "Standard"),
    ("apps_only", "Apps Only"),
    ("disabled", "Disabled"),
)

_STEP_TITLES = {
    "welcome": "Welcome / Source",
    "wizard_type": "Wizard Type",
    "default_mode": "Default Mode",
    "main_preset": "Main Run Preset",
    "trees_preset": "Trees Run Preset",
    "startup_modes": "Run Enablement",
    "main_profile": "Main Run Settings",
    "trees_profile": "Trees Run Settings",
    "directories": "Directories",
    "ports": "Ports",
    "review": "Review / Save",
}

_STEP_HELP_TEXT = {
    "welcome": "This wizard saves the repo-local envctl run configuration. Existing services are not changed until a later command runs.",
    "wizard_type": "Choose the shorter preset-based flow or the full advanced flow with per-mode controls.",
    "default_mode": "Pick which mode envctl should use by default when you do not pass --main or --trees.",
    "main_preset": "Choose a simple preset for main mode. This controls what main mode is configured to run.",
    "trees_preset": "Choose a simple preset for trees mode. This is configured independently from main mode.",
    "startup_modes": "Turn main and trees on or off for envctl-run behavior. Detailed component settings stay configurable below.",
    "main_profile": "Choose which main-mode components are configured: backend, frontend, and built-in dependencies.",
    "trees_profile": "Choose which tree-mode components are configured: backend, frontend, and built-in dependencies.",
    "directories": "Set only the directories needed by the components currently configured in main or trees.",
    "ports": "Set only the ports needed by the components currently configured in main or trees.",
    "review": "Review the generated managed .envctl block before saving it to the repository.",
}

_TEXTUAL_ID_INVALID_CHARS = re.compile(r"[^A-Za-z0-9_-]+")


def _port_input_id(field_name: str) -> str:
    return f"port-{_TEXTUAL_ID_INVALID_CHARS.sub('-', field_name).strip('-')}"


def _directory_input_id(field_name: str) -> str:
    return f"directory-{_TEXTUAL_ID_INVALID_CHARS.sub('-', field_name).strip('-')}"


def _field_label_id(prefix: str, field_name: str) -> str:
    normalized = _TEXTUAL_ID_INVALID_CHARS.sub("-", field_name).strip("-")
    return f"{prefix}-label-{normalized}"


def _directory_error_id(field_name: str) -> str:
    normalized = _TEXTUAL_ID_INVALID_CHARS.sub("-", field_name).strip("-")
    return f"directory-error-{normalized}"


def _directory_field_name_from_input_id(input_id: str | None) -> str | None:
    normalized = str(input_id or "").strip()
    for field_name, _label in _DIRECTORY_FIELDS:
        if normalized == _directory_input_id(field_name):
            return field_name
    return None


def _resolve_directory_path(base_dir: Path, raw: str) -> Path:
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate
    return (base_dir / candidate).resolve()


def _directory_validation_message(base_dir: Path, label: str, raw: str) -> str | None:
    value = str(raw).strip()
    if not value:
        return f"{label} must not be empty."
    candidate = _resolve_directory_path(base_dir, value)
    if not candidate.exists():
        return f"Directory does not exist: {value}"
    if not candidate.is_dir():
        return f"Path is not a directory: {value}"
    return None


def _wizard_steps(wizard_type: str) -> list[str]:
    if wizard_type == "advanced":
        return [
            "welcome",
            "wizard_type",
            "default_mode",
            "startup_modes",
            "main_profile",
            "trees_profile",
            "directories",
            "ports",
            "review",
        ]
    return ["welcome", "wizard_type", "default_mode", "main_preset", "trees_preset", "review"]


def _copy_profile(profile: StartupProfile) -> StartupProfile:
    return StartupProfile(
        startup_enable=profile.startup_enable,
        backend_enable=profile.backend_enable,
        frontend_enable=profile.frontend_enable,
        dependencies=dict(profile.dependencies),
    )


def _clone_values(values: ManagedConfigValues) -> ManagedConfigValues:
    return ManagedConfigValues(
        default_mode=values.default_mode,
        main_profile=_copy_profile(values.main_profile),
        trees_profile=_copy_profile(values.trees_profile),
        port_defaults=type(values.port_defaults)(
            backend_port_base=values.port_defaults.backend_port_base,
            frontend_port_base=values.port_defaults.frontend_port_base,
            dependency_ports={
                key: dict(resource_map) for key, resource_map in values.port_defaults.dependency_ports.items()
            },
            port_spacing=values.port_defaults.port_spacing,
        ),
        backend_dir_name=values.backend_dir_name,
        frontend_dir_name=values.frontend_dir_name,
    )


def _preset_profile(mode: str, preset: str) -> StartupProfile:
    dependencies = {
        definition.id: (False if preset == "apps_only" else definition.enabled_by_default(mode))
        for definition in dependency_definitions()
    }
    return StartupProfile(
        startup_enable=preset != "disabled",
        backend_enable=True,
        frontend_enable=True,
        dependencies=dependencies,
    )


def _preset_for_profile(profile: StartupProfile, *, mode: str) -> str:
    for preset, _label in _PRESET_OPTIONS:
        candidate = _preset_profile(mode, preset)
        if (
            profile.startup_enable == candidate.startup_enable
            and profile.backend_enable == candidate.backend_enable
            and profile.frontend_enable == candidate.frontend_enable
            and profile.dependencies == candidate.dependencies
        ):
            return preset
    return "standard"


def _visible_directory_fields(values: ManagedConfigValues) -> tuple[tuple[str, str], ...]:
    profiles = [values.main_profile, values.trees_profile]
    show_backend = any(profile.backend_enable for profile in profiles)
    show_frontend = any(profile.frontend_enable for profile in profiles)
    visible: list[tuple[str, str]] = []
    if show_backend:
        visible.append(("backend_dir_name", "Backend directory"))
    if show_frontend:
        visible.append(("frontend_dir_name", "Frontend directory"))
    return tuple(visible)


def _visible_port_fields(values: ManagedConfigValues) -> tuple[tuple[str, str], ...]:
    profiles = [values.main_profile, values.trees_profile]
    show_backend = any(profile.backend_enable for profile in profiles)
    show_frontend = any(profile.frontend_enable for profile in profiles)
    enabled_dependencies = {
        definition.id
        for definition in dependency_definitions()
        if any(profile.dependency_enabled(definition.id) for profile in profiles)
    }
    visible: list[tuple[str, str]] = []
    if show_backend:
        visible.append(("backend_port_base", "Backend base port"))
    if show_frontend:
        visible.append(("frontend_port_base", "Frontend base port"))
    for definition in dependency_definitions():
        if definition.id not in enabled_dependencies:
            continue
        for resource in definition.resources:
            visible.append(
                (
                    f"dependency::{definition.id}::{resource.name}",
                    resource.display_name or f"{definition.display_name} base port",
                )
            )
    if visible:
        visible.append(("port_spacing", "Port spacing"))
    return tuple(visible)


def run_config_wizard_textual(
    *,
    local_state: LocalConfigState,
    initial_values: ManagedConfigValues | None = None,
    emit: Callable[..., None] | None = None,
    build_only: bool = False,
    default_wizard_type: str = "simple",
) -> ConfigWizardResult | None | object:
    if not _textual_importable():
        _emit(emit, "ui.fallback.non_interactive", reason="textual_missing", command="config_wizard")
        return None

    values = initial_values or managed_values_from_local_state(local_state)
    source_label = _source_label(local_state)
    run_policy = textual_run_policy(screen="config_wizard")

    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
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
        }
        #config-step-help {
            color: $text-muted;
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
            height: 1fr;
            overflow: auto;
        }
        #config-directories {
            height: 1fr;
            overflow: auto;
        }
        #config-empty {
            color: $text-muted;
        }
        .directory-field {
            margin-bottom: 1;
        }
        .directory-field.directory-invalid {
            background: $error 10%;
            border: tall $error;
        }
        .directory-error {
            color: $text-muted;
            margin-top: -1;
            margin-bottom: 1;
        }
        .directory-error-visible {
            color: $error;
        }
        .port-field {
            margin-bottom: 1;
        }
        #config-review-scroll {
            height: 1fr;
            overflow: auto;
        }
        #config-review {
            height: auto;
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
            self.values = _clone_values(values)
            self._save_result: ConfigSaveResult | None = None
            self._wizard_type = default_wizard_type if default_wizard_type in {"simple", "advanced"} else "simple"
            self._steps = _wizard_steps(self._wizard_type)
            self._simple_presets = {
                "main": _preset_for_profile(self.values.main_profile, mode="main"),
                "trees": _preset_for_profile(self.values.trees_profile, mode="trees"),
            }

        def compose(self) -> ComposeResult:
            with Vertical(id="config-shell"):
                yield Static("envctl Run Configuration", id="config-title")
                yield Static("", id="config-source")
                yield Static("", id="config-step-title")
                yield Static("", id="config-step-help")
                with Vertical(id="config-body"):
                    yield Static("", id="config-welcome")
                    yield ListView(id="config-list")
                    yield Static("", id="config-empty")
                    with VerticalScroll(id="config-directories"):
                        for field_name, label in _DIRECTORY_FIELDS:
                            yield Label(label, id=_field_label_id("directory", field_name))
                            yield Input(
                                value=str(self._field_value(field_name)),
                                id=_directory_input_id(field_name),
                                classes="directory-field",
                            )
                            yield Static("", id=_directory_error_id(field_name), classes="directory-error")
                    with VerticalScroll(id="config-ports"):
                        for field_name, label in _PORT_FIELDS:
                            yield Label(label, id=_field_label_id("port", field_name))
                            yield Input(
                                value=str(self._field_value(field_name)),
                                id=_port_input_id(field_name),
                                classes="port-field",
                            )
                    with VerticalScroll(id="config-review-scroll"):
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
            if event.key == "enter":
                current_step = self._current_step()
                if current_step in {
                    "wizard_type",
                    "default_mode",
                    "startup_modes",
                    "main_profile",
                    "trees_profile",
                    "main_preset",
                    "trees_preset",
                }:
                    list_view = self.query_one("#config-list", ListView)
                    if list_view.has_focus:
                        event.stop()
                        self._apply_list_selection()
                        self._advance()
                        return
            _emit(emit, "ui.key", screen="config_wizard", key=event.key, character=event.character)

        def on_input_changed(self, event: Input.Changed) -> None:
            field_name = _directory_field_name_from_input_id(getattr(event.input, "id", None))
            if field_name is None:
                return
            self._refresh_directory_validation(field_name, raw=event.value)
            if self._current_step() == "directories":
                self._refresh_status()

        def _current_step(self) -> str:
            return self._steps[self.step_index]

        def _profile_for_mode(self, mode: str) -> StartupProfile:
            return self.values.trees_profile if mode == "trees" else self.values.main_profile

        def _set_wizard_type(self, wizard_type: str) -> None:
            self._wizard_type = wizard_type
            self._steps = _wizard_steps(self._wizard_type)
            if self.step_index >= len(self._steps):
                self.step_index = len(self._steps) - 1

        def _refresh_all(self) -> None:
            self.query_one("#config-source", Static).update(
                f"Path: {local_state.config_file_path} | Source: {source_label} | CLI/env overrides still apply"
            )
            current_step = self._current_step()
            self.query_one("#config-step-title", Static).update(_STEP_TITLES[current_step])
            self.query_one("#config-step-help", Static).update(_STEP_HELP_TEXT[current_step])
            self._refresh_body()
            self._refresh_status()
            self._refresh_actions()
            self._focus_current_step()

        def _refresh_body(self) -> None:
            step = self._current_step()
            welcome = self.query_one("#config-welcome", Static)
            list_view = self.query_one("#config-list", ListView)
            empty = self.query_one("#config-empty", Static)
            directories = self.query_one("#config-directories", VerticalScroll)
            ports = self.query_one("#config-ports", VerticalScroll)
            review_scroll = self.query_one("#config-review-scroll", VerticalScroll)
            review = self.query_one("#config-review", Static)
            welcome.display = step == "welcome"
            list_view.display = step not in {"welcome", "directories", "ports", "review"}
            directories.display = step == "directories"
            ports.display = step == "ports"
            review_scroll.display = step == "review"
            empty.display = False
            if step == "welcome":
                welcome.update(
                    "envctl is the CLI for configuring, planning, and operating this repository's local environments.\n\n"
                    "This wizard will guide you through:\n"
                    "- choosing simple or advanced setup\n"
                    "- selecting the default mode (main or trees)\n"
                    "- deciding which components envctl should manage\n"
                    "- reviewing directories, ports, and the generated .envctl file\n\n"
                    f"The configuration will be written to {local_state.config_file_path}.\n"
                    f"Starting values are loaded from: {source_label}."
                )
                return
            if step == "wizard_type":
                self._render_choice_step(list_view, selected=self._wizard_type, options=_WIZARD_TYPES)
                return
            if step == "default_mode":
                self._render_choice_step(
                    list_view, selected=self.values.default_mode, options=(("main", "Main"), ("trees", "Trees"))
                )
                return
            if step == "startup_modes":
                self._render_startup_step(list_view)
                return
            if step in {"main_profile", "trees_profile"}:
                self._render_profile_step(
                    list_view, profile=self._profile_for_mode("main" if step == "main_profile" else "trees")
                )
                return
            if step in {"main_preset", "trees_preset"}:
                mode = "main" if step == "main_preset" else "trees"
                self._render_choice_step(list_view, selected=self._simple_presets[mode], options=_PRESET_OPTIONS)
                return
            if step == "directories":
                visible_fields = _visible_directory_fields(self.values)
                self._sync_directory_inputs(visible_fields)
                if not visible_fields:
                    empty.update(
                        "No directories need configuration for the components currently configured in main or trees."
                    )
                    empty.display = True
                return
            if step == "ports":
                visible_fields = _visible_port_fields(self.values)
                self._sync_port_inputs(visible_fields)
                if not visible_fields:
                    empty.update(
                        "No ports need configuration for the components currently configured in main or trees."
                    )
                    empty.display = True
                return
            if step == "review":
                review.update(
                    config_review_text(
                        path=local_state.config_file_path,
                        values=self.values,
                        source_label=source_label,
                        ignore_warning=".envctl and trees/ will be added to .gitignore on save when possible.",
                    )
                )

        def _render_choice_step(self, list_view, *, selected: str, options: tuple[tuple[str, str], ...]) -> None:
            list_view.clear()
            items: list[ListItem] = []
            default_index = 0
            for index, (value, label) in enumerate(options):
                is_selected = selected == value
                if is_selected:
                    default_index = index
                marker = "●" if is_selected else "○"
                classes = "config-row-selected" if is_selected else "config-row-unselected"
                items.append(ListItem(Label(f"{marker} {label}", markup=False), classes=classes))
            list_view.extend(items)
            list_view.index = default_index

        def _render_profile_step(self, list_view, *, profile: StartupProfile) -> None:
            list_view.clear()
            items: list[ListItem] = []
            for field_name, label in _ADVANCED_PROFILE_FIELDS:
                if field_name in {"backend_enable", "frontend_enable"}:
                    enabled = bool(getattr(profile, field_name))
                else:
                    enabled = profile.dependency_enabled(field_name)
                marker = "●" if enabled else "○"
                classes = "config-row-selected" if enabled else "config-row-unselected"
                items.append(ListItem(Label(f"{marker} {label}", markup=False), classes=classes))
            list_view.extend(items)
            list_view.index = 0

        def _render_startup_step(self, list_view) -> None:
            list_view.clear()
            items: list[ListItem] = []
            for mode, label in _ADVANCED_STARTUP_FIELDS:
                profile = self._profile_for_mode(mode)
                marker = "●" if profile.startup_enable else "○"
                classes = "config-row-selected" if profile.startup_enable else "config-row-unselected"
                items.append(ListItem(Label(f"{marker} {label}", markup=False), classes=classes))
            list_view.extend(items)
            list_view.index = 0

        def _sync_directory_inputs(self, visible_fields: tuple[tuple[str, str], ...]) -> None:
            visible_names = {field_name for field_name, _label in visible_fields}
            for field_name, _label in _DIRECTORY_FIELDS:
                label = self.query_one(f"#{_field_label_id('directory', field_name)}", Label)
                directory_input = self.query_one(f"#{_directory_input_id(field_name)}", Input)
                error = self.query_one(f"#{_directory_error_id(field_name)}", Static)
                label.display = field_name in visible_names
                directory_input.display = field_name in visible_names
                error.display = field_name in visible_names
                if field_name in visible_names:
                    directory_input.value = str(self._field_value(field_name))
                    self._refresh_directory_validation(field_name)
                else:
                    directory_input.remove_class("directory-invalid")
                    error.update("")
                    error.remove_class("directory-error-visible")

        def _sync_port_inputs(self, visible_fields: tuple[tuple[str, str], ...]) -> None:
            visible_names = {field_name for field_name, _label in visible_fields}
            for field_name, _label in _PORT_FIELDS:
                label = self.query_one(f"#{_field_label_id('port', field_name)}", Label)
                port_input = self.query_one(f"#{_port_input_id(field_name)}", Input)
                label.display = field_name in visible_names
                port_input.display = field_name in visible_names
                if field_name in visible_names:
                    port_input.value = str(self._field_value(field_name))

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
            step = self._current_step()
            if step in {"startup_modes", "main_profile", "trees_profile", "main_preset", "trees_preset", "review"}:
                validation = validate_managed_values(self.values)
                if validation.valid:
                    if step in {"main_preset", "trees_preset"}:
                        status.update("Simple presets overwrite detailed mode settings.")
                    elif step == "startup_modes":
                        status.update(
                            "Choose whether envctl may run main and trees by default. Detailed service toggles stay in the next screens."
                        )
                    else:
                        status.update("Configuration is valid.")
                else:
                    status.update(validation.errors[0])
                return
            if step == "directories":
                visible_fields = _visible_directory_fields(self.values)
                if visible_fields:
                    directory_error = self._first_directory_error()
                    if directory_error is not None:
                        status.update(directory_error)
                    else:
                        status.update("Only directories for components configured in main or trees are shown.")
                else:
                    status.update("No directories are needed for the components currently configured in main or trees.")
                return
            if step == "ports":
                visible_fields = _visible_port_fields(self.values)
                if visible_fields:
                    status.update("Only ports for components configured in main or trees are shown.")
                else:
                    status.update("No ports are needed for the components currently configured in main or trees.")
                return
            status.update("Use Enter for Next/Save, Space to toggle, Escape to cancel.")

        def _focus_current_step(self) -> None:
            step = self._current_step()
            if step in {
                "wizard_type",
                "default_mode",
                "startup_modes",
                "main_profile",
                "trees_profile",
                "main_preset",
                "trees_preset",
            }:
                self.query_one("#config-list", ListView).focus()
            elif step == "directories":
                visible_fields = _visible_directory_fields(self.values)
                if visible_fields:
                    self.query_one(f"#{_directory_input_id(visible_fields[0][0])}", Input).focus()
                else:
                    self.query_one("#btn-next", Button).focus()
            elif step == "ports":
                visible_fields = _visible_port_fields(self.values)
                if visible_fields:
                    self.query_one(f"#{_port_input_id(visible_fields[0][0])}", Input).focus()
                else:
                    self.query_one("#btn-next", Button).focus()
            elif step == "review":
                self.query_one("#config-review-scroll", VerticalScroll).focus()
            else:
                self.query_one("#btn-next", Button).focus()

        def _field_value(self, field_name: str) -> int | str:
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

        def _directory_label(self, field_name: str) -> str:
            for candidate, label in _DIRECTORY_FIELDS:
                if candidate == field_name:
                    return label
            return "Directory"

        def _directory_validation_error(self, field_name: str, *, raw: str | None = None) -> str | None:
            label = self._directory_label(field_name)
            value = str(self._field_value(field_name)) if raw is None else str(raw)
            return _directory_validation_message(local_state.base_dir, label, value)

        def _refresh_directory_validation(self, field_name: str, *, raw: str | None = None) -> None:
            directory_input = self.query_one(f"#{_directory_input_id(field_name)}", Input)
            error = self.query_one(f"#{_directory_error_id(field_name)}", Static)
            message = self._directory_validation_error(
                field_name, raw=raw if raw is not None else directory_input.value
            )
            if message is None:
                directory_input.remove_class("directory-invalid")
                error.update("")
                error.remove_class("directory-error-visible")
                return
            directory_input.add_class("directory-invalid")
            error.update(message)
            error.add_class("directory-error-visible")

        def _first_directory_error(self) -> str | None:
            for field_name, _label in _visible_directory_fields(self.values):
                message = self._directory_validation_error(field_name)
                if message is not None:
                    return message
            return None

        def _current_profile(self) -> StartupProfile | None:
            step = self._current_step()
            if step == "main_profile":
                return self.values.main_profile
            if step == "trees_profile":
                return self.values.trees_profile
            return None

        def action_cursor_up(self) -> None:
            if self._current_step() not in {
                "wizard_type",
                "default_mode",
                "startup_modes",
                "main_profile",
                "trees_profile",
                "main_preset",
                "trees_preset",
            }:
                return
            list_view = self.query_one("#config-list", ListView)
            if list_view.index is None:
                list_view.index = 0
                return
            list_view.index = max(list_view.index - 1, 0)

        def action_cursor_down(self) -> None:
            if self._current_step() not in {
                "wizard_type",
                "default_mode",
                "startup_modes",
                "main_profile",
                "trees_profile",
                "main_preset",
                "trees_preset",
            }:
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
            self._apply_list_selection(toggle_profiles=True)

        def _apply_list_selection(self, *, toggle_profiles: bool = False) -> None:
            step = self._current_step()
            list_view = self.query_one("#config-list", ListView)
            index = list_view.index or 0
            if step == "wizard_type":
                self._set_wizard_type(_WIZARD_TYPES[index][0])
                self._refresh_all()
                return
            if step == "default_mode":
                self.values.default_mode = ("main", "trees")[1 if index == 1 else 0]
                self._refresh_body()
                self._refresh_status()
                return
            if step in {"main_preset", "trees_preset"}:
                mode = "main" if step == "main_preset" else "trees"
                preset = _PRESET_OPTIONS[index][0]
                self._simple_presets[mode] = preset
                if mode == "main":
                    self.values.main_profile = _preset_profile(mode, preset)
                else:
                    self.values.trees_profile = _preset_profile(mode, preset)
                self._refresh_body()
                self._refresh_status()
                return
            if step == "startup_modes":
                if not toggle_profiles:
                    return
                mode = _ADVANCED_STARTUP_FIELDS[index][0]
                profile = self._profile_for_mode(mode)
                profile.startup_enable = not profile.startup_enable
                self._refresh_body()
                self._refresh_status()
                return
            profile = self._current_profile()
            if profile is None:
                return
            if not toggle_profiles:
                return
            field_name = _ADVANCED_PROFILE_FIELDS[index][0]
            if field_name in {"backend_enable", "frontend_enable"}:
                setattr(profile, field_name, not bool(getattr(profile, field_name)))
            else:
                profile.dependencies[field_name] = not profile.dependency_enabled(field_name)
            self._refresh_body()
            self._refresh_status()

        def action_focus_next(self) -> None:
            self.screen.focus_next()

        def action_focus_previous(self) -> None:
            self.screen.focus_previous()

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
            step = self._current_step()
            if step == "directories" and not self._apply_directory_inputs():
                return
            if step == "ports" and not self._apply_port_inputs():
                return
            if step in {
                "startup_modes",
                "main_profile",
                "trees_profile",
                "main_preset",
                "trees_preset",
                "directories",
                "ports",
                "review",
            }:
                validation = validate_managed_values(self.values)
                if not validation.valid:
                    self._refresh_status(validation.errors[0])
                    return
            if step == self._steps[-1]:
                save_result = save_local_config(local_state=local_state, values=self.values)
                self._save_result = save_result
                self.exit(ConfigWizardResult(values=self.values, save_result=save_result))
                return
            self.step_index += 1
            self._refresh_all()

        def _apply_directory_inputs(self) -> bool:
            for field_name, label in _visible_directory_fields(self.values):
                input_selector = f"#{_directory_input_id(field_name)}"
                directory_input = self.query_one(input_selector, Input)
                raw = directory_input.value.strip()
                directory_error = _directory_validation_message(local_state.base_dir, label, raw)
                self._refresh_directory_validation(field_name, raw=raw)
                if directory_error is not None:
                    self._refresh_status(directory_error)
                    directory_input.focus()
                    return False
                setattr(self.values, field_name, raw)
            return True

        def _apply_port_inputs(self) -> bool:
            new_values: dict[str, int] = {}
            for field_name, label in _visible_port_fields(self.values):
                input_selector = f"#{_port_input_id(field_name)}"
                port_input = self.query_one(input_selector, Input)
                raw = port_input.value.strip()
                if not raw.isdigit() or int(raw) < 1:
                    self._refresh_status(f"{label} must be a positive integer.")
                    port_input.focus()
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
