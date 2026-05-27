from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PlanningRow:
    plan_file: str
    count: int
    existing: int
    visible: bool = True


@dataclass(frozen=True, slots=True)
class PlanningRenderEntry:
    model_index: int
    plan_file: str
    text: str
    selected: bool


class PlanningSelectionModel:
    def __init__(self, rows: list[PlanningRow]) -> None:
        self.rows = rows

    @classmethod
    def from_counts(
        cls,
        *,
        planning_files: list[str],
        selected_counts: dict[str, int],
        existing_counts: dict[str, int],
    ) -> PlanningSelectionModel:
        return cls(
            [
                PlanningRow(
                    plan_file=plan_file,
                    count=max(0, int(selected_counts.get(plan_file, 0))),
                    existing=max(0, int(existing_counts.get(plan_file, 0))),
                )
                for plan_file in planning_files
            ]
        )

    def render_entries(self) -> list[PlanningRenderEntry]:
        entries: list[PlanningRenderEntry] = []
        for index, row in enumerate(self.rows):
            if not row.visible:
                continue
            entries.append(
                PlanningRenderEntry(
                    model_index=index,
                    plan_file=row.plan_file,
                    text=self.row_text(row),
                    selected=row.count > 0,
                )
            )
        return entries

    @staticmethod
    def row_text(row: PlanningRow) -> str:
        existing = f" (existing {row.existing}x)" if row.existing > 0 else ""
        marker = "●" if row.count > 0 else "○"
        return f"{marker} [{row.count}x] {row.plan_file}{existing}"

    def status_text(self) -> str:
        visible = [row for row in self.rows if row.visible]
        selected = sum(1 for row in visible if row.count > 0)
        total_selected = sum(1 for row in self.rows if row.count > 0)
        return f"{selected} selected visible • {total_selected} selected total • {len(visible)} visible"

    def run_enabled(self) -> bool:
        return any((row.count > 0) or (row.existing > 0) for row in self.rows)

    @staticmethod
    def default_count(row: PlanningRow) -> int:
        return row.existing if row.existing > 0 else 1

    def set_count(self, row: PlanningRow, count: int) -> PlanningRow:
        row.count = max(0, int(count))
        return row

    def toggle_model_index(self, model_index: int) -> PlanningRow | None:
        if model_index < 0 or model_index >= len(self.rows):
            return None
        row = self.rows[model_index]
        if row.count > 0:
            row.count = 0
        else:
            row.count = self.default_count(row)
        return row

    def activate_row(self, row: PlanningRow) -> None:
        row.count = self.default_count(row)

    @staticmethod
    def deactivate_row(row: PlanningRow) -> None:
        row.count = 0

    def apply_filter(self, query: str) -> str:
        normalized = str(query or "").strip().lower()
        for row in self.rows:
            row.visible = normalized in row.plan_file.lower() if normalized else True
        return normalized

    def result(self) -> dict[str, int]:
        has_existing = any(row.existing > 0 for row in self.rows)
        if has_existing:
            return {row.plan_file: int(row.count) for row in self.rows}
        return {row.plan_file: int(row.count) for row in self.rows if row.count > 0}
