from __future__ import annotations

import sys
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from envctl_engine.planning.worktree_creation_commands import (
    worktree_branch_exists as _worktree_branch_exists_impl,
    worktree_branch_name as _worktree_branch_name_impl,
    worktree_start_point as _worktree_start_point_impl,
)
from envctl_engine.planning.worktree_creation_recovery import (
    setup_worktree_placeholder_fallback_enabled as _setup_worktree_placeholder_fallback_enabled_impl,
    worktree_target_created as _worktree_target_created_impl,
)
from envctl_engine.planning.worktree_git_hooks import (
    worktree_git_hooks_disabled as _worktree_git_hooks_disabled_impl,
    worktree_git_hooks_policy as _worktree_git_hooks_policy_impl,
)
from envctl_engine.planning.worktree_main_task import (
    next_available_iteration as _next_available_iteration_impl,
    seed_main_task_from_plan as _seed_main_task_from_plan_impl,
)
from envctl_engine.planning.worktree_menu_terminal_support import (
    decode_planning_menu_escape as _decode_planning_menu_escape_impl,
    planning_menu_apply_key as _planning_menu_apply_key_impl,
    read_planning_menu_escape_sequence as _read_planning_menu_escape_sequence_impl,
    read_planning_menu_key as _read_planning_menu_key_impl,
    render_planning_selection_menu as _render_planning_selection_menu_impl,
    terminal_size as _terminal_size_impl,
    to_terminal_lines as _to_terminal_lines_impl,
    truncate_text as _truncate_text_impl,
)
from envctl_engine.planning.worktree_plan_selection import (
    adjust_plan_counts_for_fresh_ai_launch as _adjust_plan_counts_for_fresh_ai_launch_impl,
    fresh_ai_launch_transport as _fresh_ai_launch_transport_impl,
    planning_keep_plan_enabled as _planning_keep_plan_enabled_impl,
    route_requests_fresh_ai_worktree as _route_requests_fresh_ai_worktree_impl,
)
from envctl_engine.planning.worktree_project_catalog import (
    cleanup_empty_feature_root as _cleanup_empty_feature_root_impl,
    feature_project_candidates as _feature_project_candidates_impl,
    project_sort_key_for_feature as _project_sort_key_for_feature_impl,
)
from envctl_engine.planning.worktree_selection_memory import (
    initial_plan_selected_counts as _initial_plan_selected_counts_impl,
    load_plan_selection_memory as _load_plan_selection_memory_impl,
    plan_selection_memory_path as _plan_selection_memory_path_impl,
    save_plan_selection_memory as _save_plan_selection_memory_impl,
)
from envctl_engine.planning.worktree_shared_artifacts import (
    link_repo_local_shared_artifacts as _link_repo_local_shared_artifacts_impl,
)
from envctl_engine.planning.worktree_setup_entries import (
    coerce_setup_entries as _coerce_setup_entries_impl,
)
from envctl_engine.planning.worktree_spinner_support import (
    worktree_spinner_fail as _worktree_spinner_fail_impl,
    worktree_spinner_finish as _worktree_spinner_finish_impl,
    worktree_spinner_policy as _worktree_spinner_policy_impl,
    worktree_spinner_start as _worktree_spinner_start_impl,
    worktree_spinner_stop as _worktree_spinner_stop_impl,
    worktree_spinner_update as _worktree_spinner_update_impl,
)
from envctl_engine.planning.worktree_code_intelligence import (
    prepare_worktree_code_intelligence as _prepare_worktree_code_intelligence_impl,
)
from envctl_engine.planning.worktree_path_support import (
    planning_done_root as _planning_done_root_impl,
    planning_root as _planning_root_impl,
    preferred_tree_root_for_feature as _preferred_tree_root_for_feature_impl,
    render_planning_path as _render_planning_path_impl,
    resolve_planning_selection_target as _resolve_planning_selection_target_impl,
    setup_worktree_requested as _setup_worktree_requested_impl,
    trees_root_for_worktree as _trees_root_for_worktree_impl,
)
from envctl_engine.planning.worktree_provenance import (
    active_fresh_ai_worktree_protection_reason as _active_fresh_ai_worktree_protection_reason_impl,
    build_worktree_provenance as _build_worktree_provenance_impl,
    detect_default_branch as _detect_default_branch_impl,
    fresh_ai_launch_marker_is_fresh as _fresh_ai_launch_marker_is_fresh_impl,
    git_command_output as _git_command_output_impl,
    read_worktree_provenance as _read_worktree_provenance_impl,
    resolve_branch_ref as _resolve_branch_ref_impl,
    write_worktree_provenance as _write_worktree_provenance_impl,
)
from envctl_engine.planning.worktree_runtime_bridge import create_planning_runtime_bridge
from envctl_engine.planning.plan_agent.models import (
    PlanWorktreeSyncResult,
)
from envctl_engine.planning.protocols import ProjectContextLike
from envctl_engine.runtime.command_router import Route
from envctl_engine.ui.spinner_service import SpinnerPolicy


