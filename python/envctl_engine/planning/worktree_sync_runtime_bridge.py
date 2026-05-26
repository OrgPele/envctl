from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import PlanWorktreeSyncResult
from envctl_engine.planning.worktree_sync_deletion import delete_feature_worktrees
from envctl_engine.planning.worktree_sync_orchestration import (
    sync_plan_worktrees_from_plan_counts,
    sync_single_plan_worktree_target,
)


@dataclass(slots=True)
class WorktreeSyncRuntimeBridge:
    """Wires runtime collaborators into plan-worktree sync/delete owners."""

    runtime: Any
    discover_tree_projects: Callable[[Path, str], list[tuple[str, Path]]]
    delete_worktree_path: Callable[..., Any]
    process_runtime_factory: Callable[[Any], Any]
    render_planning_path: Callable[..., str]
    update_spinner: Callable[..., None]
    output: Callable[..., None]
    create_feature_worktrees_result: Callable[..., PlanWorktreeSyncResult]

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
