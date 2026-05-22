from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from envctl_engine.planning import planning_existing_counts


def prompt_planning_selection(
    *,
    planning_files: list[str],
    raw_projects: list[tuple[str, Path]],
    initial_plan_selected_counts: Callable[..., dict[str, int]],
    run_planning_selection_menu: Callable[..., dict[str, int] | None],
    save_plan_selection_memory: Callable[[dict[str, int]], None],
    persist_memory: bool = True,
) -> dict[str, int] | None:
    existing_counts = planning_existing_counts(projects=raw_projects, planning_files=planning_files)
    selected_counts = initial_plan_selected_counts(
        planning_files=planning_files,
        existing_counts=existing_counts,
    )
    chosen = run_planning_selection_menu(
        planning_files=planning_files,
        selected_counts=selected_counts,
        existing_counts=existing_counts,
    )
    if chosen and persist_memory:
        save_plan_selection_memory(chosen)
    return chosen