def delete_worktree_path(*args: Any, **kwargs: Any) -> Any:
    """Compatibility patch point for legacy worktree-domain callers."""
    from envctl_engine.actions.actions_worktree import delete_worktree_path as delete_worktree_path_impl

    return delete_worktree_path_impl(*args, **kwargs)


def select_planning_counts_textual(*args: Any, **kwargs: Any) -> Any:
    """Compatibility patch point for legacy planning-selector tests/callers."""
    from envctl_engine.ui.textual.screens.planning_selector import (
        select_planning_counts_textual as select_planning_counts_textual_impl,
    )

    return select_planning_counts_textual_impl(*args, **kwargs)


def _planning_runtime_bridge(self: Any) -> Any:
    return create_planning_runtime_bridge(
        self,
        delete_worktree_path_fn=delete_worktree_path,
        select_planning_counts_fn=select_planning_counts_textual,
    )


def _worktree_spinner_policy(self: Any, *, op_id: str) -> SpinnerPolicy:
    return _worktree_spinner_policy_impl(self, op_id=op_id)


def _worktree_spinner_update(
    self: Any,
    *,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
    terminal_message: str | None = None,
) -> None:
    _worktree_spinner_update_impl(
        self,
        enabled=enabled,
        active_spinner=active_spinner,
        op_id=op_id,
        message=message,
        terminal_message=terminal_message,
    )


def _render_planning_path(
    self: Any,
    *,
    absolute_path: Path,
    display_text: str,
    interactive_tty: bool | None = None,
) -> str:
    return _render_planning_path_impl(
        absolute_path=absolute_path,
        display_text=display_text,
        env=getattr(self, "env", {}),
        stream=sys.stdout,
        interactive_tty=interactive_tty,
    )


def _worktree_spinner_start(
    self: Any,
    *,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
) -> None:
    _worktree_spinner_start_impl(
        self,
        enabled=enabled,
        active_spinner=active_spinner,
        op_id=op_id,
        message=message,
    )


def _worktree_spinner_finish(
    self: Any,
    *,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
) -> None:
    _worktree_spinner_finish_impl(
        self,
        enabled=enabled,
        active_spinner=active_spinner,
        op_id=op_id,
        message=message,
    )


def _worktree_spinner_fail(
    self: Any,
    *,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
) -> None:
    _worktree_spinner_fail_impl(
        self,
        enabled=enabled,
        active_spinner=active_spinner,
        op_id=op_id,
        message=message,
    )


def _worktree_spinner_stop(self: Any, *, enabled: bool, op_id: str) -> None:
    _worktree_spinner_stop_impl(self, enabled=enabled, op_id=op_id)


def _coerce_setup_entries(
    self: Any,
    *,
    route: Route,
    flag_name: str,
    value_name: str,
) -> list[tuple[str, str]]:
    return _coerce_setup_entries_impl(flags=route.flags, flag_name=flag_name, value_name=value_name)


def _create_single_worktree(self, *, feature: str, iteration: str) -> str | None:
    return _planning_runtime_bridge(self).create_single_worktree(feature=feature, iteration=iteration)


def _apply_setup_worktree_selection(
    self: Any, route: Route, project_contexts: list[ProjectContextLike]
) -> list[ProjectContextLike]:
    return _planning_runtime_bridge(self).apply_setup_worktree_selection(route, project_contexts)


def _apply_multi_setup_entry(
    self: Any,
    *,
    feature: str,
    count_raw: str,
    raw_projects: list[tuple[str, Path]],
    enabled: bool,
    active_spinner: Any,
    op_id: str,
) -> tuple[list[tuple[str, Path]], set[str]]:
    return _planning_runtime_bridge(self).apply_multi_setup_entry(
        feature=feature,
        count_raw=count_raw,
        raw_projects=raw_projects,
        enabled=enabled,
        active_spinner=active_spinner,
        op_id=op_id,
    )


