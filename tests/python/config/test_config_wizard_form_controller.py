from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tempfile
import unittest

from envctl_engine.config import AppServiceConfig, PortDefaults, StartupProfile
from envctl_engine.config.persistence import ManagedConfigValues
from envctl_engine.ui.textual.screens.config_wizard_fields import (
    _additional_service_input_id,
    _directory_error_id,
    _directory_hint_id,
    _directory_input_id,
    _field_label_id,
    _port_input_id,
)
from envctl_engine.ui.textual.screens.config_wizard_form import ConfigWizardFormController
from envctl_engine.ui.textual.screens.config_wizard_hints import ConfigWizardHintResolver


@dataclass(slots=True)
class FakeWidget:
    value: str = ""
    display: bool = True
    focused: bool = False
    classes: set[str] = field(default_factory=set)
    text: str = ""

    def update(self, value: str) -> None:
        self.text = value

    def add_class(self, name: str) -> None:
        self.classes.add(name)

    def remove_class(self, name: str) -> None:
        self.classes.discard(name)

    def focus(self) -> None:
        self.focused = True


class FakeApp:
    def __init__(self, widgets: dict[str, FakeWidget]) -> None:
        self.widgets = widgets

    def query_one(self, selector: str, _widget_type: object = None) -> FakeWidget:
        return self.widgets.setdefault(selector.removeprefix("#"), FakeWidget())


