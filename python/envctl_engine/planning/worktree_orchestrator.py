from __future__ import annotations

from pathlib import Path
from typing import Any

from envctl_engine.runtime.command_router import Route
from envctl_engine.planning.worktree_domain import (
    _apply_setup_worktree_selection as domain_apply_setup_worktree_selection,
    _initial_plan_selected_counts as domain_initial_plan_selected_counts,
    _load_plan_selection_memory as domain_load_plan_selection_memory,
    _planning_keep_plan_enabled as domain_planning_keep_plan_enabled,
    _prompt_planning_selection as domain_prompt_planning_selection,
    _run_planning_selection_menu as domain_run_planning_selection_menu,
    _save_plan_selection_memory as domain_save_plan_selection_memory,
    _select_plan_projects as domain_select_plan_projects,
    _sync_plan_worktrees_from_plan_counts as domain_sync_plan_worktrees_from_plan_counts,
)


class PlanningWorktreeOrchestrator:
    _apply_setup_worktree_selection = domain_apply_setup_worktree_selection
    _select_plan_projects = domain_select_plan_projects
    _prompt_planning_selection = domain_prompt_planning_selection
    _initial_plan_selected_counts = domain_initial_plan_selected_counts
    _load_plan_selection_memory = domain_load_plan_selection_memory
    _save_plan_selection_memory = domain_save_plan_selection_memory
    _planning_keep_plan_enabled = domain_planning_keep_plan_enabled
    _sync_plan_worktrees_from_plan_counts = domain_sync_plan_worktrees_from_plan_counts

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def __getattr__(self, name: str) -> Any:
        return getattr(self._runtime, name)

    @property
    def runtime(self) -> Any:
        return self._runtime

    def apply_setup_worktree_selection(
        self,
        route: Route,
        project_contexts: list[Any],
    ) -> list[Any]:
        return self._apply_setup_worktree_selection(route, project_contexts)

    def select_plan_projects(self, route: Route, project_contexts: list[Any]) -> list[Any]:
        return self._select_plan_projects(route, project_contexts)

    def prompt_planning_selection(
        self,
        planning_files: list[str],
        raw_projects: list[tuple[str, Path]],
    ) -> dict[str, int]:
        return self._prompt_planning_selection(planning_files, raw_projects)

    def initial_plan_selected_counts(
        self,
        *,
        planning_files: list[str],
        existing_counts: dict[str, int],
    ) -> dict[str, int]:
        return self._initial_plan_selected_counts(
            planning_files=planning_files,
            existing_counts=existing_counts,
        )

    def run_planning_selection_menu(
        self,
        *,
        planning_files: list[str],
        selected_counts: dict[str, int],
        existing_counts: dict[str, int],
    ) -> dict[str, int] | None:
        return self._run_planning_selection_menu(
            planning_files=planning_files,
            selected_counts=selected_counts,
            existing_counts=existing_counts,
        )

    def _run_planning_selection_menu(
        self,
        *,
        planning_files: list[str],
        selected_counts: dict[str, int],
        existing_counts: dict[str, int],
    ) -> dict[str, int] | None:
        runtime_override = getattr(self._runtime, "__dict__", {}).get("_run_planning_selection_menu")
        if runtime_override is not None:
            return runtime_override(
                planning_files=planning_files,
                selected_counts=selected_counts,
                existing_counts=existing_counts,
            )
        return domain_run_planning_selection_menu(
            self,
            planning_files=planning_files,
            selected_counts=selected_counts,
            existing_counts=existing_counts,
        )

    def load_plan_selection_memory(self) -> dict[str, int]:
        return self._load_plan_selection_memory()

    def save_plan_selection_memory(self, selected_counts: dict[str, int]) -> None:
        self._save_plan_selection_memory(selected_counts)

    def planning_keep_plan_enabled(self, route: Route) -> bool:
        return self._planning_keep_plan_enabled(route)

    def sync_plan_worktrees_from_plan_counts(
        self,
        *,
        plan_counts: dict[str, int],
        raw_projects: list[tuple[str, Path]],
        keep_plan: bool,
    ) -> tuple[list[tuple[str, Path]], str | None]:
        return self._sync_plan_worktrees_from_plan_counts(
            plan_counts=plan_counts,
            raw_projects=raw_projects,
            keep_plan=keep_plan,
        )
