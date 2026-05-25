from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Any

import envctl_engine.actions.action_commit_support as commit_support
import envctl_engine.actions.action_pr_workflow_support as pr_workflow_support
import envctl_engine.actions.action_review_workflow_support as review_workflow_support
import envctl_engine.actions.action_ship_support as ship_support
from envctl_engine.actions.action_git_state_support import DirtyWorktreeReport


@dataclass(frozen=True, slots=True)
class ProjectActionGitWorkflowDependencies:
    resolve_git_root_fn: Callable[[Path, Path], Path]
    which_fn: Callable[[str], str | None]
    git_output_fn: Callable[[Path, list[str]], str]
    run_git_fn: Callable[[Path, list[str]], subprocess.CompletedProcess[str]]
    print_error_fn: Callable[[str, subprocess.CompletedProcess[str]], None]
    print_process_output_fn: Callable[[subprocess.CompletedProcess[str]], None]
    run_process_fn: Callable[..., subprocess.CompletedProcess[str]]

    @property
    def git_available(self) -> bool:
        return self.which_fn("git") is not None

    @property
    def gh_path(self) -> str | None:
        return self.which_fn("gh")


@dataclass(frozen=True, slots=True)
class ProjectActionCommitWorkflowDependencies:
    partition_envctl_protected_paths_fn: Callable[..., Any]
    ordered_unique_paths_fn: Callable[..., list[str]]


@dataclass(frozen=True, slots=True)
class ProjectActionPullRequestWorkflowDependencies:
    resolve_base_branch_fn: Callable[[Any, Path], str]
    existing_pr_url_fn: Callable[[Path, str], str]
    probe_dirty_worktree_fn: Callable[[Path, Path, str], DirtyWorktreeReport]
    run_commit_action_fn: Callable[[Any], int]
    pr_title_fn: Callable[[Any, Path, str], str]
    pr_body_fn: Callable[[Any, Path, str, str], str]
    write_pr_body_file_fn: Callable[[str], Path]
    run_pr_action_fn: Callable[[Any], int]
    github_pr_checks_fn: ship_support.GithubPrChecks


@dataclass(frozen=True, slots=True)
class ProjectActionReviewWorkflowDependencies:
    resolve_analyze_mode_fn: Callable[[Any], str]
    resolve_original_plan_fn: Callable[[Any], Any]
    resolve_review_base_fn: Callable[[Any, Path], Any]
    analysis_iterations_fn: Callable[[Any, str], list[str]]
    run_analyze_helper_fn: Callable[[Any, Path, list[str], str, str, Any, Any], int]
    tree_diffs_output_path_fn: Callable[[Any, str, str], Path]
    original_plan_markdown_lines_fn: Callable[[Any], list[str]]
    sanitize_label_fn: Callable[[str], str]


