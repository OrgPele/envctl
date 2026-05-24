from __future__ import annotations

import sys
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from envctl_engine.actions.actions_worktree import delete_worktree_path
from envctl_engine.planning.worktree_creation_commands import (
    run_worktree_add as _run_worktree_add_impl,
    worktree_branch_exists as _worktree_branch_exists_impl,
    worktree_branch_name as _worktree_branch_name_impl,
    worktree_start_point as _worktree_start_point_impl,
)
from envctl_engine.planning.worktree_creation_flow import (
    create_feature_worktrees as _create_feature_worktrees_flow,
    create_feature_worktrees_result as _create_feature_worktrees_result_flow,
    create_single_worktree as _create_single_worktree_flow,
)
from envctl_engine.planning.worktree_identity import worktree_project_name as _worktree_project_name_impl
from envctl_engine.planning.worktree_creation_recovery import (
    recover_partial_worktree_creation as _recover_partial_worktree_creation_impl,
    setup_worktree_placeholder_fallback_enabled as _setup_worktree_placeholder_fallback_enabled_impl,
    worktree_add_failure as _worktree_add_failure_impl,
    worktree_target_created as _worktree_target_created_impl,
)
from envctl_engine.planning.worktree_git_hooks import (
    worktree_git_hooks_disabled as _worktree_git_hooks_disabled_impl,
    worktree_git_hooks_policy as _worktree_git_hooks_policy_impl,
)
from envctl_engine.planning.worktree_main_task import (
    move_plan_to_done as _move_plan_to_done_impl,
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
from envctl_engine.planning.worktree_plan_project_selection import (
    select_plan_projects as _select_plan_projects_impl,
)
from envctl_engine.planning.worktree_prompt_selection import (
    prompt_planning_selection as _prompt_planning_selection_impl,
)
from envctl_engine.planning.worktree_planning_menu import (
    run_planning_selection_menu as _run_planning_selection_menu_impl,
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
    apply_multi_setup_entry as _apply_multi_setup_entry_impl,
    apply_single_setup_entry as _apply_single_setup_entry_impl,
    coerce_setup_entries as _coerce_setup_entries_impl,
    resolve_included_setup_worktrees as _resolve_included_setup_worktrees_impl,
)
from envctl_engine.planning.worktree_setup_coordinator import (
    apply_setup_worktree_selection as _apply_setup_worktree_selection_impl,
)
from envctl_engine.planning.worktree_spinner_support import (
    worktree_spinner_fail as _worktree_spinner_fail_impl,
    worktree_spinner_finish as _worktree_spinner_finish_impl,
    worktree_spinner_policy as _worktree_spinner_policy_impl,
    worktree_spinner_start as _worktree_spinner_start_impl,
    worktree_spinner_stop as _worktree_spinner_stop_impl,
    worktree_spinner_update as _worktree_spinner_update_impl,
)
from envctl_engine.planning.worktree_sync_deletion import (
    delete_feature_worktrees as _delete_feature_worktrees_impl,
)
from envctl_engine.planning.worktree_sync_orchestration import (
    sync_plan_worktrees_from_plan_counts as _sync_plan_worktrees_from_plan_counts_impl,
    sync_single_plan_worktree_target as _sync_single_plan_worktree_target_impl,
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
from envctl_engine.planning.plan_agent.models import (
    PlanSelectionResult,
    PlanWorktreeSyncResult,
)
from envctl_engine.planning.protocols import ProjectContextLike
from envctl_engine.runtime.command_router import Route
from envctl_engine.planning import (
    discover_tree_projects,
)
from envctl_engine.ui.spinner_service import SpinnerPolicy
from envctl_engine.ui.textual.screens.planning_selector import select_planning_counts_textual


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
    return _create_single_worktree_flow(
        feature=feature,
        iteration=iteration,
        preferred_tree_root_for_feature=self._preferred_tree_root_for_feature,
        command_env=self._command_env,
        run_worktree_add=lambda **kwargs: _run_worktree_add(self, **kwargs),
        recover_partial_worktree_creation=lambda **kwargs: _recover_partial_worktree_creation(self, **kwargs),
        link_repo_local_shared_artifacts=lambda **kwargs: _link_repo_local_shared_artifacts(self, **kwargs),
        prepare_worktree_code_intelligence=lambda **kwargs: _prepare_worktree_code_intelligence(self, **kwargs),
        write_worktree_provenance=lambda **kwargs: _write_worktree_provenance(self, **kwargs),
        worktree_add_failure=self._worktree_add_failure,
    )


def _apply_setup_worktree_selection(
    self: Any, route: Route, project_contexts: list[ProjectContextLike]
) -> list[ProjectContextLike]:
    return _apply_setup_worktree_selection_impl(
        route=route,
        project_contexts=project_contexts,
        setup_worktree_requested=self._setup_worktree_requested,
        env=getattr(self, "env", {}),
        emit=getattr(self, "_emit", None),
        coerce_setup_entries=self._coerce_setup_entries,
        apply_multi_setup_entry=lambda **kwargs: _apply_multi_setup_entry(self, **kwargs),
        apply_single_setup_entry=lambda **kwargs: _apply_single_setup_entry(self, **kwargs),
        resolve_included_setup_worktrees=_resolve_included_setup_worktrees_impl,
        contexts_from_raw_projects=self._contexts_from_raw_projects,
    )


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
    return _apply_multi_setup_entry_impl(
        feature=feature,
        count_raw=count_raw,
        raw_projects=raw_projects,
        feature_project_candidates=self._feature_project_candidates,
        update=lambda message: _worktree_spinner_update(
            self,
            enabled=enabled,
            active_spinner=active_spinner,
            op_id=op_id,
            message=message,
        ),
        create_feature_worktrees=self._create_feature_worktrees,
        discover_tree_projects=lambda: discover_tree_projects(self.config.base_dir, self.config.trees_dir_name),
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
    return _apply_single_setup_entry_impl(
        feature=feature,
        iteration_raw=iteration_raw,
        raw_projects=raw_projects,
        preferred_tree_root_for_feature=self._preferred_tree_root_for_feature,
        trees_root_for_worktree=self._trees_root_for_worktree,
        delete_worktree=lambda **kwargs: (
            (result := delete_worktree_path(**kwargs)).success,
            result.message,
        ),
        create_single_worktree=self._create_single_worktree,
        discover_tree_projects=lambda: discover_tree_projects(self.config.base_dir, self.config.trees_dir_name),
        update=lambda message: _worktree_spinner_update(
            self,
            enabled=enabled,
            active_spinner=active_spinner,
            op_id=op_id,
            message=message,
        ),
        repo_root=self.config.base_dir,
        process_runner=self.process_runner,
        setup_worktree_existing=setup_worktree_existing,
        setup_worktree_recreate=setup_worktree_recreate,
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
    setattr(self, "_last_plan_selection_result", PlanSelectionResult(raw_projects=[], selected_contexts=[]))
    selection_result = _select_plan_projects_impl(
        route=route,
        project_contexts=project_contexts,
        config=self.config,
        env=getattr(self, "env", {}),
        emit=self._emit,
        contexts_from_raw_projects=self._contexts_from_raw_projects,
        duplicate_project_context_error=self._duplicate_project_context_error,
        planning_keep_plan_enabled=self._planning_keep_plan_enabled,
        prompt_planning_selection=self._prompt_planning_selection,
        sync_plan_worktrees_from_plan_counts=self._sync_plan_worktrees_from_plan_counts,
    )
    setattr(self, "_last_plan_selection_result", selection_result)
    return selection_result.selected_contexts


def _prompt_planning_selection(
    self: Any,
    planning_files: list[str],
    raw_projects: list[tuple[str, Path]],
    *,
    persist_memory: bool = True,
) -> dict[str, int]:
    return _prompt_planning_selection_impl(
        planning_files=planning_files,
        raw_projects=raw_projects,
        initial_plan_selected_counts=self._initial_plan_selected_counts,
        run_planning_selection_menu=self._run_planning_selection_menu,
        save_plan_selection_memory=self._save_plan_selection_memory,
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
    return _run_planning_selection_menu_impl(
        planning_files=planning_files,
        selected_counts=selected_counts,
        existing_counts=existing_counts,
        flush_pending_interactive_input=self._flush_pending_interactive_input,
        emit=getattr(self, "_emit", None),
        select_planning_counts=select_planning_counts_textual,
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
    return _sync_plan_worktrees_from_plan_counts_impl(
        plan_counts=plan_counts,
        raw_projects=raw_projects,
        keep_plan=keep_plan,
        fresh_ai_launch=fresh_ai_launch,
        launch_transport=launch_transport,
        ensure_trees_root=lambda: (self.config.base_dir / self.config.trees_dir_name).mkdir(
            parents=True,
            exist_ok=True,
        ),
        env=getattr(self, "env", {}),
        emit=getattr(self, "_emit", None),
        sync_single_plan_worktree_target=lambda **kwargs: _sync_single_plan_worktree_target(self, **kwargs),
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
    return _sync_single_plan_worktree_target_impl(
        plan_file=plan_file,
        desired_raw=desired_raw,
        projects=projects,
        keep_plan=keep_plan,
        fresh_ai_launch=fresh_ai_launch,
        launch_transport=launch_transport,
        enabled=enabled,
        active_spinner=active_spinner,
        op_id=op_id,
        feature_project_candidates=self._feature_project_candidates,
        create_feature_worktrees_result=lambda **kwargs: _create_feature_worktrees_result(self, **kwargs),
        discover_tree_projects=lambda: discover_tree_projects(self.config.base_dir, self.config.trees_dir_name),
        delete_feature_worktrees=self._delete_feature_worktrees,
        cleanup_empty_feature_root=self._cleanup_empty_feature_root,
        move_plan_to_done=self._move_plan_to_done,
        render_planning_path=lambda *, plan_file, interactive_tty: _render_planning_path(
            self,
            absolute_path=self._planning_root() / plan_file,
            display_text=plan_file,
            interactive_tty=interactive_tty,
        ),
        update=lambda **kwargs: _worktree_spinner_update(self, **kwargs),
        output=print,
    )


def _create_feature_worktrees(self: Any, *, feature: str, count: int, plan_file: str) -> str | None:
    return _create_feature_worktrees_flow(
        feature=feature,
        count=count,
        plan_file=plan_file,
        create_feature_worktrees_result=lambda **kwargs: _create_feature_worktrees_result(self, **kwargs),
    )


def _create_feature_worktrees_result(
    self: Any,
    *,
    feature: str,
    count: int,
    plan_file: str,
    created_for_fresh_ai_launch: bool = False,
    launch_transport: str = "",
) -> PlanWorktreeSyncResult:
    return _create_feature_worktrees_result_flow(
        feature=feature,
        count=count,
        plan_file=plan_file,
        created_for_fresh_ai_launch=created_for_fresh_ai_launch,
        launch_transport=launch_transport,
        preferred_tree_root_for_feature=self._preferred_tree_root_for_feature,
        planning_root=self._planning_root,
        command_env=self._command_env,
        run_worktree_add=lambda **kwargs: _run_worktree_add(self, **kwargs),
        recover_partial_worktree_creation=lambda **kwargs: _recover_partial_worktree_creation(self, **kwargs),
        write_worktree_provenance=lambda **kwargs: _write_worktree_provenance(self, **kwargs),
        prepare_worktree_code_intelligence=lambda **kwargs: _prepare_worktree_code_intelligence(self, **kwargs),
        worktree_add_failure=self._worktree_add_failure,
        seed_main_task_from_plan=_seed_main_task_from_plan,
        next_available_iteration=self._next_available_iteration,
        worktree_project_name=_worktree_project_name_impl,
        env=getattr(self, "env", {}),
        config_raw=getattr(self.config, "raw", {}),
    )


def _worktree_add_failure(self: Any, *, feature: str, iteration: str, target: Path, result: object) -> str | None:
    return _worktree_add_failure_impl(
        feature=feature,
        iteration=iteration,
        target=target,
        result=result,
        placeholder_fallback_enabled=self._setup_worktree_placeholder_fallback_enabled(),
        command_result_error_text=lambda command_result: self._command_result_error_text(result=command_result),
        link_repo_local_shared_artifacts=lambda linked_target: _link_repo_local_shared_artifacts(
            self,
            target=linked_target,
        ),
        emit=self._emit,
    )


def _recover_partial_worktree_creation(
    self: Any,
    *,
    feature: str,
    iteration: str,
    target: Path,
    result: object,
) -> bool:
    return _recover_partial_worktree_creation_impl(
        git_hooks_disabled=_worktree_git_hooks_disabled(self),
        target=target,
        feature=feature,
        iteration=iteration,
        result=result,
        command_result_error_text=lambda command_result: self._command_result_error_text(result=command_result),
        emit=self._emit,
    )


def _worktree_target_created(target: Path) -> bool:
    return _worktree_target_created_impl(target)


def _run_worktree_add(self: Any, *, feature: str, iteration: str, target: Path, env: Mapping[str, str]) -> object:
    return _run_worktree_add_impl(
        repo_root=self.config.base_dir,
        feature=feature,
        iteration=iteration,
        target=target,
        env=env,
        git_hooks_disabled=_worktree_git_hooks_disabled(self),
        branch_exists=lambda branch_name: _worktree_branch_exists(self, branch_name=branch_name),
        start_point=lambda: _worktree_start_point(self),
        run=self.process_runner.run,
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
    return _delete_feature_worktrees_impl(
        feature=feature,
        candidates=candidates,
        remove_count=remove_count,
        project_sort_key_for_feature=self._project_sort_key_for_feature,
        active_protection_reason=lambda *, name, root: _active_fresh_ai_worktree_protection_reason(
            self,
            name=name,
            root=root,
        ),
        blast_worktree_before_delete=getattr(self, "_blast_worktree_before_delete", None),
        delete_worktree=delete_worktree_path,
        repo_root=self.config.base_dir,
        trees_root_for_worktree=self._trees_root_for_worktree,
        process_runner=self.process_runner,
        emit=self._emit,
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
    _move_plan_to_done_impl(
        plan_file=plan_file,
        planning_root=self._planning_root(),
        planning_done_root=self._planning_done_root(),
        render_path=lambda *, absolute_path, display_text: _render_planning_path(
            self,
            absolute_path=absolute_path,
            display_text=display_text,
        ),
        emit_message=print,
    )


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
