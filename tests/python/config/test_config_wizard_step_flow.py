from __future__ import annotations

import unittest

from envctl_engine.config.persistence_values import managed_values_from_mapping
from envctl_engine.ui.textual.screens.config_wizard_step_flow import (
    should_show_service_startup_step,
    sync_wizard_steps,
)


class ConfigWizardStepFlowTests(unittest.TestCase):
    def test_service_startup_step_only_appears_for_backend_only_configuration(self) -> None:
        backend_only = managed_values_from_mapping(
            {
                "BACKEND_ENABLE": "true",
                "FRONTEND_ENABLE": "false",
                "MAIN_BACKEND_ENABLE": "true",
                "MAIN_FRONTEND_ENABLE": "false",
                "TREES_BACKEND_ENABLE": "false",
                "TREES_FRONTEND_ENABLE": "false",
            }
        )
        full_stack = managed_values_from_mapping(
            {
                "BACKEND_ENABLE": "true",
                "FRONTEND_ENABLE": "true",
                "MAIN_BACKEND_ENABLE": "true",
                "MAIN_FRONTEND_ENABLE": "true",
                "TREES_BACKEND_ENABLE": "false",
                "TREES_FRONTEND_ENABLE": "false",
            }
        )

        self.assertTrue(should_show_service_startup_step(backend_only))
        self.assertFalse(should_show_service_startup_step(full_stack))

    def test_sync_steps_preserves_current_step_when_available(self) -> None:
        values = managed_values_from_mapping({"BACKEND_ENABLE": "true", "FRONTEND_ENABLE": "false"})

        state = sync_wizard_steps(
            values,
            current_steps=["welcome", "components", "directories"],
            step_index=1,
            current_step="components",
            include_additional_services=False,
        )

        self.assertIn("components", state.steps)
        self.assertEqual(state.current_step, "components")

    def test_sync_steps_falls_back_from_removed_service_startup_step(self) -> None:
        values = managed_values_from_mapping({"BACKEND_ENABLE": "true", "FRONTEND_ENABLE": "true"})

        state = sync_wizard_steps(
            values,
            current_steps=["welcome", "components", "service_startup"],
            step_index=2,
            current_step="service_startup",
            include_additional_services=False,
        )

        self.assertNotIn("service_startup", state.steps)
        self.assertEqual(state.current_step, "directories")


if __name__ == "__main__":
    unittest.main()
