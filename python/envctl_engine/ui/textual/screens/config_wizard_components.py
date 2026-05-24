from __future__ import annotations

from dataclasses import dataclass

from ....config import StartupProfile
from ....config.persistence import ManagedConfigValues
from envctl_engine.ui.textual.list_row_styles import selectable_list_default_index
from .config_wizard_fields import _COMPONENT_FIELDS, _SERVICE_FIELDS


@dataclass(frozen=True, slots=True)
class ComponentRow:
    label: str
    component_id: str | None = None
    mode: str | None = None
    kind: str = "item"

    @property
    def selectable(self) -> bool:
        return self.kind == "item" and self.component_id is not None

    @property
    def shared(self) -> bool:
        return self.selectable and self.mode is None


def profile_for_mode(values: ManagedConfigValues, mode: str) -> StartupProfile:
    return values.trees_profile if mode == "trees" else values.main_profile


def component_rows(split_component_fields: set[str]) -> list[ComponentRow]:
    rows: list[ComponentRow] = [ComponentRow(label="Services", kind="header")]
    for field_name, label in _SERVICE_FIELDS:
        rows.extend(_component_rows_for_field(field_name, label, split_component_fields))
    rows.append(ComponentRow(label="Dependencies", kind="header"))
    for field_name, label in _COMPONENT_FIELDS:
        rows.extend(_component_rows_for_field(field_name, label, split_component_fields))
    return rows


def _component_rows_for_field(field_name: str, label: str, split_component_fields: set[str]) -> list[ComponentRow]:
    if field_name not in split_component_fields:
        return [ComponentRow(component_id=field_name, label=label)]
    return [
        ComponentRow(component_id=field_name, label=f"Main - {label}", mode="main"),
        ComponentRow(component_id=field_name, label=f"Trees - {label}", mode="trees"),
    ]


def service_startup_value(values: ManagedConfigValues, field_name: str, mode: str) -> bool:
    if field_name == "startup_enable":
        return bool(profile_for_mode(values, mode).startup_enable)
    if field_name == "backend_expect_listener":
        return bool(values.trees_backend_expect_listener if mode == "trees" else values.main_backend_expect_listener)
    return False


def toggle_service_startup_value(values: ManagedConfigValues, field_name: str, mode: str) -> None:
    if field_name == "startup_enable":
        profile = profile_for_mode(values, mode)
        profile.startup_enable = not profile.startup_enable
        return
    if field_name == "backend_expect_listener":
        if mode == "trees":
            values.trees_backend_expect_listener = not values.trees_backend_expect_listener
        else:
            values.main_backend_expect_listener = not values.main_backend_expect_listener


def sync_startup_enable_flags(values: ManagedConfigValues, *, include_service_startup: bool) -> None:
    if include_service_startup:
        return
    for profile in (values.main_profile, values.trees_profile):
        profile.startup_enable = bool(
            profile.backend_enable or profile.frontend_enable or any(profile.dependencies.values())
        )


def component_value(values: ManagedConfigValues, mode: str, field_name: str) -> bool:
    profile = profile_for_mode(values, mode)
    if field_name in {"backend_enable", "frontend_enable"}:
        return bool(getattr(profile, field_name))
    return profile.dependency_enabled(field_name)


def set_component_value(values: ManagedConfigValues, mode: str, field_name: str, enabled: bool) -> None:
    profile = profile_for_mode(values, mode)
    if field_name in {"backend_enable", "frontend_enable"}:
        setattr(profile, field_name, enabled)
        return
    profile.dependencies[field_name] = enabled


def component_values_differ(values: ManagedConfigValues, field_name: str) -> bool:
    return component_value(values, "main", field_name) != component_value(values, "trees", field_name)


def component_row_enabled(values: ManagedConfigValues, row: ComponentRow) -> bool:
    if not row.selectable:
        return False
    if row.shared:
        return component_value(values, "main", row.component_id or "")
    return component_value(values, row.mode or "main", row.component_id or "")


def default_component_index(rows: list[ComponentRow], selected_flags: list[bool]) -> int:
    selected_index = selectable_list_default_index(selected_flags)
    if 0 <= selected_index < len(rows) and rows[selected_index].selectable:
        return selected_index
    return next((index for index, row in enumerate(rows) if row.selectable), 0)


def nearest_selectable_component_index(rows: list[ComponentRow], index: int, *, step: int) -> int:
    if not rows:
        return 0
    candidate = max(0, min(index, len(rows) - 1))
    if rows[candidate].selectable:
        return candidate
    probe = candidate
    while 0 <= probe + step < len(rows):
        probe += step
        if rows[probe].selectable:
            return probe
    probe = candidate
    while 0 <= probe - step < len(rows):
        probe -= step
        if rows[probe].selectable:
            return probe
    return candidate