@dataclass(frozen=True, slots=True)
class ProjectActionWorkflowRunner:
    """Owns workflow-level dependency wiring for project actions."""

    git: ProjectActionGitWorkflowDependencies
    commit: ProjectActionCommitWorkflowDependencies
    pull_request: ProjectActionPullRequestWorkflowDependencies
    review: ProjectActionReviewWorkflowDependencies

    @property
    def git_available(self) -> bool:
        return self.git.git_available

    @property
    def gh_path(self) -> str | None:
        return self.git.gh_path

    @property
    def probe_dirty_worktree_fn(self) -> Callable[[Path, Path, str], DirtyWorktreeReport]:
        return self.pull_request.probe_dirty_worktree_fn

    @property
    def analysis_iterations_fn(self) -> Callable[[Any, str], list[str]]:
        return self.review.analysis_iterations_fn

    @property
    def run_analyze_helper_fn(self) -> Callable[[Any, Path, list[str], str, str, Any, Any], int]:
        return self.review.run_analyze_helper_fn

    @property
    def original_plan_markdown_lines_fn(self) -> Callable[[Any], list[str]]:
        return self.review.original_plan_markdown_lines_fn

    def run_commit_action(self, context: Any) -> int:
        return commit_support.run_commit_workflow(
            context,
            resolve_git_root=self.git.resolve_git_root_fn,
            git_available=self.git_available,
            git_output=self.git.git_output_fn,
            run_git=self.git.run_git_fn,
            print_error=self.git.print_error_fn,
            partition_envctl_protected_paths=self.commit.partition_envctl_protected_paths_fn,
            ordered_unique_paths=self.commit.ordered_unique_paths_fn,
        )

    def run_pr_action(self, context: Any) -> int:
        return pr_workflow_support.run_pr_workflow(
            context,
            resolve_git_root_fn=self.git.resolve_git_root_fn,
            git_available=self.git_available,
            git_output_fn=self.git.git_output_fn,
            resolve_base_branch_fn=self.pull_request.resolve_base_branch_fn,
            existing_pr_url_fn=self.pull_request.existing_pr_url_fn,
            probe_dirty_worktree_fn=self.pull_request.probe_dirty_worktree_fn,
            run_commit_action_fn=self.pull_request.run_commit_action_fn,
            pr_title_fn=self.pull_request.pr_title_fn,
            pr_body_fn=self.pull_request.pr_body_fn,
            write_pr_body_file_fn=self.pull_request.write_pr_body_file_fn,
            print_process_output_fn=self.git.print_process_output_fn,
            gh_path=self.gh_path,
            run_process_fn=self.git.run_process_fn,
        )

    def run_ship_action(self, context: Any) -> int:
        return ship_support.run_ship_workflow(
            context,
            resolve_git_root=self.git.resolve_git_root_fn,
            git_available=self.git_available,
            git_output=self.git.git_output_fn,
            run_git=self.git.run_git_fn,
            resolve_base_branch=self.pull_request.resolve_base_branch_fn,
            resolve_base_ref=self._resolve_base_ref,
            run_commit_action=self.pull_request.run_commit_action_fn,
            run_pr_action=self.pull_request.run_pr_action_fn,
            probe_dirty_worktree=self._probe_dirty_worktree_for_ship,
            existing_pr_url=self.pull_request.existing_pr_url_fn,
            partition_envctl_protected_paths=self.commit.partition_envctl_protected_paths_fn,
            ordered_unique_paths=self.commit.ordered_unique_paths_fn,
            github_pr_checks=self.pull_request.github_pr_checks_fn,
        )

    def run_review_action(self, context: Any) -> int:
        return review_workflow_support.run_review_workflow(
            context,
            resolve_git_root_fn=self.git.resolve_git_root_fn,
            git_available=self.git_available,
            git_output_fn=self.git.git_output_fn,
            resolve_analyze_mode_fn=self.review.resolve_analyze_mode_fn,
            resolve_original_plan_fn=self.review.resolve_original_plan_fn,
            resolve_review_base_fn=self.review.resolve_review_base_fn,
            analysis_iterations_fn=self.review.analysis_iterations_fn,
            run_analyze_helper_fn=self.review.run_analyze_helper_fn,
            tree_diffs_output_path_fn=self.review.tree_diffs_output_path_fn,
            original_plan_markdown_lines_fn=self.review.original_plan_markdown_lines_fn,
            sanitize_label_fn=self.review.sanitize_label_fn,
        )

    def _resolve_base_ref(self, git_root: Path, base_branch: str) -> str:
        from envctl_engine.actions.action_pr_message_support import pr_base_ref

        return pr_base_ref(git_root, base_branch, git_output=self.git.git_output_fn)

    def _probe_dirty_worktree_for_ship(
        self,
        project_root: Path,
        repo_root: Path,
        *,
        project_name: str = "",
    ) -> DirtyWorktreeReport:
        return self.probe_dirty_worktree_fn(project_root, repo_root, project_name)