def _apply_single_setup_entry(
    self: Any,
    *,
    feature: str,
    iteration_raw: str,
    raw_projects: list[tuple[str, Path]],
    setup_worktree_existing: bool,
    setup_worktree_recreate: bool,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
) -> tuple[list[tuple[str, Path]], str]:
    return _planning_runtime_bridge(self).apply_single_setup_entry(
        feature=feature,
        iteration_raw=iteration_raw,
        raw_projects=raw_projects,
        setup_worktree_existing=setup_worktree_existing,
        setup_worktree_recreate=setup_worktree_recreate,
        enabled=enabled,
        active_spinner=active_spinner,
        op_id=op_id,
    )


def _preferred_tree_root_for_feature(self, feature: str) -> Path:
    return _preferred_tree_root_for_feature_impl(
        base_dir=self.config.base_dir,
        trees_dir_name=self.config.trees_dir_name,
        feature=feature,
    )


def _trees_root_for_worktree(self, worktree_root: Path) -> Path:
    return _trees_root_for_worktree_impl(
        base_dir=self.config.base_dir,
        trees_dir_name=self.config.trees_dir_name,
        worktree_root=worktree_root,
    )


def _select_plan_projects(
    self: Any, route: Route, project_contexts: list[ProjectContextLike]
) -> list[ProjectContextLike]:
    return _planning_runtime_bridge(self).select_plan_projects(route, project_contexts)


def _prompt_planning_selection(
    self: Any,
    planning_files: list[str],
    raw_projects: list[tuple[str, Path]],
    *,
    persist_memory: bool = True,
) -> dict[str, int] | None:
    return _planning_runtime_bridge(self).prompt_planning_selection(
        planning_files=planning_files,
        raw_projects=raw_projects,
        persist_memory=persist_memory,
    )


_route_requests_fresh_ai_worktree = _route_requests_fresh_ai_worktree_impl
_fresh_ai_launch_transport = _fresh_ai_launch_transport_impl


def _adjust_plan_counts_for_fresh_ai_launch(
    *,
    raw_projects: list[tuple[str, Path]],
    plan_counts: OrderedDict[str, int],
    route: Route,
) -> OrderedDict[str, int]:
    return _adjust_plan_counts_for_fresh_ai_launch_impl(
        raw_projects=raw_projects,
        plan_counts=plan_counts,
        route=route,
    )


def _initial_plan_selected_counts(
    self: Any,
    *,
    planning_files: list[str],
    existing_counts: dict[str, int],
) -> dict[str, int]:
    remembered = self._load_plan_selection_memory()
    return _initial_plan_selected_counts_impl(
        planning_files=planning_files,
        existing_counts=existing_counts,
        remembered_counts=remembered,
    )


def _run_planning_selection_menu(
    self: Any,
    *,
    planning_files: list[str],
    selected_counts: dict[str, int],
    existing_counts: dict[str, int],
) -> dict[str, int] | None:
    return _planning_runtime_bridge(self).run_planning_selection_menu(
        planning_files=planning_files,
        selected_counts=selected_counts,
        existing_counts=existing_counts,
    )


def _render_planning_selection_menu(
    self: Any,
    *,
    planning_files: list[str],
    selected_counts: dict[str, int],
    existing_counts: dict[str, int],
    cursor: int,
    message: str,
    terminal_width: int | None = None,
    terminal_height: int | None = None,
) -> str:
    return _render_planning_selection_menu_impl(
        self.terminal_ui,
        planning_files=planning_files,
        selected_counts=selected_counts,
        existing_counts=existing_counts,
        cursor=cursor,
        message=message,
        terminal_width=terminal_width,
        terminal_height=terminal_height,
    )


def _terminal_size(self: Any) -> tuple[int, int]:
    return _terminal_size_impl(self.terminal_ui)


_truncate_text = _truncate_text_impl
_to_terminal_lines = _to_terminal_lines_impl


def _read_planning_menu_key(self: Any, *, fd: int, selector: Callable[..., object]) -> str:
    return _read_planning_menu_key_impl(self.terminal_ui, fd=fd, selector=selector)


_read_planning_menu_escape_sequence = _read_planning_menu_escape_sequence_impl
_decode_planning_menu_escape = _decode_planning_menu_escape_impl


