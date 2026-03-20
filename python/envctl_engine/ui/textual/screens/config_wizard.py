from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable

from ....actions.actions_test import (
    suggest_backend_test_command,
    suggest_frontend_test_command,
    suggest_frontend_test_path,
)
from ....config import LocalConfigState, StartupProfile
from ....config.persistence import (
    ConfigSaveResult,
    ManagedConfigValues,
    config_review_text,
    managed_values_from_local_state,
    save_local_config_with_ignore_policy,
    validate_managed_values,
)
from ....requirements.core import dependency_definitions
from ....runtime.command_resolution import suggest_service_directory, suggest_service_start_command
from envctl_engine.ui.capabilities import textual_importable as _textual_importable
from envctl_engine.ui.textual.compat import (
    apply_textual_driver_compat,
    handle_text_edit_key_alias,
    textual_run_policy,
)
from envctl_engine.ui.textual.list_row_styles import (
    apply_selectable_list_index,
    focus_selectable_list,
    selectable_list_default_index,
    selectable_list_row_classes,
    selectable_list_row_css,
)


def _emit(emit: Callable[..., None] | None, event: str, **payload: object) -> None:
    if callable(emit):
        emit(event, component="ui.textual.config_wizard", **payload)


@dataclass(slots=True)
class ConfigWizardResult:
    values: ManagedConfigValues
    save_result: ConfigSaveResult


_SERVICE_FIELDS: tuple[tuple[str, str], ...] = (
    ("backend_enable", "Backend"),
    ("frontend_enable", "Frontend"),
)

_SERVICE_STARTUP_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("startup_enable", "main", "Main - start this service with envctl"),
    ("startup_enable", "trees", "Trees - start this service with envctl"),
    ("backend_expect_listener", "main", "Main - wait for a listener/port before continuing"),
    ("backend_expect_listener", "trees", "Trees - wait for a listener/port before continuing"),
)

_COMPONENT_FIELDS: tuple[tuple[str, str], ...] = (
    *tuple((definition.id, definition.display_name.title()) for definition in dependency_definitions()),
)

_DIRECTORY_FIELDS: tuple[tuple[str, str], ...] = (
    ("backend_dir_name", "Backend directory"),
    ("frontend_dir_name", "Frontend directory"),
    ("frontend_test_path", "Frontend tests directory"),
)

_COMMAND_FIELDS: tuple[tuple[str, str], ...] = (
    ("backend_start_cmd", "Backend entrypoint"),
    ("frontend_start_cmd", "Frontend entrypoint"),
    ("backend_test_cmd", "Backend test command"),
    ("frontend_test_cmd", "Frontend test command"),
)

_PORT_FIELDS: tuple[tuple[str, str], ...] = (
    ("backend_port_base", "Backend base port"),
    ("frontend_port_base", "Frontend base port"),
    ("db_port_base", "Database base port"),
    ("redis_port_base", "Redis base port"),
    ("n8n_port_base", "n8n base port"),
    ("port_spacing", "Port spacing"),
)

_STEP_TITLES = {
    "welcome": "Welcome / Source",
    "default_mode": "Default Mode",
    "components": "Components",
    "service_startup": "Long-Running Service",
    "directories": "Directories",
    "commands": "Entrypoints / Commands",
    "ports": "Ports",
    "review": "Review / Save",
}

_STEP_HELP_TEXT = {
    "welcome": (
        "This wizard saves the repo-local envctl run configuration. "
        "Existing services are not changed until a later command runs."
    ),
    "default_mode": "Pick which mode envctl should use by default when you do not pass --main or --trees.",
    "components": (
        "Choose which services and dependencies envctl should manage. Rows apply to Main + Trees until split. "
        "Press D to split the focused row into separate main and trees settings."
    ),
    "service_startup": (
        "This looks like a backend-only project. Choose whether envctl should keep it running automatically in "
        "main and trees. CLI tools usually should not stay running."
    ),
    "directories": "Set only the directories needed by the components currently configured in main or trees.",
    "commands": (
        "Set only the entrypoints and test commands needed by the components currently configured in main or trees."
    ),
    "ports": "Set only the ports needed by the components currently configured in main or trees.",
    "review": "Review the generated managed .envctl block before saving it to the repository.",
}

_TEXTUAL_ID_INVALID_CHARS = re.compile(r"[^A-Za-z0-9_-]+")

CONFIG_ROW_STYLES_CSS = selectable_list_row_css("config-row")


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


def _entrypoint_validation_message(label: str, raw: str) -> str | None:
    value = str(raw).strip()
    if not value:
        return f"{label} must not be empty."
    return None


