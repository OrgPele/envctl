from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import PlanSelectionResult, PlanWorktreeSyncResult
from envctl_engine.planning.protocols import ProjectContextLike
from envctl_engine.planning.worktree_code_intelligence import prepare_worktree_code_intelligence
from envctl_engine.planning.worktree_creation_commands import (
    run_worktree_add,
    worktree_branch_exists,
    worktree_start_point,
)
from envctl_engine.planning.worktree_creation_flow import (
    create_feature_worktrees,
    create_feature_worktrees_result,
    create_single_worktree,
)
from envctl_engine.planning.worktree_creation_recovery import (
    recover_partial_worktree_creation,
    worktree_add_failure,
)
from envctl_engine.planning.worktree_git_hooks import worktree_git_hooks_disabled
from envctl_engine.planning.worktree_identity import worktree_project_name
from envctl_engine.planning.worktree_main_task import move_plan_to_done
from envctl_engine.planning.worktree_main_task import seed_main_task_from_plan
from envctl_engine.planning.worktree_plan_project_selection import select_plan_projects
from envctl_engine.planning.worktree_path_support import render_planning_path
from envctl_engine.planning.worktree_prompt_selection import prompt_planning_selection
from envctl_engine.planning.worktree_provenance import (
    build_worktree_provenance,
    git_command_output,
    write_worktree_provenance,
)
from envctl_engine.planning.worktree_shared_artifacts import link_repo_local_shared_artifacts
from envctl_engine.planning.worktree_setup_coordinator import apply_setup_worktree_selection
from envctl_engine.planning.worktree_setup_entries import (
    apply_multi_setup_entry,
    apply_single_setup_entry,
    resolve_included_setup_worktrees,
)
from envctl_engine.planning.worktree_spinner_support import worktree_spinner_update
from envctl_engine.planning.worktree_sync_deletion import delete_feature_worktrees
from envctl_engine.planning.worktree_sync_orchestration import (
    sync_plan_worktrees_from_plan_counts,
    sync_single_plan_worktree_target,
)
from envctl_engine.runtime.command_router import Route