def _planning_menu_apply_key(
    self: Any,
    *,
    key: str,
    cursor: int,
    planning_files: list[str],
    selected_counts: dict[str, int],
    existing_counts: dict[str, int],
) -> tuple[int, str, str]:
    return _planning_menu_apply_key_impl(
        self.terminal_ui,
        key=key,
        cursor=cursor,
        planning_files=planning_files,
        selected_counts=selected_counts,
        existing_counts=existing_counts,
    )


def _resolve_planning_selection_target(
    self: Any,
    *,
    target_token: str,
    planning_files: list[str],
) -> str:
    return _resolve_planning_selection_target_impl(
        target_token=target_token,
        planning_files=planning_files,
        planning_dir=self.config.planning_dir,
        base_dir=self.config.base_dir,
    )


def _plan_selection_memory_path(self: Any) -> Path:
    return _plan_selection_memory_path_impl(runtime_root=self.runtime_root)


def _planning_root(self: Any) -> Path:
    return _planning_root_impl(planning_dir=self.config.planning_dir)


def _planning_done_root(self: Any) -> Path:
    return _planning_done_root_impl(planning_dir=self.config.planning_dir)


def _load_plan_selection_memory(self: Any) -> dict[str, int]:
    return _load_plan_selection_memory_impl(
        runtime_root=self.runtime_root,
        runtime_legacy_root=self.runtime_legacy_root,
    )


def _save_plan_selection_memory(self: Any, selected_counts: dict[str, int]) -> None:
    _save_plan_selection_memory_impl(
        runtime_root=self.runtime_root,
        runtime_legacy_root=self.runtime_legacy_root,
        selected_counts=selected_counts,
    )


def _planning_keep_plan_enabled(self: Any, route: Route) -> bool:
    return _planning_keep_plan_enabled_impl(route=route, env=self.env, config_raw=self.config.raw)


def _sync_plan_worktrees_from_plan_counts(
    self: Any,
    *,
    plan_counts: Mapping[str, int],
    raw_projects: list[tuple[str, Path]],
    keep_plan: bool,
    fresh_ai_launch: bool = False,
    launch_transport: str = "",
) -> PlanWorktreeSyncResult:
    return _planning_runtime_bridge(self).sync_plan_worktrees_from_plan_counts(
        plan_counts=plan_counts,
        raw_projects=raw_projects,
        keep_plan=keep_plan,
        fresh_ai_launch=fresh_ai_launch,
        launch_transport=launch_transport,
    )


def _sync_single_plan_worktree_target(
    self: Any,
    *,
    plan_file: str,
    desired_raw: int,
    projects: list[tuple[str, Path]],
    keep_plan: bool,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    fresh_ai_launch: bool = False,
    launch_transport: str = "",
) -> PlanWorktreeSyncResult:
    return _planning_runtime_bridge(self).sync_single_plan_worktree_target(
        plan_file=plan_file,
        desired_raw=desired_raw,
        projects=projects,
        keep_plan=keep_plan,
        enabled=enabled,
        active_spinner=active_spinner,
        op_id=op_id,
        fresh_ai_launch=fresh_ai_launch,
        launch_transport=launch_transport,
    )


def _create_feature_worktrees(self: Any, *, feature: str, count: int, plan_file: str) -> str | None:
    return _planning_runtime_bridge(self).create_feature_worktrees(feature=feature, count=count, plan_file=plan_file)


def _create_feature_worktrees_result(
    self: Any,
    *,
    feature: str,
    count: int,
    plan_file: str,
    created_for_fresh_ai_launch: bool = False,
    launch_transport: str = "",
) -> PlanWorktreeSyncResult:
    return _planning_runtime_bridge(self).create_feature_worktrees_result(
        feature=feature,
        count=count,
        plan_file=plan_file,
        created_for_fresh_ai_launch=created_for_fresh_ai_launch,
        launch_transport=launch_transport,
    )


def _worktree_add_failure(self: Any, *, feature: str, iteration: str, target: Path, result: object) -> str | None:
    return _planning_runtime_bridge(self).worktree_add_failure(
        feature=feature,
        iteration=iteration,
        target=target,
        result=result,
    )


def _recover_partial_worktree_creation(
    self: Any,
    *,
    feature: str,
    iteration: str,
    target: Path,
    result: object,
) -> bool:
    return _planning_runtime_bridge(self).recover_partial_worktree_creation(
        feature=feature,
        iteration=iteration,
        target=target,
        result=result,
    )


def _worktree_target_created(target: Path) -> bool:
    return _worktree_target_created_impl(target)