def _wizard_steps(values: ManagedConfigValues, *, include_service_startup: bool) -> list[str]:
    steps = ["welcome", "default_mode", "components"]
    if include_service_startup:
        steps.append("service_startup")
    if _visible_directory_fields(values):
        steps.append("directories")
    if _visible_command_fields(values):
        steps.append("commands")
    if _visible_port_fields(values):
        steps.append("ports")
    steps.append("review")
    return steps


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
        main_backend_expect_listener=values.main_backend_expect_listener,
        trees_backend_expect_listener=values.trees_backend_expect_listener,
        backend_dir_name=values.backend_dir_name,
        frontend_dir_name=values.frontend_dir_name,
        backend_start_cmd=values.backend_start_cmd,
        frontend_start_cmd=values.frontend_start_cmd,
        backend_test_cmd=values.backend_test_cmd,
        frontend_test_cmd=values.frontend_test_cmd,
        action_test_cmd=values.action_test_cmd,
        frontend_test_path=values.frontend_test_path,
    )


def _hydrate_wizard_values(values: ManagedConfigValues, *, base_dir: Path) -> ManagedConfigValues:
    hydrated = _clone_values(values)
    baseline_defaults = managed_values_from_local_state(
        LocalConfigState(
            base_dir=base_dir,
            config_file_path=base_dir / ".envctl",
            config_file_exists=False,
            config_source="defaults",
            active_source_path=None,
            legacy_source_path=None,
            explicit_path=None,
            parsed_values={},
            file_text="",
        )
    )
    backend_suggested = str(suggest_service_directory(service_name="backend", project_root=base_dir) or "").strip()
    frontend_suggested = str(suggest_service_directory(service_name="frontend", project_root=base_dir) or "").strip()
    if _should_hydrate_directory_value(
        current_value=hydrated.backend_dir_name,
        baseline_value=baseline_defaults.backend_dir_name,
        base_dir=base_dir,
        conventional_default="backend",
        suggested_value=backend_suggested,
    ):
        hydrated.backend_dir_name = backend_suggested
    if _should_hydrate_directory_value(
        current_value=hydrated.frontend_dir_name,
        baseline_value=baseline_defaults.frontend_dir_name,
        base_dir=base_dir,
        conventional_default="frontend",
        suggested_value=frontend_suggested,
    ):
        hydrated.frontend_dir_name = frontend_suggested
    if not str(hydrated.backend_start_cmd).strip():
        hydrated.backend_start_cmd = str(
            suggest_service_start_command(service_name="backend", project_root=base_dir) or ""
        ).strip()
    if not str(hydrated.frontend_start_cmd).strip():
        hydrated.frontend_start_cmd = str(
            suggest_service_start_command(service_name="frontend", project_root=base_dir) or ""
        ).strip()
    if not str(hydrated.backend_test_cmd).strip():
        hydrated.backend_test_cmd = str(suggest_backend_test_command(base_dir) or "").strip()
    if not str(hydrated.frontend_test_cmd).strip():
        hydrated.frontend_test_cmd = str(suggest_frontend_test_command(base_dir) or "").strip()
    if not str(hydrated.frontend_test_path).strip():
        hydrated.frontend_test_path = str(suggest_frontend_test_path(base_dir) or "").strip()
    return hydrated


def _should_hydrate_directory_value(
    *,
    current_value: str,
    baseline_value: str,
    base_dir: Path,
    conventional_default: str,
    suggested_value: str,
) -> bool:
    current = str(current_value or "").strip()
    if not current:
        return True
    if current == str(baseline_value or "").strip():
        return True
    if current != conventional_default or not suggested_value or suggested_value == current:
        return False
    return not (base_dir / current).exists()


def _visible_directory_fields(values: ManagedConfigValues) -> tuple[tuple[str, str], ...]:
    profiles = [values.main_profile, values.trees_profile]
    visible: list[tuple[str, str]] = []
    if any(profile.backend_enable for profile in profiles):
        visible.append(("backend_dir_name", "Backend directory"))
    if any(profile.frontend_enable for profile in profiles):
        visible.append(("frontend_dir_name", "Frontend directory"))
        visible.append(("frontend_test_path", "Frontend tests directory"))
    return tuple(visible)


def _visible_command_fields(values: ManagedConfigValues) -> tuple[tuple[str, str], ...]:
    profiles = [values.main_profile, values.trees_profile]
    visible: list[tuple[str, str]] = []
    backend_runs = any(profile.startup_enable and profile.backend_enable for profile in profiles)
    frontend_runs = any(profile.startup_enable and profile.frontend_enable for profile in profiles)
    if any(profile.backend_enable for profile in profiles):
        if backend_runs:
            visible.append(("backend_start_cmd", "Backend entrypoint"))
        visible.append(("backend_test_cmd", "Backend test command"))
    if any(profile.frontend_enable for profile in profiles):
        if frontend_runs:
            visible.append(("frontend_start_cmd", "Frontend entrypoint"))
        visible.append(("frontend_test_cmd", "Frontend test command"))
    return tuple(visible)