class ConfigWizardFormControllerTests(unittest.TestCase):
    def _values(self) -> ManagedConfigValues:
        return ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, True, True, True, False, False),
            trees_profile=StartupProfile(False, False, False, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
            backend_dir_name="backend",
            frontend_dir_name="frontend",
            backend_start_cmd="python app.py",
            frontend_start_cmd="npm run dev",
            backend_test_cmd="pytest",
            frontend_test_cmd="npm test",
        )

    def test_directory_sync_updates_visible_widgets_and_hides_inactive_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            (base_dir / "backend").mkdir()
            values = self._values()
            widgets = {
                _field_label_id("directory", "backend_dir_name"): FakeWidget(),
                _directory_input_id("backend_dir_name"): FakeWidget(),
                _directory_hint_id("backend_dir_name"): FakeWidget(),
                _directory_error_id("backend_dir_name"): FakeWidget(),
                _field_label_id("directory", "frontend_dir_name"): FakeWidget(),
                _directory_input_id("frontend_dir_name"): FakeWidget(classes={"directory-invalid"}),
                _directory_hint_id("frontend_dir_name"): FakeWidget(text="stale"),
                _directory_error_id("frontend_dir_name"): FakeWidget(
                    text="stale",
                    classes={"directory-error-visible"},
                ),
            }
            controller = ConfigWizardFormController(
                app=FakeApp(widgets),
                values=values,
                base_dir=base_dir,
                hints=ConfigWizardHintResolver(
                    base_dir=base_dir,
                    parsed_values={},
                    suggestions_by_field={},
                    field_value=lambda field: getattr(values, field),
                ),
                input_cls=FakeWidget,
                label_cls=FakeWidget,
                static_cls=FakeWidget,
                refresh_status=lambda _message=None: None,
                current_step=lambda: "directories",
            )

            controller.sync_directory_inputs((("backend_dir_name", "Backend directory"),))

            self.assertEqual(widgets[_directory_input_id("backend_dir_name")].value, "backend")
            self.assertTrue(widgets[_directory_input_id("backend_dir_name")].display)
            self.assertFalse(widgets[_directory_input_id("frontend_dir_name")].display)
            self.assertNotIn("directory-invalid", widgets[_directory_input_id("frontend_dir_name")].classes)
            self.assertEqual(widgets[_directory_hint_id("frontend_dir_name")].text, "")
            self.assertEqual(widgets[_directory_error_id("frontend_dir_name")].text, "")
            self.assertNotIn("directory-error-visible", widgets[_directory_error_id("frontend_dir_name")].classes)

    def test_apply_directory_inputs_validates_before_mutating_and_focuses_invalid_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            (base_dir / "api").mkdir()
            values = self._values()
            messages: list[str] = []
            widgets = {
                _directory_input_id("backend_dir_name"): FakeWidget(value="api"),
                _directory_hint_id("backend_dir_name"): FakeWidget(),
                _directory_error_id("backend_dir_name"): FakeWidget(),
                _directory_input_id("frontend_dir_name"): FakeWidget(value="web"),
                _directory_hint_id("frontend_dir_name"): FakeWidget(),
                _directory_error_id("frontend_dir_name"): FakeWidget(),
            }
            controller = ConfigWizardFormController(
                app=FakeApp(widgets),
                values=values,
                base_dir=base_dir,
                hints=ConfigWizardHintResolver(
                    base_dir=base_dir,
                    parsed_values={},
                    suggestions_by_field={},
                    field_value=lambda field: getattr(values, field),
                ),
                input_cls=FakeWidget,
                label_cls=FakeWidget,
                static_cls=FakeWidget,
                refresh_status=lambda message=None: messages.append(str(message or "")),
                current_step=lambda: "directories",
            )

            self.assertFalse(
                controller.apply_directory_inputs(
                    (("backend_dir_name", "Backend directory"), ("frontend_dir_name", "Frontend directory"))
                )
            )

            self.assertEqual(values.backend_dir_name, "backend")
            self.assertEqual(messages[-1], "Directory does not exist: web")
            self.assertTrue(widgets[_directory_input_id("frontend_dir_name")].focused)

    def test_apply_additional_service_inputs_preserves_hidden_service_fields(self) -> None:
        existing = AppServiceConfig(
            name="voice-runtime",
            env_suffix="VOICE_RUNTIME",
            enabled_main=True,
            enabled_trees=True,
            dir_name="voice-runtime",
            start_cmd="old {port}",
            startup_group="workers",
            enable_if_path="voice-runtime/app.py",
        )
        values = self._values()
        values.additional_services = (existing,)
        widgets = {
            _additional_service_input_id("slug"): FakeWidget(value="voice-runtime"),
            _additional_service_input_id("dir_name"): FakeWidget(value="voice-runtime"),
            _additional_service_input_id("start_cmd"): FakeWidget(value="new {port}"),
            _additional_service_input_id("port_base"): FakeWidget(value="8010"),
            _additional_service_input_id("listener_expected"): FakeWidget(value="true"),
            _additional_service_input_id("enabled_main"): FakeWidget(value="true"),
            _additional_service_input_id("enabled_trees"): FakeWidget(value="false"),
            _additional_service_input_id("test_cmd"): FakeWidget(value="pytest voice"),
            _additional_service_input_id("public_url"): FakeWidget(value=""),
            _additional_service_input_id("health_url"): FakeWidget(value=""),
            _additional_service_input_id("depends_on"): FakeWidget(value="backend"),
            _additional_service_input_id("start_order"): FakeWidget(value="50"),
            _additional_service_input_id("critical"): FakeWidget(value="false"),
        }
        controller = ConfigWizardFormController(
            app=FakeApp(widgets),
            values=values,
            base_dir=Path.cwd(),
            hints=ConfigWizardHintResolver(
                base_dir=Path.cwd(),
                parsed_values={},
                suggestions_by_field={},
                field_value=lambda field: getattr(values, field),
            ),
            input_cls=FakeWidget,
            label_cls=FakeWidget,
            static_cls=FakeWidget,
            refresh_status=lambda _message=None: None,
            current_step=lambda: "additional_services",
        )

        self.assertTrue(controller.apply_additional_service_inputs())

        service = values.additional_services[0]
        self.assertEqual(service.start_cmd, "new {port}")
        self.assertEqual(service.startup_group, "workers")
        self.assertEqual(service.enable_if_path, "voice-runtime/app.py")

    def test_apply_port_inputs_validates_before_mutating_and_focuses_invalid_field(self) -> None:
        values = self._values()
        messages: list[str] = []
        widgets = {
            _port_input_id("backend_port_base"): FakeWidget(value="8100"),
            _port_input_id("frontend_port_base"): FakeWidget(value="0"),
        }
        controller = ConfigWizardFormController(
            app=FakeApp(widgets),
            values=values,
            base_dir=Path.cwd(),
            hints=ConfigWizardHintResolver(
                base_dir=Path.cwd(),
                parsed_values={},
                suggestions_by_field={},
                field_value=lambda field: getattr(values, field),
            ),
            input_cls=FakeWidget,
            label_cls=FakeWidget,
            static_cls=FakeWidget,
            refresh_status=lambda message=None: messages.append(str(message or "")),
            current_step=lambda: "ports",
        )

        self.assertFalse(
            controller.apply_port_inputs(
                (("backend_port_base", "Backend base port"), ("frontend_port_base", "Frontend base port"))
            )
        )

        self.assertEqual(values.port_defaults.backend_port_base, 8000)
        self.assertEqual(messages[-1], "Frontend base port must be a positive integer.")
        self.assertTrue(widgets[_port_input_id("frontend_port_base")].focused)


if __name__ == "__main__":
    unittest.main()
