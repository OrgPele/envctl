from __future__ import annotations

from dataclasses import dataclass
import unittest

from envctl_engine.config import PortDefaults, StartupProfile
from envctl_engine.config.persistence import ManagedConfigValues
from envctl_engine.ui.textual.screens.config_wizard_layout import (
    CONFIG_WIZARD_APP_CSS,
    compose_config_wizard_layout,
)


@dataclass(slots=True)
class FakeWidget:
    label: object = ""
    id: str | None = None
    value: str = ""
    placeholder: str = ""
    classes: str = ""
    variant: str = ""


class FakeContainer(FakeWidget):
    def __enter__(self) -> FakeContainer:
        return self

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        return None


class ConfigWizardLayoutTests(unittest.TestCase):
    def test_layout_css_includes_wizard_shell_and_row_styles(self) -> None:
        self.assertIn("#config-shell", CONFIG_WIZARD_APP_CSS)
        self.assertIn(".config-row", CONFIG_WIZARD_APP_CSS)

    def test_compose_layout_builds_static_fields_and_actions(self) -> None:
        values = ManagedConfigValues(
            default_mode="main",
            main_profile=StartupProfile(True, True, True, False, False, False, False),
            trees_profile=StartupProfile(True, True, True, False, False, False, False),
            port_defaults=PortDefaults(8000, 9000, 5432, 6379, 5678, 20),
        )

        widgets = list(
            compose_config_wizard_layout(
                values=values,
                field_value=lambda field_name: f"value-for-{field_name}",
                horizontal_cls=FakeContainer,
                vertical_cls=FakeContainer,
                vertical_scroll_cls=FakeContainer,
                button_cls=FakeWidget,
                footer_cls=FakeWidget,
                input_cls=FakeWidget,
                label_cls=FakeWidget,
                list_view_cls=FakeWidget,
                static_cls=FakeWidget,
            )
        )

        widget_ids = {widget.id for widget in widgets}
        self.assertIn("config-title", widget_ids)
        self.assertIn("config-list", widget_ids)
        self.assertIn("config-review", widget_ids)
        self.assertIn("btn-cancel", widget_ids)
        self.assertIn("btn-next", widget_ids)
        self.assertTrue(
            any(
                widget.id == "directory-backend_dir_name" and widget.value == "value-for-backend_dir_name"
                for widget in widgets
            )
        )
        self.assertTrue(
            any(
                widget.id == "port-backend_port_base" and widget.value == "value-for-backend_port_base"
                for widget in widgets
            )
        )


if __name__ == "__main__":
    unittest.main()
