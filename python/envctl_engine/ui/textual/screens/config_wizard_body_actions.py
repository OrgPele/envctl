from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ....config.persistence import ManagedConfigValues, config_review_text
from .config_wizard_fields import (
    _visible_command_fields,
    _visible_directory_fields,
    _visible_port_fields,
)


_FIELD_STEP_IDS = {"additional_services", "directories", "commands", "ports", "review"}
_MANAGED_IGNORE_WARNING = (
    "envctl local artifacts are managed through Git global excludes instead of repo "
    ".gitignore. On save, envctl configures or updates core.excludesFile to keep "
    ".envctl, MAIN_TASK.md, OLD_TASK_*.md, trees/, and trees-* out of git status."
)


@dataclass(slots=True)
class ConfigWizardBodyActions:
    values: ManagedConfigValues
    config_file_path: Path
    source_label: str
    current_step: Callable[[], str]
    set_display: Callable[[str, bool], None]
    update_widget: Callable[[str, str], None]
    render_choice_step: Callable[..., None]
    render_components_step: Callable[[], None]
    render_service_startup_step: Callable[[], None]
    sync_additional_service_inputs: Callable[[], None]
    sync_directory_inputs: Callable[[tuple[tuple[str, str], ...]], None]
    sync_port_inputs: Callable[[tuple[tuple[str, str], ...]], None]
    update_review: Callable[[str], None]

    def refresh_body(self) -> None:
        step = self.current_step()
        self._sync_body_visibility(step)
        if step == "welcome":
            self._render_welcome()
            return
        if step == "default_mode":
            self.render_choice_step(selected=self.values.default_mode, options=(("main", "Main"), ("trees", "Trees")))
            return
        if step == "components":
            self.render_components_step()
            return
        if step == "service_startup":
            self.render_service_startup_step()
            return
        if step == "additional_services":
            self.sync_additional_service_inputs()
            return
        if step == "directories":
            self._sync_directory_step()
            return
        if step == "commands":
            self._sync_command_step()
            return
        if step == "ports":
            self._sync_port_step()
            return
        if step == "review":
            self._render_review()

    def _sync_body_visibility(self, step: str) -> None:
        self.set_display("config-welcome", step == "welcome")
        self.set_display("config-list", step not in {"welcome", *_FIELD_STEP_IDS})
        self.set_display("config-directories", step in {"directories", "commands"})
        self.set_display("config-ports", step == "ports")
        self.set_display("config-additional-services", step == "additional_services")
        self.set_display("config-review-scroll", step == "review")
        self.set_display("config-empty", False)

    def _render_welcome(self) -> None:
        self.update_widget(
            "config-welcome",
            "envctl is the CLI for configuring, planning, and operating "
            "this repository's local environments.\n\n"
            "This wizard will guide you through:\n"
            "- selecting the default mode (main or trees)\n"
            "- deciding which components envctl should manage\n"
            "- reviewing directories, ports, and the generated .envctl file\n\n"
            f"The configuration will be written to {self.config_file_path}.\n"
            f"Starting values are loaded from: {self.source_label}.",
        )

    def _sync_directory_step(self) -> None:
        visible_fields = _visible_directory_fields(self.values)
        self.sync_directory_inputs(visible_fields)
        if visible_fields:
            return
        self.update_widget(
            "config-empty",
            "No directories need configuration for the components currently configured in main or trees.",
        )
        self.set_display("config-empty", True)

    def _sync_command_step(self) -> None:
        visible_fields = _visible_command_fields(self.values)
        self.sync_directory_inputs(visible_fields)
        if visible_fields:
            return
        self.update_widget(
            "config-empty",
            "No entrypoints or test commands need configuration "
            "for the components currently configured in main or trees.",
        )
        self.set_display("config-empty", True)

    def _sync_port_step(self) -> None:
        visible_fields = _visible_port_fields(self.values)
        self.sync_port_inputs(visible_fields)
        if visible_fields:
            return
        self.update_widget(
            "config-empty",
            "No ports need configuration for the components currently configured in main or trees.",
        )
        self.set_display("config-empty", True)

    def _render_review(self) -> None:
        self.update_review(
            config_review_text(
                path=self.config_file_path,
                values=self.values,
                source_label=self.source_label,
                ignore_warning=_MANAGED_IGNORE_WARNING,
            )
        )
