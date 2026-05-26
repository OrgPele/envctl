from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

from envctl_engine.ui.selector_model import SelectorItem


@dataclass(slots=True)
class PrFlowResult:
    project_names: list[str]
    base_branch: str | None
    cancelled: bool = False
    cancelled_step: str | None = None


@dataclass(slots=True)
class PrFlowRow:
    token: str
    label: str
    selected: bool = False


PrFlowStep = Literal["project", "branch"]


@dataclass(slots=True)
class PrFlowState:
    project_rows: list[PrFlowRow]
    branch_rows: list[PrFlowRow]
    step: PrFlowStep
    project_list_index: int = 0
    branch_list_index: int = 0

    @classmethod
    def create(cls, *, project_rows: list[PrFlowRow], branch_rows: list[PrFlowRow]) -> "PrFlowState":
        if len(project_rows) == 1:
            project_rows[0].selected = True
            step: PrFlowStep = "branch"
        else:
            step = "project"
        return cls(project_rows=project_rows, branch_rows=branch_rows, step=step)

    def rows(self) -> list[PrFlowRow]:
        return self.branch_rows if self.step == "branch" else self.project_rows

    def current_index(self) -> int:
        return self.branch_list_index if self.step == "branch" else self.project_list_index

    def set_current_index(self, value: int | None) -> None:
        index = 0 if value is None else max(0, value)
        if self.step == "branch":
            self.branch_list_index = index
        else:
            self.project_list_index = index

    def prompt_text(self) -> str:
        return "Create PR into" if self.step == "branch" else "Create PR for"

    def status_text(self, *, focus_index: int) -> str:
        rows = self.rows()
        selected_count = sum(1 for row in rows if row.selected)
        total = len(rows)
        if self.step == "branch":
            return f"Select base branch • focus: {focus_index}/{total}"
        return f"{selected_count} selected • focus: {focus_index}/{total}"

    def row_text(self, row: PrFlowRow) -> str:
        marker = "●" if row.selected else "○"
        badge = "branch" if self.step == "branch" else "project"
        return f"{marker} {row.label}  ({badge})"

    def toggle_row(self, row: PrFlowRow) -> None:
        if self.step == "branch":
            for candidate in self.branch_rows:
                candidate.selected = candidate is row
            return
        row.selected = not row.selected

    def selected_projects(self) -> list[str]:
        return [row.token for row in self.project_rows if row.selected]

    def selected_branch(self, *, focused_row: PrFlowRow | None) -> str | None:
        selected = next((row.token for row in self.branch_rows if row.selected), "")
        if selected:
            return selected
        return focused_row.token if focused_row is not None and self.step == "branch" else None

    def advance_to_branch_if_ready(self) -> bool:
        if self.step != "project" or not self.selected_projects():
            return False
        self.step = "branch"
        return True

    def back_to_project_step(self) -> bool:
        if self.step != "branch" or len(self.project_rows) == 1:
            return False
        self.step = "project"
        return True

    def can_go_back(self) -> bool:
        return self.step == "branch" and len(self.project_rows) > 1

    def result(self, *, focused_row: PrFlowRow | None = None) -> PrFlowResult:
        return PrFlowResult(
            project_names=self.selected_projects(),
            base_branch=self.selected_branch(focused_row=focused_row),
        )

    def cancel_result(self) -> PrFlowResult:
        return PrFlowResult(
            project_names=[],
            base_branch=None,
            cancelled=True,
            cancelled_step=self.step,
        )


def build_project_rows(projects: Sequence[object], initial_project_names: Sequence[str] | None) -> list[PrFlowRow]:
    initial_projects = {
        str(name).strip().lower()
        for name in (initial_project_names or [])
        if str(name).strip()
    }
    rows: list[PrFlowRow] = []
    for project in projects:
        name = str(getattr(project, "name", "")).strip()
        if not name:
            continue
        rows.append(
            PrFlowRow(
                token=name,
                label=name,
                selected=name.lower() in initial_projects,
            )
        )
    return rows


def build_branch_rows(branch_options: Sequence[SelectorItem], default_branch: str) -> list[PrFlowRow]:
    rows: list[PrFlowRow] = []
    for option in branch_options:
        token = str(option.token).strip()
        if not token:
            continue
        label = str(option.label).strip() or token
        rows.append(PrFlowRow(token=token, label=label, selected=token == default_branch))
    return rows
