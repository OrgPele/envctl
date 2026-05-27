from __future__ import annotations

import unittest

from envctl_engine.config import PortDefaults, StartupProfile
from envctl_engine.config.persistence import ManagedConfigValues
from envctl_engine.ui.textual.screens.config_wizard_status import (
    command_step_status,
    component_step_status,
    directory_step_status,
    resolve_config_wizard_action_state,
    resolve_config_wizard_status,
    port_step_status,
    status_for_valid_config_step,
)


class ConfigWizardStatusPolicyTests(unittest.TestCase):
    def _values(self) -> ManagedConfigValues:
        return ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(False, False, False, False, False, False, False),
            trees_profile=StartupProfile(False, False, False, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
        )

    def test_component_status_reflects_split_availability(self) -> None:
        self.assertIn("or split a row", component_step_status(component_split_available=True))
        self.assertNotIn("or split a row", component_step_status(component_split_available=False))

    def test_valid_config_step_statuses_are_step_specific(self) -> None:
        self.assertEqual(
            status_for_valid_config_step("additional_services", component_split_available=False),
            "Edit the first additional app service. Leave the slug blank to keep no services configured.",
        )
        self.assertEqual(status_for_valid_config_step("review", component_split_available=False), "Configuration is valid.")
        self.assertIn("auto-start", status_for_valid_config_step("service_startup", component_split_available=False))

    def test_directory_and_command_statuses_prefer_validation_errors(self) -> None:
        visible_fields = (("backend_dir", "Backend"),)

        self.assertEqual(
            directory_step_status(visible_fields=visible_fields, first_error="Backend directory is missing."),
            "Backend directory is missing.",
        )
        self.assertIn(
            "Only directories",
            directory_step_status(visible_fields=visible_fields, first_error=None),
        )
        self.assertIn(
            "No directories",
            directory_step_status(visible_fields=(), first_error=None),
        )

        self.assertEqual(
            command_step_status(visible_fields=visible_fields, first_error="Backend command is invalid."),
            "Backend command is invalid.",
        )
        self.assertIn("detected suggestions", command_step_status(visible_fields=visible_fields, first_error=None))
        self.assertIn("No entrypoints", command_step_status(visible_fields=(), first_error=None))

    def test_port_status_reflects_visible_fields(self) -> None:
        self.assertIn("canonical ports", port_step_status(visible_fields=(("backend_port", "Backend"),)))
        self.assertIn("No ports", port_step_status(visible_fields=()))

    def test_resolve_status_applies_validation_and_field_visibility_policy(self) -> None:
        values = self._values()

        self.assertIn(
            "components",
            resolve_config_wizard_status(
                "components",
                values,
                component_split_available=False,
                first_directory_error=lambda _visible_fields: None,
            ),
        )

        self.assertIn(
            "No directories",
            resolve_config_wizard_status(
                "directories",
                values,
                component_split_available=False,
                first_directory_error=lambda _visible_fields: None,
            ),
        )

        values.main_profile.backend_enable = True
        values.backend_dir_name = "backend"
        self.assertEqual(
            resolve_config_wizard_status(
                "directories",
                values,
                component_split_available=False,
                first_directory_error=lambda visible_fields: f"{visible_fields[0][1]} missing.",
            ),
            "Backend directory missing.",
        )

    def test_resolve_action_state_disables_back_and_labels_final_step_save(self) -> None:
        self.assertEqual(resolve_config_wizard_action_state(step_index=0, step_count=3), (True, "Next"))
        self.assertEqual(resolve_config_wizard_action_state(step_index=1, step_count=3), (False, "Next"))
        self.assertEqual(resolve_config_wizard_action_state(step_index=2, step_count=3), (False, "Save"))


if __name__ == "__main__":
    unittest.main()
