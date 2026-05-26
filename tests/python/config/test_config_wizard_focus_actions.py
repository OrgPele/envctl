from __future__ import annotations

import unittest

from envctl_engine.config import PortDefaults, StartupProfile
from envctl_engine.config.persistence import ManagedConfigValues
from envctl_engine.ui.textual.screens.config_wizard_focus_actions import (
    ConfigWizardFocusActions,
)


class _ListView:
    def __init__(self, *, index: int | None = 0) -> None:
        self.index = index


class ConfigWizardFocusActionsTests(unittest.TestCase):
    def _values(self) -> ManagedConfigValues:
        return ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, True, False, False, False, False),
            trees_profile=StartupProfile(True, True, True, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
        )

    def _actions(self, *, step: str, list_view: _ListView | None = None) -> tuple[ConfigWizardFocusActions, list[str]]:
        calls: list[str] = []
        list_view = list_view or _ListView(index=0)
        actions = ConfigWizardFocusActions(
            values=self._values(),
            current_step=lambda: step,
            list_view=lambda: list_view,
            nearest_selectable_component_index=lambda index, *, step: index + step,
            focus_list=lambda view, index: calls.append(f"list:{view.index}:{index}"),
            focus_widget=lambda widget_id: calls.append(f"widget:{widget_id}"),
        )
        return actions, calls

    def test_components_step_moves_to_nearest_selectable_component_and_focuses_list(self) -> None:
        list_view = _ListView(index=2)
        actions, calls = self._actions(step="components", list_view=list_view)

        actions.focus_current_step()

        self.assertEqual(list_view.index, 3)
        self.assertEqual(calls, ["list:3:3"])

    def test_directories_step_focuses_first_visible_directory_input(self) -> None:
        actions, calls = self._actions(step="directories")

        actions.focus_current_step()

        self.assertEqual(calls, ["widget:directory-backend_dir_name"])

    def test_commands_step_focuses_first_visible_command_input(self) -> None:
        actions, calls = self._actions(step="commands")

        actions.focus_current_step()

        self.assertEqual(calls, ["widget:directory-backend_start_cmd"])

    def test_ports_step_focuses_first_visible_port_input(self) -> None:
        actions, calls = self._actions(step="ports")

        actions.focus_current_step()

        self.assertEqual(calls, ["widget:port-backend_port_base"])

    def test_additional_services_and_review_use_dedicated_focus_targets(self) -> None:
        additional_actions, additional_calls = self._actions(step="additional_services")
        review_actions, review_calls = self._actions(step="review")

        additional_actions.focus_current_step()
        review_actions.focus_current_step()

        self.assertEqual(additional_calls, ["widget:additional-service-slug"])
        self.assertEqual(review_calls, ["widget:config-review-scroll"])

    def test_unknown_or_empty_field_steps_focus_next_button(self) -> None:
        values = self._values()
        values.main_profile.backend_enable = False
        values.main_profile.frontend_enable = False
        values.trees_profile.backend_enable = False
        values.trees_profile.frontend_enable = False
        calls: list[str] = []
        actions = ConfigWizardFocusActions(
            values=values,
            current_step=lambda: "directories",
            list_view=lambda: _ListView(),
            nearest_selectable_component_index=lambda index, *, step: index,
            focus_list=lambda _view, _index: None,
            focus_widget=lambda widget_id: calls.append(f"widget:{widget_id}"),
        )

        actions.focus_current_step()

        self.assertEqual(calls, ["widget:btn-next"])


if __name__ == "__main__":
    unittest.main()
