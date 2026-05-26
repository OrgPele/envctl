from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from envctl_engine.config.models import AppServiceConfig
from envctl_engine.ui.textual.list_row_styles import (
    apply_selectable_list_index,
    selectable_list_default_index,
    selectable_list_row_classes,
)

from .config_wizard_components import ComponentRow


def render_additional_services_list(
    list_view: Any,
    *,
    services: Sequence[AppServiceConfig],
    label_cls: type,
    list_item_cls: type,
) -> None:
    list_view.clear()
    items: list[Any] = []
    selected_flags: list[bool] = []
    for service in services:
        modes = []
        if service.enabled_main:
            modes.append("main")
        if service.enabled_trees:
            modes.append("trees")
        mode_text = "+".join(modes) if modes else "disabled"
        port_text = str(service.port_base) if service.port_base is not None else "non-listener"
        critical_text = "critical" if service.critical else "non-critical"
        deps = ",".join(service.depends_on) if service.depends_on else "none"
        label = (
            f"{service.name} | dir={service.dir_name} | mode={mode_text} | "
            f"port={port_text} | deps={deps} | {critical_text}"
        )
        items.append(
            list_item_cls(
                label_cls(label, markup=False),
                classes=selectable_list_row_classes("config-row", selected=False),
            )
        )
        selected_flags.append(False)
    if not items:
        items.append(list_item_cls(label_cls("No additional app services configured.", markup=False)))
        selected_flags.append(False)
    list_view.extend(items)
    apply_selectable_list_index(list_view, selectable_list_default_index(selected_flags))


def render_choice_list(
    list_view: Any,
    *,
    selected: str,
    options: tuple[tuple[str, str], ...],
    label_cls: type,
    list_item_cls: type,
) -> None:
    list_view.clear()
    items: list[Any] = []
    selected_flags: list[bool] = []
    for value, label in options:
        is_selected = selected == value
        selected_flags.append(is_selected)
        marker = "●" if is_selected else "○"
        items.append(
            list_item_cls(
                label_cls(f"{marker} {label}", markup=False),
                classes=selectable_list_row_classes("config-row", selected=is_selected),
            )
        )
    list_view.extend(items)
    apply_selectable_list_index(list_view, selectable_list_default_index(selected_flags))


def render_components_list(
    list_view: Any,
    *,
    rows: Sequence[ComponentRow],
    selected_flags: Sequence[bool],
    default_index: int,
    label_cls: type,
    list_item_cls: type,
) -> None:
    list_view.clear()
    items: list[Any] = []
    for row, enabled in zip(rows, selected_flags, strict=True):
        marker = "●" if enabled else "○"
        if not row.selectable:
            items.append(
                list_item_cls(
                    label_cls(row.label, markup=False),
                    classes="config-section-header",
                )
            )
            continue
        suffix = " (Main + Trees)" if row.shared else ""
        items.append(
            list_item_cls(
                label_cls(f"{marker} {row.label}{suffix}", markup=False),
                classes=selectable_list_row_classes("config-row", selected=enabled),
            )
        )
    list_view.extend(items)
    apply_selectable_list_index(list_view, default_index)


def render_service_startup_list(
    list_view: Any,
    *,
    rows: tuple[tuple[str, str, str], ...],
    enabled_flags: Sequence[bool],
    label_cls: type,
    list_item_cls: type,
) -> None:
    list_view.clear()
    items: list[Any] = []
    for (_field_name, _mode, label), enabled in zip(rows, enabled_flags, strict=True):
        marker = "●" if enabled else "○"
        items.append(
            list_item_cls(
                label_cls(f"{marker} {label}", markup=False),
                classes=selectable_list_row_classes("config-row", selected=enabled),
            )
        )
    list_view.extend(items)
    apply_selectable_list_index(list_view, selectable_list_default_index(tuple(enabled_flags)))
