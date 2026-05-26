from __future__ import annotations

import unittest
from dataclasses import dataclass

from envctl_engine.config.models import AppServiceConfig
from envctl_engine.ui.textual.screens.config_wizard_components import ComponentRow
from envctl_engine.ui.textual.screens.config_wizard_list_rendering import (
    render_additional_services_list,
    render_choice_list,
    render_components_list,
)


@dataclass
class FakeLabel:
    text: str
    markup: bool = False


class FakeListItem:
    def __init__(self, label: FakeLabel, *, classes: str = "") -> None:
        self.label = label
        self.classes = classes


class FakeListView:
    def __init__(self) -> None:
        self.children: list[FakeListItem] = []
        self.index: int | None = None

    def clear(self) -> None:
        self.children.clear()

    def extend(self, items: list[FakeListItem]) -> None:
        self.children.extend(items)


class ConfigWizardListRenderingTests(unittest.TestCase):
    def test_choice_list_marks_selected_option_and_index(self) -> None:
        list_view = FakeListView()

        render_choice_list(
            list_view,
            selected="trees",
            options=(("main", "Main"), ("trees", "Trees")),
            label_cls=FakeLabel,
            list_item_cls=FakeListItem,
        )

        self.assertEqual([item.label.text for item in list_view.children], ["○ Main", "● Trees"])
        self.assertEqual(list_view.index, 1)

    def test_component_list_preserves_headers_and_default_index(self) -> None:
        list_view = FakeListView()
        rows = [
            ComponentRow(label="Core", kind="header"),
            ComponentRow(label="Backend", component_id="backend"),
            ComponentRow(label="Frontend", component_id="frontend"),
        ]

        render_components_list(
            list_view,
            rows=rows,
            selected_flags=[False, True, False],
            default_index=1,
            label_cls=FakeLabel,
            list_item_cls=FakeListItem,
        )

        self.assertEqual([item.label.text for item in list_view.children], ["Core", "● Backend (Main + Trees)", "○ Frontend (Main + Trees)"])
        self.assertEqual(list_view.children[0].classes, "config-section-header")
        self.assertEqual(list_view.index, 1)

    def test_additional_services_list_renders_service_summary(self) -> None:
        list_view = FakeListView()
        service = AppServiceConfig(
            name="worker",
            env_suffix="WORKER",
            dir_name="worker",
            start_cmd="npm run dev",
            port_base=None,
            enabled_main=True,
            enabled_trees=False,
            depends_on=("backend",),
            critical=False,
        )

        render_additional_services_list(
            list_view,
            services=(service,),
            label_cls=FakeLabel,
            list_item_cls=FakeListItem,
        )

        self.assertEqual(
            list_view.children[0].label.text,
            "worker | dir=worker | mode=main | port=non-listener | deps=backend | non-critical",
        )


if __name__ == "__main__":
    unittest.main()
