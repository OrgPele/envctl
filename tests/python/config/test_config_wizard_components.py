from __future__ import annotations

import unittest

from envctl_engine.config import PortDefaults, StartupProfile
from envctl_engine.config.persistence import ManagedConfigValues
from envctl_engine.ui.textual.screens.config_wizard_components import (
    ComponentRow,
    ConfigWizardComponentInteraction,
    component_row_enabled,
    component_rows,
    component_value,
    component_values_differ,
    default_component_index,
    nearest_selectable_component_index,
    service_startup_value,
    set_component_value,
    sync_startup_enable_flags,
    toggle_service_startup_value,
)


class ConfigWizardComponentPolicyTests(unittest.TestCase):
    def _values(self) -> ManagedConfigValues:
        return ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, False, True, False, False, False),
            trees_profile=StartupProfile(False, False, True, False, True, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            main_backend_expect_listener=True,
            trees_backend_expect_listener=False,
        )

    def test_component_rows_include_headers_and_split_rows(self) -> None:
        rows = component_rows({"backend_enable", "postgres"})

        self.assertEqual(rows[0], ComponentRow(label="Services", kind="header"))
        self.assertIn(ComponentRow(component_id="backend_enable", label="Main - Backend", mode="main"), rows)
        self.assertIn(ComponentRow(component_id="backend_enable", label="Trees - Backend", mode="trees"), rows)
        self.assertIn(ComponentRow(label="Dependencies", kind="header"), rows)
        self.assertIn(ComponentRow(component_id="postgres", label="Main - Postgres", mode="main"), rows)
        self.assertIn(ComponentRow(component_id="postgres", label="Trees - Postgres", mode="trees"), rows)

    def test_component_value_and_row_enabled_follow_mode(self) -> None:
        values = self._values()

        self.assertTrue(component_value(values, "main", "backend_enable"))
        self.assertFalse(component_value(values, "trees", "backend_enable"))
        self.assertTrue(component_value(values, "main", "postgres"))
        self.assertFalse(component_row_enabled(values, ComponentRow(label="Services", kind="header")))
        self.assertTrue(component_row_enabled(values, ComponentRow(component_id="backend_enable", label="Backend")))
        self.assertTrue(
            component_row_enabled(values, ComponentRow(component_id="frontend_enable", label="Trees - Frontend", mode="trees"))
        )

    def test_set_component_value_updates_services_and_dependencies(self) -> None:
        values = self._values()

        set_component_value(values, "trees", "backend_enable", True)
        set_component_value(values, "main", "redis", True)

        self.assertTrue(values.trees_profile.backend_enable)
        self.assertTrue(values.main_profile.dependency_enabled("redis"))
        self.assertTrue(component_values_differ(values, "frontend_enable"))

    def test_startup_policy_toggles_and_syncs_values(self) -> None:
        values = self._values()

        self.assertTrue(service_startup_value(values, "startup_enable", "main"))
        self.assertFalse(service_startup_value(values, "backend_expect_listener", "trees"))
        toggle_service_startup_value(values, "backend_expect_listener", "trees")
        toggle_service_startup_value(values, "startup_enable", "main")

        self.assertTrue(values.trees_backend_expect_listener)
        self.assertFalse(values.main_profile.startup_enable)

        values.main_profile.backend_enable = False
        values.main_profile.frontend_enable = False
        values.main_profile.dependencies.clear()
        values.main_profile.startup_enable = True
        sync_startup_enable_flags(values, include_service_startup=False)

        self.assertFalse(values.main_profile.startup_enable)
        self.assertTrue(values.trees_profile.startup_enable)

    def test_component_index_helpers_skip_headers(self) -> None:
        rows = [
            ComponentRow(label="Services", kind="header"),
            ComponentRow(component_id="backend_enable", label="Backend"),
            ComponentRow(label="Dependencies", kind="header"),
            ComponentRow(component_id="postgres", label="Postgres"),
        ]

        self.assertEqual(default_component_index(rows, [True, False, False, False]), 1)
        self.assertEqual(default_component_index(rows, [False, False, False, True]), 3)
        self.assertEqual(nearest_selectable_component_index(rows, 0, step=1), 1)
        self.assertEqual(nearest_selectable_component_index(rows, 2, step=-1), 1)

    def test_component_interaction_toggles_shared_row_for_main_and_trees(self) -> None:
        values = self._values()
        interaction = ConfigWizardComponentInteraction(values, split_component_fields=set())
        backend_index = next(
            index for index, row in enumerate(interaction.rows()) if row.component_id == "backend_enable" and row.shared
        )

        result = interaction.toggle_component_at(backend_index)

        self.assertTrue(result.changed)
        self.assertEqual(result.target_index, backend_index)
        self.assertFalse(values.main_profile.backend_enable)
        self.assertFalse(values.trees_profile.backend_enable)

    def test_component_interaction_toggles_split_mode_row_only(self) -> None:
        values = self._values()
        interaction = ConfigWizardComponentInteraction(values, split_component_fields={"backend_enable"})
        trees_backend_index = next(
            index
            for index, row in enumerate(interaction.rows())
            if row.component_id == "backend_enable" and row.mode == "trees"
        )

        result = interaction.toggle_component_at(trees_backend_index)

        self.assertTrue(result.changed)
        self.assertTrue(values.main_profile.backend_enable)
        self.assertTrue(values.trees_profile.backend_enable)

    def test_component_interaction_prevents_merging_when_values_differ(self) -> None:
        values = self._values()
        interaction = ConfigWizardComponentInteraction(values, split_component_fields={"backend_enable"})
        main_backend_index = next(
            index
            for index, row in enumerate(interaction.rows())
            if row.component_id == "backend_enable" and row.mode == "main"
        )

        result = interaction.toggle_split_at(main_backend_index)

        self.assertFalse(result.changed)
        self.assertIn("differ", result.error_message or "")
        self.assertIn("backend_enable", interaction.split_component_fields)

    def test_component_interaction_merges_matching_split_rows_to_shared_target(self) -> None:
        values = self._values()
        values.trees_profile.backend_enable = True
        interaction = ConfigWizardComponentInteraction(values, split_component_fields={"backend_enable"})
        main_backend_index = next(
            index
            for index, row in enumerate(interaction.rows())
            if row.component_id == "backend_enable" and row.mode == "main"
        )

        result = interaction.toggle_split_at(main_backend_index)

        self.assertTrue(result.changed)
        self.assertNotIn("backend_enable", interaction.split_component_fields)
        self.assertTrue(interaction.rows()[result.target_index].shared)

    def test_component_interaction_splits_shared_row_to_preferred_mode_target(self) -> None:
        values = self._values()
        interaction = ConfigWizardComponentInteraction(values, split_component_fields=set())
        backend_index = next(
            index for index, row in enumerate(interaction.rows()) if row.component_id == "backend_enable" and row.shared
        )

        result = interaction.toggle_split_at(backend_index)

        self.assertTrue(result.changed)
        self.assertIn("backend_enable", interaction.split_component_fields)
        self.assertEqual(interaction.rows()[result.target_index].mode, "main")