def _run_worktree_add(self: Any, *, feature: str, iteration: str, target: Path, env: Mapping[str, str]) -> object:
    return _planning_runtime_bridge(self).run_worktree_add(
        feature=feature,
        iteration=iteration,
        target=target,
        env=env,
    )


def _worktree_branch_name(*, feature: str, iteration: str) -> str:
    return _worktree_branch_name_impl(feature=feature, iteration=iteration)


def _worktree_branch_exists(self: Any, *, branch_name: str) -> bool:
    return _worktree_branch_exists_impl(
        branch_name=branch_name,
        git_command_output=lambda args: _git_command_output(self, args),
    )


def _worktree_start_point(self: Any) -> str | None:
    return _worktree_start_point_impl(
        provenance=_build_worktree_provenance(self) or {},
        git_command_output=lambda args: _git_command_output(self, args),
    )


def _setup_worktree_placeholder_fallback_enabled(self: Any) -> bool:
    return _setup_worktree_placeholder_fallback_enabled_impl(env=self.env, config_raw=self.config.raw)


def _worktree_git_hooks_policy(self: Any) -> str:
    return _worktree_git_hooks_policy_impl(self)


def _worktree_git_hooks_disabled(self: Any) -> bool:
    return _worktree_git_hooks_disabled_impl(self)


def _write_worktree_provenance(
    self: Any,
    *,
    target: Path,
    plan_file: str | None = None,
    created_for_fresh_ai_launch: bool = False,
    launch_transport: str = "",
) -> None:
    _write_worktree_provenance_impl(
        self,
        target=target,
        plan_file=plan_file,
        created_for_fresh_ai_launch=created_for_fresh_ai_launch,
        launch_transport=launch_transport,
    )


def _link_repo_local_shared_artifacts(self: Any, *, target: Path) -> None:
    _link_repo_local_shared_artifacts_impl(repo_root=self.config.base_dir, target=target)


def _prepare_worktree_code_intelligence(self: Any, *, target: Path) -> None:
    _prepare_worktree_code_intelligence_impl(
        self,
        target=target,
        trees_root_for_worktree=_trees_root_for_worktree,
    )


def _build_worktree_provenance(
    self: Any,
    *,
    plan_file: str | None = None,
    created_for_fresh_ai_launch: bool = False,
    launch_transport: str = "",
) -> dict[str, object] | None:
    return _build_worktree_provenance_impl(
        self,
        plan_file=plan_file,
        created_for_fresh_ai_launch=created_for_fresh_ai_launch,
        launch_transport=launch_transport,
    )


def _resolve_branch_ref(self: Any, *, source_branch: str) -> str:
    return _resolve_branch_ref_impl(self, source_branch=source_branch)


def _detect_default_branch(self: Any) -> str:
    return _detect_default_branch_impl(self)


def _git_command_output(self: Any, args: list[str]) -> str:
    return _git_command_output_impl(self, args)


def _seed_main_task_from_plan(*, target: Path, plan_path: Path) -> None:
    _seed_main_task_from_plan_impl(target=target, plan_path=plan_path)


def _delete_feature_worktrees(
    self: Any,
    *,
    feature: str,
    candidates: list[tuple[str, Path]],
    remove_count: int,
) -> str | None:
    return _planning_runtime_bridge(self).delete_feature_worktrees(
        feature=feature,
        candidates=candidates,
        remove_count=remove_count,
    )


def _active_fresh_ai_worktree_protection_reason(self: Any, *, name: str, root: Path) -> str:
    return _active_fresh_ai_worktree_protection_reason_impl(self, name=name, root=root)


_fresh_ai_launch_marker_is_fresh = _fresh_ai_launch_marker_is_fresh_impl
_read_worktree_provenance = _read_worktree_provenance_impl


def _cleanup_empty_feature_root(self: Any, *, feature: str) -> None:
    _cleanup_empty_feature_root_impl(
        preferred_tree_root_for_feature=self._preferred_tree_root_for_feature,
        feature=feature,
    )


def _move_plan_to_done(self: Any, plan_file: str) -> None:
    _planning_runtime_bridge(self).move_plan_to_done(plan_file)


def _feature_project_candidates(
    self: Any,
    *,
    projects: list[tuple[str, Path]],
    feature: str,
) -> list[tuple[str, Path]]:
    return _feature_project_candidates_impl(projects=projects, feature=feature)


_project_sort_key_for_feature = _project_sort_key_for_feature_impl
_next_available_iteration = _next_available_iteration_impl
_setup_worktree_requested = _setup_worktree_requested_impl
