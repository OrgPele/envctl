from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.config import PortDefaults, StartupProfile
from envctl_engine.config.persistence import ManagedConfigValues
from envctl_engine.ui.textual.screens.config_wizard_action_bundle import ConfigWizardActionBundle
from envctl_engine.ui.textual.screens.config_wizard_components import ConfigWizardComponentInteraction


class _ListView:
    def __init__(self, *, index: int | None = 0, count: int = 2, has_focus: bool = True) -> None:
        self.index = index
        self.children = [object() for _ in range(count)]
        self.has_focus = has_focus


@dataclass(slots=True)
class _StepState:
    index: int = 0
    suppress_selected_once: bool = False
    save_result: object | None = None


class ConfigWizardActionBundleTests(unittest.TestCase):
    def _values(self) -> ManagedConfigValues:
        return ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, True, False, False, False, False),
            trees_profile=StartupProfile(True, True, True, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
        )

    def _bundle(self, *, step: str = "welcome") -> tuple[ConfigWizardActionBundle, list[str], _StepState, _ListView]:
        values = self._values()
        calls: list[str] = []
        state = _StepState()
        list_view = _ListView()

        bundle = ConfigWizardActionBundle(
            app=object(),
            values=values,
            component_interaction=ConfigWizardComponentInteraction.from_values(values),
            service_startup_fields=(("startup_enable", "main", "Main"),),
            config_file_path=Path("/repo/.envctl"),
            source_label="defaults",
            steps=lambda: ["welcome", "review"],
            step_index=lambda: state.index,
            set_step_index=lambda value: setattr(state, "index", value),
            set_suppress_list_selected_once=lambda value: setattr(state, "suppress_selected_once", value),
            set_save_result=lambda value: setattr(state, "save_result", value),
            current_step=lambda: step,
            list_view=lambda: list_view,
            focused_widget=lambda: list_view,
            input_type=_ListView,
            suggestions_by_field={},
            field_name_from_input_id=lambda _widget_id: None,
            directory_label=lambda field_name: field_name,
            refresh_all=lambda: calls.append("refresh-all"),
            refresh_body=lambda: calls.append("refresh-body"),
            refresh_status=lambda message=None: calls.append(f"status:{message or ''}"),
            refresh_actions=lambda: calls.append("refresh-actions"),
            sync_steps=lambda current_step=None: calls.append(f"sync-steps:{current_step or ''}"),
            sync_startup_enable_flags=lambda: calls.append("sync-startup"),
            refresh_directory_validation=lambda field_name, raw=None: calls.append(f"validation:{field_name}:{raw}"),
            refresh_field_hint=lambda field_name, raw=None: calls.append(f"hint:{field_name}:{raw}"),
            emit=lambda event, **_payload: calls.append(f"emit:{event}"),
            set_display=lambda widget_id, display: calls.append(f"display:{widget_id}:{display}"),
            update_widget=lambda widget_id, text: calls.append(f"update:{widget_id}:{text.splitlines()[0]}"),
            render_choice_step=lambda *, selected, options: calls.append(f"choice:{selected}:{len(options)}"),
            render_components_step=lambda: calls.append("components"),
            render_service_startup_step=lambda: calls.append("service-startup"),
            sync_additional_service_inputs=lambda: calls.append("sync-additional-services"),
            sync_directory_inputs=lambda visible_fields: calls.append(f"sync-directory:{len(visible_fields)}"),
            sync_port_inputs=lambda visible_fields: calls.append(f"sync-port:{len(visible_fields)}"),
            update_review=lambda text: calls.append(f"review:{text.splitlines()[0]}"),
            focus_list=lambda view, index: calls.append(f"focus-list:{view.index}:{index}"),
            focus_widget=lambda widget_id: calls.append(f"focus-widget:{widget_id}"),
            apply_directory_inputs=lambda: True,
            apply_additional_service_inputs=lambda: True,
            apply_port_inputs=lambda: True,
            validate_values=lambda **_kwargs: SimpleNamespace(valid=True, errors=[]),
            save_config=lambda: SimpleNamespace(path=Path("/repo/.envctl")),
            exit_with_result=lambda result: calls.append(f"exit:{bool(result)}"),
            result_factory=lambda values, save_result: (values, save_result),
        )
        return bundle, calls, state, list_view

    def test_bundle_builds_body_focus_and_flow_actions_from_shared_dependencies(self) -> None:
        body_bundle, body_calls, _state, _list_view = self._bundle(step="welcome")
        focus_bundle, focus_calls, _state, _list_view = self._bundle(step="ports")
        flow_bundle, flow_calls, flow_state, _list_view = self._bundle(step="welcome")

        body_bundle.body().refresh_body()
        focus_bundle.focus().focus_current_step()
        flow_bundle.flow().advance()

        self.assertIn("display:config-welcome:True", body_calls)
        self.assertTrue(any(call.startswith("update:config-welcome:envctl is the CLI") for call in body_calls))
        self.assertEqual(focus_calls, ["focus-widget:port-backend_port_base"])
        self.assertEqual(flow_state.index, 1)
        self.assertEqual(flow_calls, ["refresh-all"])

    def test_bundle_builds_component_and_suggestion_actions_from_shared_dependencies(self) -> None:
        component_bundle, component_calls, _state, list_view = self._bundle(step="default_mode")
        suggestion_bundle, _suggestion_calls, _state, _list_view = self._bundle(step="welcome")

        component_bundle.component().cursor_down()

        self.assertEqual(list_view.index, 1)
        self.assertEqual(component_bundle.values.default_mode, "trees")
        self.assertIn("refresh-body", component_calls)
        self.assertFalse(suggestion_bundle.suggestions().cycle_command_suggestion_available())


if __name__ == "__main__":
    unittest.main()
