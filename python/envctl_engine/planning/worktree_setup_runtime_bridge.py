from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from envctl_engine.planning.protocols import ProjectContextLike
from envctl_engine.planning.worktree_setup_coordinator import apply_setup_worktree_selection
from envctl_engine.planning.worktree_setup_entries import (
    apply_multi_setup_entry,
    apply_single_setup_entry,
    resolve_included_setup_worktrees,
)
from envctl_engine.runtime.command_router import Route


@dataclass(slots=True)
class WorktreeSetupRuntimeBridge:
    """Wires runtime collaborators into setup-worktree owner functions."""

    runtime: Any
    delete_worktree_path: Callable[..., Any]
    discover_tree_projects: Callable[[Path, str], list[tuple[str, Path]]]
    process_runtime_factory: Callable[[Any], Any]
    update_spinner: Callable[..., None]

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
