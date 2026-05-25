from __future__ import annotations

import unittest

from envctl_engine.ui.textual.screens.config_wizard_status import (
    command_step_status,
    component_step_status,
    directory_step_status,
    port_step_status,
    status_for_valid_config_step,
)


class ConfigWizardStatusPolicyTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
