from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.config import PortDefaults, StartupProfile
from envctl_engine.config.persistence import ManagedConfigValues
from envctl_engine.ui.textual.screens.config_wizard_flow_actions import ConfigWizardFlowActions


@dataclass(slots=True)
class _StepState:
    step_index: int
    suppress_selected_once: bool = False
    save_result: object | None = None


class ConfigWizardFlowActionsTests(unittest.TestCase):
    def _values(self) -> ManagedConfigValues:
        return ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, True, False, False, False, False),
            trees_profile=StartupProfile(True, True, True, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
        )

    def _actions(
        self,
        *,
        steps: list[str],
        step_index: int,
        list_has_focus: bool = False,
        apply_directory_inputs=lambda: True,
        apply_additional_service_inputs=lambda: True,
        apply_port_inputs=lambda: True,
        validate=lambda **_kwargs: SimpleNamespace(valid=True, errors=[]),
        save_config=lambda: SimpleNamespace(path=Path(".envctl")),
    ) -> tuple[ConfigWizardFlowActions, _StepState, list[str], list[object]]:
        state = _StepState(step_index=step_index)
        calls: list[str] = []
        exits: list[object] = []
        actions = ConfigWizardFlowActions(
            values=self._values(),
            steps=lambda: steps,
            step_index=lambda: state.step_index,
            set_step_index=lambda value: setattr(state, "step_index", value),
            set_suppress_list_selected_once=lambda value: setattr(state, "suppress_selected_once", value),
            set_save_result=lambda value: setattr(state, "save_result", value),
            current_step=lambda: steps[state.step_index],
            list_has_focus=lambda: list_has_focus,
            refresh_all=lambda: calls.append("refresh-all"),
            refresh_status=lambda message=None: calls.append(f"status:{message or ''}"),
            apply_directory_inputs=apply_directory_inputs,
            apply_additional_service_inputs=apply_additional_service_inputs,
            apply_port_inputs=apply_port_inputs,
            validate_values=validate,
            save_config=save_config,
            exit_with_result=lambda result: exits.append(result),
            result_factory=lambda values, save_result: (values, save_result),
        )
        return actions, state, calls, exits

    def test_go_back_moves_to_previous_step_and_refreshes(self) -> None:
        actions, state, calls, _exits = self._actions(steps=["welcome", "components"], step_index=1)

        actions.go_back()

        self.assertEqual(state.step_index, 0)
        self.assertEqual(calls, ["refresh-all"])

    def test_submit_or_next_suppresses_list_selected_when_choice_list_has_focus(self) -> None:
        actions, state, calls, _exits = self._actions(
            steps=["default_mode", "components"],
            step_index=0,
            list_has_focus=True,
        )

        actions.submit_or_next()

        self.assertTrue(state.suppress_selected_once)
        self.assertEqual(state.step_index, 1)
        self.assertEqual(calls, ["refresh-all"])

    def test_advance_stops_when_directory_input_application_fails(self) -> None:
        actions, state, calls, _exits = self._actions(
            steps=["directories", "review"],
            step_index=0,
            apply_directory_inputs=lambda: False,
        )

        actions.advance()

        self.assertEqual(state.step_index, 0)
        self.assertEqual(calls, [])

    def test_advance_reports_validation_error_before_moving_forward(self) -> None:
        actions, state, calls, _exits = self._actions(
            steps=["commands", "review"],
            step_index=0,
            validate=lambda **_kwargs: SimpleNamespace(valid=False, errors=["Backend entrypoint must not be empty."]),
        )

        actions.advance()

        self.assertEqual(state.step_index, 0)
        self.assertEqual(calls, ["status:Backend entrypoint must not be empty."])

    def test_advance_saves_and_exits_on_final_step(self) -> None:
        save_result = SimpleNamespace(path=Path(".envctl"))
        actions, state, calls, exits = self._actions(
            steps=["review"],
            step_index=0,
            save_config=lambda: save_result,
        )

        actions.advance()

        self.assertIs(state.save_result, save_result)
        self.assertEqual(calls, [])
        self.assertEqual(exits, [(actions.values, save_result)])


if __name__ == "__main__":
    unittest.main()
