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


@dataclass(frozen=True, slots=True)
class ComponentInteractionResult:
    changed: bool
    target_index: int = 0
    error_message: str | None = None


class ConfigWizardComponentInteraction:
    def __init__(self, values: ManagedConfigValues, *, split_component_fields: set[str]) -> None:
        self.values = values
        self.split_component_fields = set(split_component_fields)

    @classmethod
    def from_values(cls, values: ManagedConfigValues) -> ConfigWizardComponentInteraction:
        split_component_fields = {
            field_name for field_name, _label in _COMPONENT_FIELDS if component_values_differ(values, field_name)
        }
        return cls(values, split_component_fields=split_component_fields)

    def rows(self) -> list[ComponentRow]:
        return component_rows(self.split_component_fields)

    def selected_flags(self, rows: list[ComponentRow]) -> list[bool]:
        return [self.row_enabled(row) if row.selectable else False for row in rows]

    def row_enabled(self, row: ComponentRow) -> bool:
        return component_row_enabled(self.values, row)

    def default_index(self, rows: list[ComponentRow], selected_flags: list[bool]) -> int:
        return default_component_index(rows, selected_flags)

    def nearest_selectable_index(self, index: int, *, step: int) -> int:
        return nearest_selectable_component_index(self.rows(), index, step=step)

    def toggle_component_at(self, index: int) -> ComponentInteractionResult:
        rows = self.rows()
        row = self._row_at(rows, index)
        if row is None or not row.selectable:
            return ComponentInteractionResult(changed=False, target_index=max(index, 0))
        enabled = not self.row_enabled(row)
        if row.shared:
            set_component_value(self.values, "main", row.component_id or "", enabled)
            set_component_value(self.values, "trees", row.component_id or "", enabled)
        else:
            set_component_value(self.values, row.mode or "main", row.component_id or "", enabled)
        return ComponentInteractionResult(changed=True, target_index=index)

    def toggle_split_at(self, index: int) -> ComponentInteractionResult:
        rows = self.rows()
        row = self._row_at(rows, index)
        if row is None or not row.selectable:
            return ComponentInteractionResult(changed=False, target_index=max(index, 0))
        component_id = row.component_id or ""
        if component_id in self.split_component_fields:
            if component_values_differ(self.values, component_id):
                return ComponentInteractionResult(
                    changed=False,
                    target_index=index,
                    error_message=(
                        "Main and Trees differ for this component. Make them match before merging the split rows."
                    ),
                )
            self.split_component_fields.remove(component_id)
            return ComponentInteractionResult(
                changed=True,
                target_index=self._target_index(component_id=component_id, shared=True),
            )
        self.split_component_fields.add(component_id)
        return ComponentInteractionResult(
            changed=True,
            target_index=self._target_index(component_id=component_id, mode=row.mode or "main"),
        )

    def _target_index(self, *, component_id: str, shared: bool = False, mode: str | None = None) -> int:
        for index, row in enumerate(self.rows()):
            if row.component_id != component_id:
                continue
            if shared and row.shared:
                return index
            if mode is not None and row.mode == mode:
                return index
        return 0

    @staticmethod
    def _row_at(rows: list[ComponentRow], index: int) -> ComponentRow | None:
        if index < 0 or index >= len(rows):
            return None
        return rows[index]


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
