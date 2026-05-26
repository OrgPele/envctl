from __future__ import annotations

from pathlib import Path
from typing import Any

from envctl_engine.planning.worktree_domain import (
    _cleanup_empty_feature_root as domain_cleanup_empty_feature_root,
    _coerce_setup_entries as domain_coerce_setup_entries,
    _create_feature_worktrees as domain_create_feature_worktrees,
    _create_single_worktree as domain_create_single_worktree,
    _decode_planning_menu_escape as domain_decode_planning_menu_escape,
    _delete_feature_worktrees as domain_delete_feature_worktrees,
    _feature_project_candidates as domain_feature_project_candidates,
    _move_plan_to_done as domain_move_plan_to_done,
    _next_available_iteration as domain_next_available_iteration,
    _planning_done_root as domain_planning_done_root,
    _planning_menu_apply_key as domain_planning_menu_apply_key,
    _planning_root as domain_planning_root,
    _plan_selection_memory_path as domain_plan_selection_memory_path,
    _preferred_tree_root_for_feature as domain_preferred_tree_root_for_feature,
    _project_sort_key_for_feature as domain_project_sort_key_for_feature,
    _read_planning_menu_escape_sequence as domain_read_planning_menu_escape_sequence,
    _read_planning_menu_key as domain_read_planning_menu_key,
    _render_planning_selection_menu as domain_render_planning_selection_menu,
    _resolve_planning_selection_target as domain_resolve_planning_selection_target,
    _setup_worktree_placeholder_fallback_enabled as domain_setup_worktree_placeholder_fallback_enabled,
    _setup_worktree_requested as domain_setup_worktree_requested,
    _terminal_size as domain_terminal_size,
    _to_terminal_lines as domain_to_terminal_lines,
    _trees_root_for_worktree as domain_trees_root_for_worktree,
    _truncate_text as domain_truncate_text,
    _worktree_add_failure as domain_worktree_add_failure,
)
from envctl_engine.runtime.command_router import Route


def _planning_orchestrator(runtime: Any) -> Any:
    return getattr(runtime, "planning_worktree_orchestrator")


class RuntimePlanningFacadeMixin:
    _coerce_setup_entries = domain_coerce_setup_entries
    _create_single_worktree = domain_create_single_worktree
    _preferred_tree_root_for_feature = domain_preferred_tree_root_for_feature
    _trees_root_for_worktree = domain_trees_root_for_worktree
    _render_planning_selection_menu = domain_render_planning_selection_menu
    _terminal_size = domain_terminal_size
    _truncate_text = staticmethod(domain_truncate_text)
    _to_terminal_lines = staticmethod(domain_to_terminal_lines)
    _read_planning_menu_key = domain_read_planning_menu_key
    _read_planning_menu_escape_sequence = staticmethod(domain_read_planning_menu_escape_sequence)
    _decode_planning_menu_escape = staticmethod(domain_decode_planning_menu_escape)
    _planning_menu_apply_key = domain_planning_menu_apply_key
    _resolve_planning_selection_target = domain_resolve_planning_selection_target
    _planning_root = domain_planning_root
    _planning_done_root = domain_planning_done_root
    _plan_selection_memory_path = domain_plan_selection_memory_path
    _create_feature_worktrees = domain_create_feature_worktrees
    _worktree_add_failure = domain_worktree_add_failure
    _setup_worktree_placeholder_fallback_enabled = domain_setup_worktree_placeholder_fallback_enabled
    _delete_feature_worktrees = domain_delete_feature_worktrees
    _cleanup_empty_feature_root = domain_cleanup_empty_feature_root
    _move_plan_to_done = domain_move_plan_to_done
    _feature_project_candidates = domain_feature_project_candidates
    _project_sort_key_for_feature = staticmethod(domain_project_sort_key_for_feature)
    _next_available_iteration = staticmethod(domain_next_available_iteration)
    _setup_worktree_requested = staticmethod(domain_setup_worktree_requested)

    def _apply_setup_worktree_selection(self, route: Route, project_contexts: list[Any]) -> list[Any]:
        return _planning_orchestrator(self).apply_setup_worktree_selection(route, project_contexts)

    def _select_plan_projects(self, route: Route, project_contexts: list[Any]) -> list[Any]:
        return _planning_orchestrator(self).select_plan_projects(route, project_contexts)

    def _prompt_planning_selection(
        self,
        planning_files: list[str],
        raw_projects: list[tuple[str, Path]],
    ) -> dict[str, int] | None:
        return _planning_orchestrator(self).prompt_planning_selection(planning_files, raw_projects)

    def _initial_plan_selected_counts(
        self,
        *,
        planning_files: list[str],
        existing_counts: dict[str, int],
    ) -> dict[str, int]:
        return _planning_orchestrator(self).initial_plan_selected_counts(
            planning_files=planning_files,
            existing_counts=existing_counts,
        )

    def _run_planning_selection_menu(
        self,
        *,
        planning_files: list[str],
        selected_counts: dict[str, int],
        existing_counts: dict[str, int],
    ) -> dict[str, int] | None:
        return _planning_orchestrator(self).run_planning_selection_menu(
            planning_files=planning_files,
            selected_counts=selected_counts,
            existing_counts=existing_counts,
        )

    def _load_plan_selection_memory(self) -> dict[str, int]:
        return _planning_orchestrator(self).load_plan_selection_memory()

    def _save_plan_selection_memory(self, selected_counts: dict[str, int]) -> None:
        _planning_orchestrator(self).save_plan_selection_memory(selected_counts)

    def _planning_keep_plan_enabled(self, route: Route) -> bool:
        return _planning_orchestrator(self).planning_keep_plan_enabled(route)

    def _sync_plan_worktrees_from_plan_counts(
        self,
        *,
        plan_counts: dict[str, int],
        raw_projects: list[tuple[str, Path]],
        keep_plan: bool,
    ) -> tuple[list[tuple[str, Path]], str | None]:
        return _planning_orchestrator(self).sync_plan_worktrees_from_plan_counts(
            plan_counts=plan_counts,
            raw_projects=raw_projects,
            keep_plan=keep_plan,
        )
