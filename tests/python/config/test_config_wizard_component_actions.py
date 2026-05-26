from __future__ import annotations

import unittest
from typing import Any

from envctl_engine.config import PortDefaults, StartupProfile
from envctl_engine.config.persistence import ManagedConfigValues
from envctl_engine.ui.textual.screens.config_wizard_component_actions import (
    ConfigWizardComponentActions,
)
from envctl_engine.ui.textual.screens.config_wizard_components import (
    ConfigWizardComponentInteraction,
)


class _ListView:
    def __init__(self, *, index: int | None = 0, count: int = 4, has_focus: bool = True) -> None:
        self.index = index
        self.children = [object() for _ in range(count)]
        self.has_focus = has_focus
        self.focus_calls: list[int | None] = []

    def focus(self) -> None:
        self.focus_calls.append(self.index)


class ConfigWizardComponentActionsTests(unittest.TestCase):
    def _values(self) -> ManagedConfigValues:
        return ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, False, True, False, False, False),
            trees_profile=StartupProfile(False, False, True, False, True, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            main_backend_expect_listener=True,
            trees_backend_expect_listener=False,
        )

    def _actions(
        self,
        *,
        values: ManagedConfigValues | None = None,
        current_step: str = "components",
        list_view: _ListView | None = None,
        focused_widget: Any | None = None,
    ) -> tuple[ConfigWizardComponentActions, list[str], _ListView]:
        values = values or self._values()
        list_view = list_view or _ListView(index=0, count=4)
        calls: list[str] = []

        actions = ConfigWizardComponentActions(
            app=object(),
            values=values,
            component_interaction=ConfigWizardComponentInteraction.from_values(values),
            service_startup_fields=(
                ("startup_enable", "main", "Main"),
                ("backend_expect_listener", "trees", "Trees backend listener"),
            ),
            current_step=lambda: current_step,
            list_view=lambda: list_view,
            focused_widget=lambda: focused_widget if focused_widget is not None else list_view,
            sync_steps=lambda current_step=None: calls.append(f"sync:{current_step}"),
            sync_startup_enable_flags=lambda: calls.append("sync-startup"),
            refresh_body=lambda: calls.append("body"),
            refresh_status=lambda message=None: calls.append(f"status:{message or ''}"),
            refresh_actions=lambda: calls.append("actions"),
        )
        return actions, calls, list_view

    def test_cursor_navigation_skips_component_headers_and_syncs_default_mode(self) -> None:
        values = self._values()
        list_view = _ListView(index=0, count=2)
        actions, calls, _ = self._actions(values=values, current_step="default_mode", list_view=list_view)

        actions.cursor_down()

        self.assertEqual(list_view.index, 1)
        self.assertEqual(values.default_mode, "trees")
        self.assertIn("body", calls)
        self.assertIn("status:", calls)

    def test_component_toggle_syncs_flags_refreshes_and_preserves_target_index(self) -> None:
        values = self._values()
        actions, calls, list_view = self._actions(values=values, current_step="components")
        backend_index = next(
            index
            for index, row in enumerate(actions.component_interaction.rows())
            if row.component_id == "backend_enable" and row.shared
        )
        list_view.index = backend_index

        actions.toggle_item()

        self.assertFalse(values.main_profile.backend_enable)
        self.assertFalse(values.trees_profile.backend_enable)
        self.assertEqual(list_view.index, backend_index)
        self.assertEqual(calls[:5], ["sync-startup", "sync:components", "body", "status:", "actions"])

    def test_service_startup_toggle_resyncs_step_and_refocuses_list(self) -> None:
        values = self._values()
        list_view = _ListView(index=1, count=2)
        actions, calls, _ = self._actions(values=values, current_step="service_startup", list_view=list_view)

        actions.toggle_item()

        self.assertTrue(values.trees_backend_expect_listener)
        self.assertEqual(list_view.index, 1)
        self.assertEqual(calls[:4], ["sync:service_startup", "body", "status:", "actions"])

    def test_component_split_requires_component_step_focused_selectable_row(self) -> None:
        values = self._values()
        actions, _calls, list_view = self._actions(values=values, current_step="components")
        backend_index = next(
            index
            for index, row in enumerate(actions.component_interaction.rows())
            if row.component_id == "backend_enable" and row.shared
        )
        list_view.index = backend_index

        self.assertTrue(actions.component_split_available())
        actions.toggle_component_split()

        self.assertIn("backend_enable", actions.component_interaction.split_component_fields)
        self.assertEqual(actions.component_interaction.rows()[list_view.index].mode, "main")


if __name__ == "__main__":
    unittest.main()
