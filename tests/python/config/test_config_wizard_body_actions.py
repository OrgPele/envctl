from __future__ import annotations

from pathlib import Path
import unittest

from envctl_engine.config import PortDefaults, StartupProfile
from envctl_engine.config.persistence import ManagedConfigValues
from envctl_engine.ui.textual.screens.config_wizard_body_actions import (
    ConfigWizardBodyActions,
)


class ConfigWizardBodyActionsTests(unittest.TestCase):
    def _values(self) -> ManagedConfigValues:
        return ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, True, False, False, False, False),
            trees_profile=StartupProfile(False, False, False, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
        )

    def _actions(self, *, step: str, values: ManagedConfigValues | None = None) -> tuple[ConfigWizardBodyActions, list[str]]:
        calls: list[str] = []
        actions = ConfigWizardBodyActions(
            values=values or self._values(),
            config_file_path=Path("/repo/.envctl"),
            source_label="defaults",
            current_step=lambda: step,
            set_display=lambda widget_id, display: calls.append(f"display:{widget_id}:{display}"),
            update_widget=lambda widget_id, text: calls.append(f"update:{widget_id}:{text}"),
            render_choice_step=lambda *, selected, options: calls.append(f"choice:{selected}:{len(options)}"),
            render_components_step=lambda: calls.append("components"),
            render_service_startup_step=lambda: calls.append("service-startup"),
            sync_additional_service_inputs=lambda: calls.append("sync-additional-services"),
            sync_directory_inputs=lambda visible_fields: calls.append(f"sync-directory:{len(visible_fields)}"),
            sync_port_inputs=lambda visible_fields: calls.append(f"sync-port:{len(visible_fields)}"),
            update_review=lambda text: calls.append(f"review:{text.splitlines()[0]}"),
        )
        return actions, calls

    def test_welcome_step_updates_welcome_copy_and_displays_only_welcome(self) -> None:
        actions, calls = self._actions(step="welcome")

        actions.refresh_body()

        self.assertIn("display:config-welcome:True", calls)
        self.assertIn("display:config-list:False", calls)
        self.assertTrue(any(call.startswith("update:config-welcome:envctl is the CLI") for call in calls))

    def test_default_mode_step_renders_choice_list(self) -> None:
        actions, calls = self._actions(step="default_mode")

        actions.refresh_body()

        self.assertIn("display:config-list:True", calls)
        self.assertIn("choice:main:2", calls)

    def test_directories_step_syncs_visible_fields(self) -> None:
        actions, calls = self._actions(step="directories")

        actions.refresh_body()

        self.assertIn("display:config-directories:True", calls)
        self.assertIn("sync-directory:3", calls)
        self.assertNotIn("display:config-empty:True", calls)

    def test_empty_directories_step_shows_empty_message(self) -> None:
        values = self._values()
        values.main_profile.backend_enable = False
        values.main_profile.frontend_enable = False
        values.trees_profile.backend_enable = False
        values.trees_profile.frontend_enable = False
        actions, calls = self._actions(step="directories", values=values)

        actions.refresh_body()

        self.assertIn("sync-directory:0", calls)
        self.assertIn("display:config-empty:True", calls)
        self.assertTrue(any(call.startswith("update:config-empty:No directories need") for call in calls))

    def test_review_step_renders_review_text(self) -> None:
        actions, calls = self._actions(step="review")

        actions.refresh_body()

        self.assertIn("display:config-review-scroll:True", calls)
        self.assertTrue(any(call.startswith("review:Path: /repo/.envctl") for call in calls))


if __name__ == "__main__":
    unittest.main()