@dataclass(slots=True)
class PlanningRuntimeBridge:
    """Wires runtime collaborators into pure planning worktree owner modules."""

    runtime: Any
    delete_worktree_path: Callable[..., Any]
    discover_tree_projects: Callable[[Path, str], list[tuple[str, Path]]]
    process_runtime_factory: Callable[[Any], Any]
    select_planning_counts: Callable[..., Any]
    output: Callable[..., None]

    def render_planning_path(
        self,
        *,
        absolute_path: Path,
        display_text: str,
        interactive_tty: bool | None = None,
    ) -> str:
        return render_planning_path(
            absolute_path=absolute_path,
            display_text=display_text,
            env=getattr(self.runtime, "env", {}),
            stream=sys.stdout,
            interactive_tty=interactive_tty,
        )

    def update_spinner(
        self,
        *,
        enabled: bool,
        active_spinner: Any,
        op_id: str,
        message: str,
        terminal_message: str | None = None,
    ) -> None:
        worktree_spinner_update(
            self.runtime,
            enabled=enabled,
            active_spinner=active_spinner,
            op_id=op_id,
            message=message,
            terminal_message=terminal_message,
        )

    def link_repo_local_shared_artifacts(self, *, target: Path) -> None:
        link_repo_local_shared_artifacts(repo_root=self.runtime.config.base_dir, target=target)

    def prepare_worktree_code_intelligence(self, *, target: Path) -> None:
        from envctl_engine.planning.worktree_path_support import trees_root_for_worktree

        def runtime_trees_root_for_worktree(_runtime: Any, worktree_root: Path) -> Path:
            return trees_root_for_worktree(
                base_dir=self.runtime.config.base_dir,
                trees_dir_name=getattr(self.runtime.config, "trees_dir_name", "trees"),
                worktree_root=worktree_root,
            )

        prepare_worktree_code_intelligence(
            self.runtime,
            target=target,
            trees_root_for_worktree=runtime_trees_root_for_worktree,
        )

    def write_worktree_provenance(
        self,
        *,
        target: Path,
        plan_file: str | None = None,
        created_for_fresh_ai_launch: bool = False,
        launch_transport: str = "",
    ) -> None:
        write_worktree_provenance(
            self.runtime,
            target=target,
            plan_file=plan_file,
            created_for_fresh_ai_launch=created_for_fresh_ai_launch,
            launch_transport=launch_transport,
        )

    def create_single_worktree(self, *, feature: str, iteration: str) -> str | None:
        runtime = self.runtime
        return create_single_worktree(
            feature=feature,
            iteration=iteration,
            preferred_tree_root_for_feature=runtime._preferred_tree_root_for_feature,
            command_env=runtime._command_env,
            run_worktree_add=lambda **kwargs: self.run_worktree_add(**kwargs),
            recover_partial_worktree_creation=lambda **kwargs: self.recover_partial_worktree_creation(**kwargs),
            link_repo_local_shared_artifacts=lambda **kwargs: self.link_repo_local_shared_artifacts(**kwargs),
            prepare_worktree_code_intelligence=lambda **kwargs: self.prepare_worktree_code_intelligence(**kwargs),
            write_worktree_provenance=lambda **kwargs: self.write_worktree_provenance(**kwargs),
            worktree_add_failure=runtime._worktree_add_failure,
        )

    def apply_setup_worktree_selection(
        self,
        route: Route,
        project_contexts: list[ProjectContextLike],
    ) -> list[ProjectContextLike]:
        runtime = self.runtime
        return apply_setup_worktree_selection(
            route=route,
            project_contexts=project_contexts,
            setup_worktree_requested=runtime._setup_worktree_requested,
            env=getattr(runtime, "env", {}),
            emit=getattr(runtime, "_emit", None),
            coerce_setup_entries=runtime._coerce_setup_entries,
            apply_multi_setup_entry=lambda **kwargs: self.apply_multi_setup_entry(**kwargs),
            apply_single_setup_entry=lambda **kwargs: self.apply_single_setup_entry(**kwargs),
            resolve_included_setup_worktrees=resolve_included_setup_worktrees,
            contexts_from_raw_projects=runtime._contexts_from_raw_projects,
        )

    def apply_multi_setup_entry(
        self,
        *,
        feature: str,
        count_raw: str,
        raw_projects: list[tuple[str, Path]],
        enabled: bool,
        active_spinner: Any,
        op_id: str,
    ) -> tuple[list[tuple[str, Path]], set[str]]:
        runtime = self.runtime
        return apply_multi_setup_entry(
            feature=feature,
            count_raw=count_raw,
            raw_projects=raw_projects,
            feature_project_candidates=runtime._feature_project_candidates,
            update=lambda message: self.update_spinner(
                enabled=enabled,
                active_spinner=active_spinner,
                op_id=op_id,
                message=message,
            ),
            create_feature_worktrees=runtime._create_feature_worktrees,
            discover_tree_projects=lambda: self.discover_tree_projects(
                runtime.config.base_dir,
                runtime.config.trees_dir_name,
            ),
        )

    def apply_single_setup_entry(
        self,
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
        runtime = self.runtime
        return apply_single_setup_entry(
            feature=feature,
            iteration_raw=iteration_raw,
            raw_projects=raw_projects,
            preferred_tree_root_for_feature=runtime._preferred_tree_root_for_feature,
            trees_root_for_worktree=runtime._trees_root_for_worktree,
            delete_worktree=lambda **kwargs: (
                (result := self.delete_worktree_path(**kwargs)).success,
                result.message,
            ),
            create_single_worktree=runtime._create_single_worktree,
            discover_tree_projects=lambda: self.discover_tree_projects(
                runtime.config.base_dir,
                runtime.config.trees_dir_name,
            ),
            update=lambda message: self.update_spinner(
                enabled=enabled,
                active_spinner=active_spinner,
                op_id=op_id,
                message=message,
            ),
            repo_root=runtime.config.base_dir,
            process_runner=self.process_runtime_factory(runtime),
            setup_worktree_existing=setup_worktree_existing,
            setup_worktree_recreate=setup_worktree_recreate,
        )

    def select_plan_projects(
        self,
        route: Route,
        project_contexts: list[ProjectContextLike],
    ) -> list[ProjectContextLike]:
        runtime = self.runtime
        setattr(runtime, "_last_plan_selection_result", PlanSelectionResult(raw_projects=[], selected_contexts=[]))
        selection_result = select_plan_projects(
            route=route,
            project_contexts=project_contexts,
            config=runtime.config,
            env=getattr(runtime, "env", {}),
            emit=runtime._emit,
            contexts_from_raw_projects=runtime._contexts_from_raw_projects,
            duplicate_project_context_error=runtime._duplicate_project_context_error,
            planning_keep_plan_enabled=runtime._planning_keep_plan_enabled,
            prompt_planning_selection=runtime._prompt_planning_selection,
            sync_plan_worktrees_from_plan_counts=runtime._sync_plan_worktrees_from_plan_counts,
        )
        setattr(runtime, "_last_plan_selection_result", selection_result)
        return selection_result.selected_contexts

    def prompt_planning_selection(
        self,
        planning_files: list[str],
        raw_projects: list[tuple[str, Path]],
        *,
        persist_memory: bool = True,
    ) -> dict[str, int]:
        runtime = self.runtime
        return prompt_planning_selection(
            planning_files=planning_files,
            raw_projects=raw_projects,
            initial_plan_selected_counts=runtime._initial_plan_selected_counts,
            run_planning_selection_menu=runtime._run_planning_selection_menu,
            save_plan_selection_memory=runtime._save_plan_selection_memory,
            persist_memory=persist_memory,
        )

    def run_planning_selection_menu(
        self,
        *,
        planning_files: list[str],
        selected_counts: dict[str, int],
        existing_counts: dict[str, int],
    ) -> dict[str, int] | None:
        runtime = self.runtime
        from envctl_engine.planning.worktree_planning_menu import run_planning_selection_menu

        return run_planning_selection_menu(
            planning_files=planning_files,
            selected_counts=selected_counts,
            existing_counts=existing_counts,
            flush_pending_interactive_input=runtime._flush_pending_interactive_input,
            emit=getattr(runtime, "_emit", None),
            select_planning_counts=self.select_planning_counts,
        )

    def sync_plan_worktrees_from_plan_counts(
        self,
        *,
        plan_counts: Mapping[str, int],
        raw_projects: list[tuple[str, Path]],
        keep_plan: bool,
        fresh_ai_launch: bool = False,
        launch_transport: str = "",
    ) -> PlanWorktreeSyncResult:
        runtime = self.runtime
        return sync_plan_worktrees_from_plan_counts(
            plan_counts=plan_counts,
            raw_projects=raw_projects,
            keep_plan=keep_plan,
            fresh_ai_launch=fresh_ai_launch,
            launch_transport=launch_transport,
            ensure_trees_root=lambda: (runtime.config.base_dir / runtime.config.trees_dir_name).mkdir(
                parents=True,
                exist_ok=True,
            ),
            env=getattr(runtime, "env", {}),
            emit=getattr(runtime, "_emit", None),
            sync_single_plan_worktree_target=lambda **kwargs: self.sync_single_plan_worktree_target(**kwargs),
        )

    def sync_single_plan_worktree_target(
        self,
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
        runtime = self.runtime
        return sync_single_plan_worktree_target(
            plan_file=plan_file,
            desired_raw=desired_raw,
            projects=projects,
            keep_plan=keep_plan,
            fresh_ai_launch=fresh_ai_launch,
            launch_transport=launch_transport,
            enabled=enabled,
            active_spinner=active_spinner,
            op_id=op_id,
            feature_project_candidates=runtime._feature_project_candidates,
            create_feature_worktrees_result=lambda **kwargs: self.create_feature_worktrees_result(**kwargs),
            discover_tree_projects=lambda: self.discover_tree_projects(
                runtime.config.base_dir,
                runtime.config.trees_dir_name,
            ),
            delete_feature_worktrees=runtime._delete_feature_worktrees,
            cleanup_empty_feature_root=runtime._cleanup_empty_feature_root,
            move_plan_to_done=runtime._move_plan_to_done,
            render_planning_path=lambda *, plan_file, interactive_tty: self.render_planning_path(
                absolute_path=runtime._planning_root() / plan_file,
                display_text=plan_file,
                interactive_tty=interactive_tty,
            ),
            update=lambda **kwargs: self.update_spinner(**kwargs),
            output=self.output,
        )

    def create_feature_worktrees(self, *, feature: str, count: int, plan_file: str) -> str | None:
        return create_feature_worktrees(
            feature=feature,
            count=count,
            plan_file=plan_file,
            create_feature_worktrees_result=lambda **kwargs: self.create_feature_worktrees_result(**kwargs),
        )

    def create_feature_worktrees_result(
        self,
        *,
        feature: str,
        count: int,
        plan_file: str,
        created_for_fresh_ai_launch: bool = False,
        launch_transport: str = "",
    ) -> PlanWorktreeSyncResult:
        runtime = self.runtime
        return create_feature_worktrees_result(
            feature=feature,
            count=count,
            plan_file=plan_file,
            created_for_fresh_ai_launch=created_for_fresh_ai_launch,
            launch_transport=launch_transport,
            preferred_tree_root_for_feature=runtime._preferred_tree_root_for_feature,
            planning_root=runtime._planning_root,
            command_env=runtime._command_env,
            run_worktree_add=lambda **kwargs: self.run_worktree_add(**kwargs),
            recover_partial_worktree_creation=lambda **kwargs: self.recover_partial_worktree_creation(**kwargs),
            write_worktree_provenance=lambda **kwargs: self.write_worktree_provenance(**kwargs),
            prepare_worktree_code_intelligence=lambda **kwargs: self.prepare_worktree_code_intelligence(**kwargs),
            worktree_add_failure=runtime._worktree_add_failure,
            seed_main_task_from_plan=seed_main_task_from_plan,
            next_available_iteration=runtime._next_available_iteration,
            worktree_project_name=worktree_project_name,
            env=getattr(runtime, "env", {}),
            config_raw=getattr(runtime.config, "raw", {}),
        )

    def worktree_add_failure(self, *, feature: str, iteration: str, target: Path, result: object) -> str | None:
        runtime = self.runtime
        return worktree_add_failure(
            feature=feature,
            iteration=iteration,
            target=target,
            result=result,
            placeholder_fallback_enabled=runtime._setup_worktree_placeholder_fallback_enabled(),
            command_result_error_text=lambda command_result: runtime._command_result_error_text(result=command_result),
            link_repo_local_shared_artifacts=lambda linked_target: self.link_repo_local_shared_artifacts(
                target=linked_target
            ),
            emit=runtime._emit,
        )

    def recover_partial_worktree_creation(
        self,
        *,
        feature: str,
        iteration: str,
        target: Path,
        result: object,
    ) -> bool:
        runtime = self.runtime
        return recover_partial_worktree_creation(
            git_hooks_disabled=worktree_git_hooks_disabled(runtime),
            target=target,
            feature=feature,
            iteration=iteration,
            result=result,
            command_result_error_text=lambda command_result: runtime._command_result_error_text(result=command_result),
            emit=runtime._emit,
        )

    def run_worktree_add(self, *, feature: str, iteration: str, target: Path, env: Mapping[str, str]) -> object:
        runtime = self.runtime
        return run_worktree_add(
            repo_root=runtime.config.base_dir,
            feature=feature,
            iteration=iteration,
            target=target,
            env=env,
            git_hooks_disabled=worktree_git_hooks_disabled(runtime),
            branch_exists=lambda branch_name: worktree_branch_exists(
                branch_name=branch_name,
                git_command_output=lambda args: git_command_output(runtime, args),
            ),
            start_point=lambda: worktree_start_point(
                provenance=build_worktree_provenance(runtime) or {},
                git_command_output=lambda args: git_command_output(runtime, args),
            ),
            run=self.process_runtime_factory(runtime).run,
        )

    def delete_feature_worktrees(
        self,
        *,
        feature: str,
        candidates: list[tuple[str, Path]],
        remove_count: int,
    ) -> str | None:
        runtime = self.runtime
        from envctl_engine.planning.worktree_provenance import active_fresh_ai_worktree_protection_reason

        return delete_feature_worktrees(
            feature=feature,
            candidates=candidates,
            remove_count=remove_count,
            project_sort_key_for_feature=runtime._project_sort_key_for_feature,
            active_protection_reason=lambda *, name, root: active_fresh_ai_worktree_protection_reason(
                runtime,
                name=name,
                root=root,
            ),
            blast_worktree_before_delete=getattr(runtime, "_blast_worktree_before_delete", None),
            delete_worktree=self.delete_worktree_path,
            repo_root=runtime.config.base_dir,
            trees_root_for_worktree=runtime._trees_root_for_worktree,
            process_runner=self.process_runtime_factory(runtime),
            emit=runtime._emit,
        )

    def move_plan_to_done(self, plan_file: str) -> None:
        runtime = self.runtime
        move_plan_to_done(
            plan_file=plan_file,
            planning_root=runtime._planning_root(),
            planning_done_root=runtime._planning_done_root(),
            render_path=lambda *, absolute_path, display_text: self.render_planning_path(
                absolute_path=absolute_path,
                display_text=display_text,
            ),
            emit_message=self.output,
        )
