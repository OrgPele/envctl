from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from envctl_engine.planning import planning_existing_counts


def prompt_planning_selection(
    *,
    planning_files: list[str],
    raw_projects: list[tuple[str, Path]],
    run_planning_selection_menu: Callable[..., dict[str, int] | None],
) -> dict[str, int] | None:
    existing_counts = planning_existing_counts(projects=raw_projects, planning_files=planning_files)
    selected_counts = {
        plan_file: max(int(existing_counts.get(plan_file, 0)), 0)
        for plan_file in planning_files
    }
    return run_planning_selection_menu(
        planning_files=planning_files,
        selected_counts=selected_counts,
        existing_counts=existing_counts,
    )