def _visible_port_fields(values: ManagedConfigValues) -> tuple[tuple[str, str], ...]:
    backend_uses_port = (
        values.main_profile.startup_enable
        and values.main_profile.backend_enable
        and values.main_backend_expect_listener
    ) or (
        values.trees_profile.startup_enable
        and values.trees_profile.backend_enable
        and values.trees_backend_expect_listener
    )
    frontend_uses_port = any(
        profile.startup_enable and profile.frontend_enable for profile in (values.main_profile, values.trees_profile)
    )
    running_dependencies = {
        definition.id
        for definition in dependency_definitions()
        if any(
            profile.startup_enable and profile.dependency_enabled(definition.id)
            for profile in (values.main_profile, values.trees_profile)
        )
    }
    visible: list[tuple[str, str]] = []
    if backend_uses_port:
        visible.append(("backend_port_base", "Backend base port"))
    if frontend_uses_port:
        visible.append(("frontend_port_base", "Frontend base port"))
    if running_dependencies & {"postgres", "supabase"}:
        visible.append(("db_port_base", "Database base port"))
    if "redis" in running_dependencies:
        visible.append(("redis_port_base", "Redis base port"))
    if "n8n" in running_dependencies:
        visible.append(("n8n_port_base", "n8n base port"))
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

    @dataclass(frozen=True, slots=True)
    class ComponentRow:
        label: str
        component_id: str | None = None
        mode: str | None = None
        kind: str = "item"

        @property
        def selectable(self) -> bool:
            return self.kind == "item" and self.component_id is not None

        @property
        def shared(self) -> bool:
            return self.selectable and self.mode is None

    class ConfigWizardApp(App[ConfigWizardResult | None]):
        BINDINGS = [
            Binding("q", "cancel", "Cancel"),
            Binding("ctrl+c", "cancel", "Cancel"),
            Binding("escape", "cancel", "Cancel"),
            Binding("d", "toggle_component_split", "Split"),
            Binding("tab", "focus_next", "Next"),
            Binding("shift+tab", "focus_previous", "Prev"),
        ]
        CSS = (
            """
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
        .config-section-header {
            margin-top: 1;
            padding: 0 1;
            background: transparent;
            border-left: none;
        }
        .config-section-header Label {
            color: $accent;
            text-style: bold;
        }
        .config-section-header.-highlight {
            background: transparent;
            border-left: none;
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
            + CONFIG_ROW_STYLES_CSS
        )

        def __init__(self) -> None:
            super().__init__()
            _ = default_wizard_type
            self.step_index = 0
            self.values = _hydrate_wizard_values(values, base_dir=local_state.base_dir)
            self._save_result: ConfigSaveResult | None = None
            self._steps: list[str] = []
            self._suppress_list_selected_once = False
            self.values.main_profile.backend_enable = bool(self.values.main_profile.backend_enable)
            self.values.main_profile.frontend_enable = bool(self.values.main_profile.frontend_enable)
            self.values.trees_profile.backend_enable = bool(self.values.trees_profile.backend_enable)
            self.values.trees_profile.frontend_enable = bool(self.values.trees_profile.frontend_enable)
            self._sync_startup_enable_flags()
            self._split_component_fields = {
                field_name for field_name, _label in _COMPONENT_FIELDS if self._component_values_differ(field_name)
            }
            self._sync_steps(current_step="welcome")

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
                        for field_name, label in (*_DIRECTORY_FIELDS, *_COMMAND_FIELDS):
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
                    yield Button("Cancel", id="btn-cancel")
                    yield Button("Back", id="btn-back")
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
            if self._text_input_has_focus() and handle_text_edit_key_alias(widget=self.focused, event=event):
                return
            if event.key == "enter":
                if self._button_has_focus():
                    return
                event.stop()
                event.prevent_default()
                self.action_submit_or_next()
                return
            if event.key == "right":
                if self._text_input_has_focus():
                    return
                event.stop()
                event.prevent_default()
                self.action_submit_or_next()
                return
            if event.key == "left":
                if self._text_input_has_focus():
                    return
                event.stop()
                event.prevent_default()
                self.action_go_back()
                return
            if event.key == "up":
                event.stop()
                event.prevent_default()
                self.action_cursor_up()
                return
            if event.key == "down":
                event.stop()
                event.prevent_default()
                self.action_cursor_down()
                return
            if event.key == "space":
                event.stop()
                event.prevent_default()
                self.action_toggle_item()
                return
            if event.key == "d":
                event.stop()
                event.prevent_default()
                self.action_toggle_component_split()
                return
            _emit(emit, "ui.key", screen="config_wizard", key=event.key, character=event.character)

        def _text_input_has_focus(self) -> bool:
            focused = self.focused
            return isinstance(focused, Input)

        def _button_has_focus(self) -> bool:
            focused = self.focused
            return isinstance(focused, Button)

        def on_input_changed(self, event: Input.Changed) -> None:
            field_name = _directory_field_name_from_input_id(getattr(event.input, "id", None))
            if field_name is None:
                return
            self._refresh_directory_validation(field_name, raw=event.value)
            if self._current_step() in {"directories", "commands"}:
                self._refresh_status()

        def _current_step(self) -> str:
            return self._steps[self.step_index]

        def _profile_for_mode(self, mode: str) -> StartupProfile:
            return self.values.trees_profile if mode == "trees" else self.values.main_profile

        def _should_show_service_startup_step(self) -> bool:
            profiles = (self.values.main_profile, self.values.trees_profile)
            backend_enabled = any(profile.backend_enable for profile in profiles)
            frontend_enabled = any(profile.frontend_enable for profile in profiles)
            return backend_enabled and not frontend_enabled

        def _sync_steps(self, *, current_step: str | None = None) -> None:
            target_step = current_step
            if target_step is None and self._steps:
                target_step = self._steps[min(self.step_index, len(self._steps) - 1)]
            self._steps = _wizard_steps(
                self.values,
                include_service_startup=self._should_show_service_startup_step(),
            )
            if not self._steps:
                self.step_index = 0
                return
            if target_step is None:
                self.step_index = min(self.step_index, len(self._steps) - 1)
                return
            if target_step in self._steps:
                self.step_index = self._steps.index(target_step)
                return
            if target_step == "service_startup":
                fallback = "directories"
                self.step_index = self._steps.index(fallback if fallback in self._steps else self._steps[-1])
                return
            self.step_index = min(self.step_index, len(self._steps) - 1)

        def _refresh_all(self) -> None:
            self._sync_steps()
            current_step = self._current_step()
            source_widget = self.query_one("#config-source", Static)
            if current_step == "welcome":
                source_widget.display = True
                source_widget.update(
                    f"Path: {local_state.config_file_path} | Source: {source_label} | CLI/env overrides still apply"
                )
            else:
                source_widget.display = False
                source_widget.update("")
            self.query_one("#config-step-title", Static).update(_STEP_TITLES[current_step])
            self.query_one("#config-step-help", Static).update(_STEP_HELP_TEXT[current_step])
            self._refresh_body()
            self._refresh_status()
            self._refresh_actions()
            self.refresh_bindings()
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
            list_view.display = step not in {"welcome", "directories", "commands", "ports", "review"}
            directories.display = step in {"directories", "commands"}
            ports.display = step == "ports"
            review_scroll.display = step == "review"
            empty.display = False
            if step == "welcome":
                welcome.update(
                    "envctl is the CLI for configuring, planning, and operating "
                    "this repository's local environments.\n\n"
                    "This wizard will guide you through:\n"
                    "- selecting the default mode (main or trees)\n"
                    "- deciding which components envctl should manage\n"
                    "- reviewing directories, ports, and the generated .envctl file\n\n"
                    f"The configuration will be written to {local_state.config_file_path}.\n"
                    f"Starting values are loaded from: {source_label}."
                )
                return
            if step == "default_mode":
                self._render_choice_step(
                    list_view,
                    selected=self.values.default_mode,
                    options=(("main", "Main"), ("trees", "Trees")),
                )
                return
            if step == "components":
                self._render_components_step(list_view)
                return
            if step == "service_startup":
                self._render_service_startup_step(list_view)
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
            if step == "commands":
                visible_fields = _visible_command_fields(self.values)
                self._sync_directory_inputs(visible_fields)
                if not visible_fields:
                    empty.update(
                        "No entrypoints or test commands need configuration "
                        "for the components currently configured in main or trees."
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
                        ignore_warning=(
                            "envctl local artifacts are managed through Git global excludes instead of repo .gitignore. "
                            "Configure core.excludesFile to keep .envctl, MAIN_TASK.md, OLD_TASK_*.md, trees/, and trees-* out of git status."
                        ),
                    )
                )

        def _render_choice_step(self, list_view, *, selected: str, options: tuple[tuple[str, str], ...]) -> None:
            list_view.clear()
            items: list[ListItem] = []
            selected_flags: list[bool] = []
            for value, label in options:
                is_selected = selected == value
                selected_flags.append(is_selected)
                marker = "●" if is_selected else "○"
                items.append(
                    ListItem(
                        Label(f"{marker} {label}", markup=False),
                        classes=selectable_list_row_classes("config-row", selected=is_selected),
                    )
                )
            list_view.extend(items)
            apply_selectable_list_index(list_view, selectable_list_default_index(selected_flags))

        def _component_rows(self) -> list[ComponentRow]:
            rows: list[ComponentRow] = []
            rows.append(ComponentRow(label="Services", kind="header"))
            for field_name, label in _SERVICE_FIELDS:
                if field_name in self._split_component_fields:
                    rows.append(ComponentRow(component_id=field_name, label=f"Main - {label}", mode="main"))
                    rows.append(ComponentRow(component_id=field_name, label=f"Trees - {label}", mode="trees"))
                else:
                    rows.append(ComponentRow(component_id=field_name, label=label))
            rows.append(ComponentRow(label="Dependencies", kind="header"))
            for field_name, label in _COMPONENT_FIELDS:
                if field_name in self._split_component_fields:
                    rows.append(ComponentRow(component_id=field_name, label=f"Main - {label}", mode="main"))
                    rows.append(ComponentRow(component_id=field_name, label=f"Trees - {label}", mode="trees"))
                else:
                    rows.append(ComponentRow(component_id=field_name, label=label))
            return rows

        def _render_components_step(self, list_view) -> None:
            list_view.clear()
            items: list[ListItem] = []
            rows = self._component_rows()
            selected_flags: list[bool] = []
            for row in rows:
                enabled = self._component_row_enabled(row) if row.selectable else False
                selected_flags.append(enabled)
                marker = "●" if enabled else "○"
                if not row.selectable:
                    items.append(
                        ListItem(
                            Label(row.label, markup=False),
                            classes="config-section-header",
                        )
                    )
                    continue
                suffix = " (Main + Trees)" if row.shared else ""
                items.append(
                    ListItem(
                        Label(f"{marker} {row.label}{suffix}", markup=False),
                        classes=selectable_list_row_classes("config-row", selected=enabled),
                    )
                )
            list_view.extend(items)
            apply_selectable_list_index(list_view, self._default_component_index(rows, selected_flags))

        def _render_service_startup_step(self, list_view) -> None:
            list_view.clear()
            items: list[ListItem] = []
            selected_flags: list[bool] = []
            for field_name, mode, label in _SERVICE_STARTUP_FIELDS:
                enabled = self._service_startup_value(field_name, mode)
                selected_flags.append(enabled)
                marker = "●" if enabled else "○"
                items.append(
                    ListItem(
                        Label(f"{marker} {label}", markup=False),
                        classes=selectable_list_row_classes("config-row", selected=enabled),
                    )
                )
            list_view.extend(items)
            apply_selectable_list_index(list_view, selectable_list_default_index(selected_flags))

        def _service_startup_value(self, field_name: str, mode: str) -> bool:
            if field_name == "startup_enable":
                return bool(self._profile_for_mode(mode).startup_enable)
            if field_name == "backend_expect_listener":
                return bool(
                    self.values.trees_backend_expect_listener
                    if mode == "trees"
                    else self.values.main_backend_expect_listener
                )
            return False

        def _toggle_service_startup_value(self, field_name: str, mode: str) -> None:
            if field_name == "startup_enable":
                profile = self._profile_for_mode(mode)
                profile.startup_enable = not profile.startup_enable
                return
            if field_name == "backend_expect_listener":
                if mode == "trees":
                    self.values.trees_backend_expect_listener = not self.values.trees_backend_expect_listener
                else:
                    self.values.main_backend_expect_listener = not self.values.main_backend_expect_listener

        def _sync_directory_inputs(self, visible_fields: tuple[tuple[str, str], ...]) -> None:
            visible_names = {field_name for field_name, _label in visible_fields}
            for field_name, _label in (*_DIRECTORY_FIELDS, *_COMMAND_FIELDS):
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
                self.refresh_bindings()
                return
            step = self._current_step()
            if step in {"components", "service_startup", "review"}:
                validation = validate_managed_values(
                    self.values,
                    require_entrypoints=step == "review",
                )
                if validation.valid:
                    if step == "components":
                        if self._component_split_available():
                            status.update(
                                "Configure components for Main + Trees together, "
                                "or split a row when they should differ. "
                                "Use Space to toggle rows, D to split/merge, and Enter only moves forward."
                            )
                        else:
                            status.update(
                                "Configure components for Main + Trees together. "
                                "Use Space to toggle rows and Enter only moves forward."
                            )
                    elif step == "service_startup":
                        status.update(
                            "Decide whether envctl should auto-start this backend-only service "
                            "and whether it should wait for a listener before continuing. "
                            "Disable listener waiting for long-running scripts or workers "
                            "that do not open a port. Use Space to toggle rows; Enter only moves forward."
                        )
                    else:
                        status.update("Configuration is valid.")
                else:
                    status.update(validation.errors[0])
                self.refresh_bindings()
                return
            if step == "directories":
                visible_fields = _visible_directory_fields(self.values)
                if visible_fields:
                    directory_error = self._first_directory_error(visible_fields=visible_fields)
                    if directory_error is not None:
                        status.update(directory_error)
                    else:
                        status.update("Only directories for components configured in main or trees are shown.")
                else:
                    status.update("No directories are needed for the components currently configured in main or trees.")
                self.refresh_bindings()
                return
            if step == "commands":
                visible_fields = _visible_command_fields(self.values)
                if visible_fields:
                    directory_error = self._first_directory_error(visible_fields=visible_fields)
                    if directory_error is not None:
                        status.update(directory_error)
                    else:
                        status.update("Only entrypoints and test commands for configured components are shown.")
                else:
                    status.update("No entrypoints or test commands are needed for the configured components.")
                self.refresh_bindings()
                return
            if step == "ports":
                visible_fields = _visible_port_fields(self.values)
                if visible_fields:
                    status.update("Only canonical ports for configured components are shown.")
                else:
                    status.update("No ports are needed for the components currently configured in main or trees.")
                self.refresh_bindings()
                return
            status.update("Use Enter for Next/Save, Space to toggle, Escape to cancel.")
            self.refresh_bindings()

        def _focus_current_step(self) -> None:
            step = self._current_step()
            if step in {"default_mode", "components", "service_startup"}:
                list_view = self.query_one("#config-list", ListView)
                if step == "components":
                    list_view.index = self._nearest_selectable_component_index(list_view.index or 0, step=1)
                focus_selectable_list(self, list_view, list_view.index)
            elif step in {"directories", "commands"}:
                visible_fields = (
                    _visible_directory_fields(self.values)
                    if step == "directories"
                    else _visible_command_fields(self.values)
                )
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
            if field_name == "backend_start_cmd":
                return self.values.backend_start_cmd
            if field_name == "frontend_start_cmd":
                return self.values.frontend_start_cmd
            if field_name == "backend_test_cmd":
                return self.values.backend_test_cmd
            if field_name == "frontend_test_cmd":
                return self.values.frontend_test_cmd
            if field_name == "frontend_test_path":
                return self.values.frontend_test_path
            if field_name == "backend_port_base":
                return self.values.port_defaults.backend_port_base
            if field_name == "frontend_port_base":
                return self.values.port_defaults.frontend_port_base
            if field_name == "db_port_base":
                return self.values.port_defaults.db_port_base
            if field_name == "redis_port_base":
                return self.values.port_defaults.redis_port_base
            if field_name == "n8n_port_base":
                return self.values.port_defaults.n8n_port_base
            if field_name == "port_spacing":
                return self.values.port_defaults.port_spacing
            return 0

        def _sync_startup_enable_flags(self) -> None:
            if self._should_show_service_startup_step():
                return
            for profile in (self.values.main_profile, self.values.trees_profile):
                profile.startup_enable = bool(
                    profile.backend_enable or profile.frontend_enable or any(profile.dependencies.values())
                )

        def _component_value(self, mode: str, field_name: str) -> bool:
            profile = self._profile_for_mode(mode)
            if field_name in {"backend_enable", "frontend_enable"}:
                return bool(getattr(profile, field_name))
            return profile.dependency_enabled(field_name)

        def _set_component_value(self, mode: str, field_name: str, enabled: bool) -> None:
            profile = self._profile_for_mode(mode)
            if field_name in {"backend_enable", "frontend_enable"}:
                setattr(profile, field_name, enabled)
                return
            profile.dependencies[field_name] = enabled

        def _component_values_differ(self, field_name: str) -> bool:
            return self._component_value("main", field_name) != self._component_value("trees", field_name)

        def _component_row_enabled(self, row: ComponentRow) -> bool:
            if not row.selectable:
                return False
            if row.shared:
                return self._component_value("main", row.component_id or "")
            return self._component_value(row.mode or "main", row.component_id or "")

        def _default_component_index(self, rows: list[ComponentRow], selected_flags: list[bool]) -> int:
            selected_index = selectable_list_default_index(selected_flags)
            if 0 <= selected_index < len(rows) and rows[selected_index].selectable:
                return selected_index
            return next((index for index, row in enumerate(rows) if row.selectable), 0)

        def _nearest_selectable_component_index(self, index: int, *, step: int) -> int:
            rows = self._component_rows()
            if not rows:
                return 0
            candidate = max(0, min(index, len(rows) - 1))
            if rows[candidate].selectable:
                return candidate
            probe = candidate
            while 0 <= probe + step < len(rows):
                probe += step
                if rows[probe].selectable:
                    return probe
            probe = candidate
            while 0 <= probe - step < len(rows):
                probe -= step
                if rows[probe].selectable:
                    return probe
            return candidate

        def _directory_label(self, field_name: str) -> str:
            for candidate, label in _DIRECTORY_FIELDS:
                if candidate == field_name:
                    return label
            return "Directory"

        def _directory_validation_error(self, field_name: str, *, raw: str | None = None) -> str | None:
            label = self._directory_label(field_name)
            value = str(self._field_value(field_name)) if raw is None else str(raw)
            if field_name in {"backend_start_cmd", "frontend_start_cmd"}:
                return _entrypoint_validation_message(label, value)
            if field_name in {"backend_test_cmd", "frontend_test_cmd"}:
                return None
            if field_name == "frontend_test_path":
                if not value.strip():
                    return None
                return _directory_validation_message(local_state.base_dir, label, value)
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

        def _first_directory_error(self, *, visible_fields: tuple[tuple[str, str], ...] | None = None) -> str | None:
            fields = visible_fields if visible_fields is not None else _visible_directory_fields(self.values)
            for field_name, _label in fields:
                message = self._directory_validation_error(field_name)
                if message is not None:
                    return message
            return None

        def action_cursor_up(self) -> None:
            if self._current_step() not in {"default_mode", "components", "service_startup"}:
                return
            list_view = self.query_one("#config-list", ListView)
            if list_view.index is None:
                list_view.index = 0
            else:
                list_view.index = max(list_view.index - 1, 0)
            if self._current_step() == "components":
                list_view.index = self._nearest_selectable_component_index(list_view.index or 0, step=-1)
            self._sync_focus_driven_selection()
            self._refresh_status()

        def action_cursor_down(self) -> None:
            if self._current_step() not in {"default_mode", "components", "service_startup"}:
                return
            list_view = self.query_one("#config-list", ListView)
            count = len(list_view.children)
            if count <= 0:
                return
            if list_view.index is None:
                list_view.index = 0
            else:
                list_view.index = min(list_view.index + 1, count - 1)
            if self._current_step() == "components":
                list_view.index = self._nearest_selectable_component_index(list_view.index or 0, step=1)
            self._sync_focus_driven_selection()
            self._refresh_status()

        def _sync_focus_driven_selection(self) -> None:
            if self._current_step() != "default_mode":
                return
            list_view = self.query_one("#config-list", ListView)
            index = list_view.index or 0
            self.values.default_mode = "trees" if index == 1 else "main"
            self._refresh_body()
            self._refresh_status()

        def action_toggle_item(self) -> None:
            step = self._current_step()
            if step == "components":
                self._toggle_components_row()
                return
            if step == "service_startup":
                self._toggle_service_startup_row()

        def _toggle_service_startup_row(self) -> None:
            list_view = self.query_one("#config-list", ListView)
            index = list_view.index or 0
            field_name, mode, _label = _SERVICE_STARTUP_FIELDS[index]
            self._toggle_service_startup_value(field_name, mode)
            self._sync_steps(current_step="service_startup")
            self._refresh_body()
            self._refresh_status()
            self._refresh_actions()
            list_view = self.query_one("#config-list", ListView)
            apply_selectable_list_index(list_view, min(index, max(len(list_view.children) - 1, 0)))
            focus_selectable_list(self, list_view, list_view.index)

        def _toggle_components_row(self) -> None:
            list_view = self.query_one("#config-list", ListView)
            index = list_view.index or 0
            rows = self._component_rows()
            if not rows:
                return
            row = rows[index]
            if not row.selectable:
                return
            enabled = not self._component_row_enabled(row)
            if row.shared:
                self._set_component_value("main", row.component_id or "", enabled)
                self._set_component_value("trees", row.component_id or "", enabled)
            else:
                self._set_component_value(row.mode or "main", row.component_id or "", enabled)
            self._sync_startup_enable_flags()
            self._sync_steps(current_step="components")
            self._refresh_body()
            self._refresh_status()
            self._refresh_actions()
            list_view = self.query_one("#config-list", ListView)
            apply_selectable_list_index(list_view, min(index, max(len(list_view.children) - 1, 0)))
            focus_selectable_list(self, list_view, list_view.index)

        def _toggle_component_split(self) -> None:
            if not self._component_split_available():
                return
            list_view = self.query_one("#config-list", ListView)
            index = list_view.index or 0
            rows = self._component_rows()
            if not rows:
                return
            row = rows[index]
            if not row.selectable:
                return
            component_id = row.component_id or ""
            if component_id in self._split_component_fields:
                if self._component_values_differ(component_id):
                    self._refresh_status(
                        "Main and Trees differ for this component. Make them match before merging the split rows."
                    )
                    return
                self._split_component_fields.remove(component_id)
            else:
                self._split_component_fields.add(component_id)
            self._refresh_body()
            self._refresh_status()
            list_view = self.query_one("#config-list", ListView)
            updated_rows = self._component_rows()
            if component_id in self._split_component_fields:
                preferred_mode = row.mode or "main"
                target_index = next(
                    (
                        candidate_index
                        for candidate_index, candidate in enumerate(updated_rows)
                        if candidate.component_id == component_id and candidate.mode == preferred_mode
                    ),
                    0,
                )
            else:
                target_index = next(
                    (
                        candidate_index
                        for candidate_index, candidate in enumerate(updated_rows)
                        if candidate.component_id == component_id and candidate.shared
                    ),
                    0,
                )
            apply_selectable_list_index(list_view, target_index)
            focus_selectable_list(self, list_view, list_view.index)

        def _component_split_available(self) -> bool:
            if self._current_step() != "components":
                return False
            list_view = self.query_one("#config-list", ListView)
            if self.focused is not list_view:
                return False
            rows = self._component_rows()
            if not rows:
                return False
            index = list_view.index or 0
            if index < 0 or index >= len(rows):
                return False
            return rows[index].selectable

        def on_list_view_selected(self, event: ListView.Selected) -> None:
            if self._suppress_list_selected_once:
                self._suppress_list_selected_once = False
                return
            step = self._current_step()
            if step not in {"default_mode", "components", "service_startup"}:
                return
            list_view = self.query_one("#config-list", ListView)
            list_view.index = event.index
            if step == "default_mode":
                self._sync_focus_driven_selection()
            elif step == "components":
                self._toggle_components_row()
            else:
                self._toggle_service_startup_row()

        def action_focus_next(self) -> None:
            self.screen.focus_next()
            self._refresh_status()

        def action_focus_previous(self) -> None:
            self.screen.focus_previous()
            self._refresh_status()

        def action_cancel(self) -> None:
            self.exit(None)

        def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
            if action == "toggle_component_split":
                return True if self._component_split_available() else False
            return super().check_action(action, parameters)

        def action_go_back(self) -> None:
            self._go_back()

        def action_toggle_component_split(self) -> None:
            self._toggle_component_split()

        def action_submit_or_next(self) -> None:
            if self._current_step() in {"default_mode", "components", "service_startup"}:
                list_view = self.query_one("#config-list", ListView)
                if list_view.has_focus:
                    self._suppress_list_selected_once = True
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
                self.action_submit_or_next()

        def _go_back(self) -> None:
            if self.step_index <= 0:
                return
            self.step_index -= 1
            self._refresh_all()

        def _advance(self) -> None:
            step = self._current_step()
            if step in {"directories", "commands"} and not self._apply_directory_inputs():
                return
            if step == "ports" and not self._apply_port_inputs():
                return
            if step in {"components", "service_startup", "directories", "commands", "ports", "review"}:
                validation = validate_managed_values(
                    self.values,
                    require_directories=step in {"directories", "commands", "ports", "review"},
                    require_entrypoints=step in {"commands", "ports", "review"},
                )
                if not validation.valid:
                    self._refresh_status(validation.errors[0])
                    return
            if step == self._steps[-1]:
                save_result = save_local_config_with_ignore_policy(
                    local_state=local_state,
                    values=self.values,
                    update_global_ignores=False,
                )
                self._save_result = save_result
                self.exit(ConfigWizardResult(values=self.values, save_result=save_result))
                return
            self.step_index += 1
            self._refresh_all()

        def _apply_directory_inputs(self) -> bool:
            visible_fields = (
                _visible_directory_fields(self.values)
                if self._current_step() == "directories"
                else _visible_command_fields(self.values)
            )
            for field_name, label in visible_fields:
                directory_input = self.query_one(f"#{_directory_input_id(field_name)}", Input)
                raw = directory_input.value.strip()
                if field_name in {"backend_start_cmd", "frontend_start_cmd"}:
                    directory_error = _entrypoint_validation_message(label, raw)
                elif field_name in {"backend_test_cmd", "frontend_test_cmd"}:
                    directory_error = None
                elif field_name == "frontend_test_path":
                    directory_error = _directory_validation_message(local_state.base_dir, label, raw) if raw else None
                else:
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
                port_input = self.query_one(f"#{_port_input_id(field_name)}", Input)
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
                elif field_name == "db_port_base":
                    self.values.port_defaults.dependency_ports.setdefault("postgres", {})["primary"] = value
                    self.values.port_defaults.dependency_ports.setdefault("supabase", {})["db"] = value
                elif field_name == "redis_port_base":
                    self.values.port_defaults.dependency_ports.setdefault("redis", {})["primary"] = value
                elif field_name == "n8n_port_base":
                    self.values.port_defaults.dependency_ports.setdefault("n8n", {})["primary"] = value
                elif field_name == "port_spacing":
                    self.values.port_defaults.port_spacing = value
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
