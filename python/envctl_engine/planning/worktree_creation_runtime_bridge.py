from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.models import PlanWorktreeSyncResult
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
from envctl_engine.planning.worktree_main_task import seed_main_task_from_plan
from envctl_engine.planning.worktree_provenance import build_worktree_provenance, git_command_output


@dataclass(slots=True)
class WorktreeCreationRuntimeBridge:
    """Wires runtime collaborators into worktree creation owner functions."""

    runtime: Any
    process_runtime_factory: Callable[[Any], Any]
    link_repo_local_shared_artifacts: Callable[..., None]
    prepare_worktree_code_intelligence: Callable[..., None]
    write_worktree_provenance: Callable[..., None]

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
