from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Any

import envctl_engine.actions.action_ship_support as ship_support
from envctl_engine.actions.action_git_state_support import DirtyWorktreeReport
from envctl_engine.actions.action_review_context import ReviewActionContext
from envctl_engine.actions.action_review_base_support import ReviewBaseResolution
from envctl_engine.actions.action_review_original_plan_support import OriginalPlanResolution
from envctl_engine.actions.project_action_workflows import (
    ProjectActionCommitWorkflowDependencies,
    ProjectActionGitWorkflowDependencies,
    ProjectActionPullRequestWorkflowDependencies,
    ProjectActionReviewWorkflowDependencies,
    ProjectActionWorkflowRunner,
)


@dataclass(frozen=True, slots=True)
class ProjectActionWorkflowGitSources:
    resolve_git_root_fn: Callable[[Path, Path], Path]
    which_fn: Callable[[str], str | None]
    git_output_fn: Callable[[Path, list[str]], str]
    run_git_fn: Callable[[Path, list[str]], subprocess.CompletedProcess[str]]
    print_error_fn: Callable[[str, subprocess.CompletedProcess[str]], None]
    print_process_output_fn: Callable[[subprocess.CompletedProcess[str]], None]
    run_process_fn: Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True, slots=True)
class ProjectActionWorkflowCommitSources:
    partition_envctl_protected_paths_fn: Callable[..., Any]
    ordered_unique_paths_fn: Callable[..., list[str]]


@dataclass(frozen=True, slots=True)
class ProjectActionWorkflowPullRequestSources:
    resolve_base_branch_fn: Callable[[Any, Path], str]
    existing_pr_url_fn: Callable[[Path, str], str]
    probe_dirty_worktree_source_fn: Callable[..., DirtyWorktreeReport]
    run_commit_action_fn: Callable[[Any], int]
    pr_title_fn: Callable[[Any, Path, str], str]
    pr_body_fn: Callable[[Any, Path, str, str], str]
    write_pr_body_file_fn: Callable[[str], Path]
    run_pr_action_fn: Callable[[Any], int]
    add_ship_pr_label_fn: Callable[[Any, Path, str], int]
    github_pr_checks_fn: ship_support.GithubPrChecks


@dataclass(frozen=True, slots=True)
class ProjectActionWorkflowReviewSources:
    resolve_analyze_mode_fn: Callable[[ReviewActionContext], str]
    resolve_original_plan_fn: Callable[[ReviewActionContext], OriginalPlanResolution]
    resolve_review_base_fn: Callable[[ReviewActionContext, Path], ReviewBaseResolution]
    analysis_iterations_source_fn: Callable[..., list[str]]
    run_analyze_helper_source_fn: Callable[..., int]
    tree_diffs_output_path_fn: Callable[[ReviewActionContext, str, str], Path]
    original_plan_markdown_lines_source_fn: Callable[..., list[str]]


@dataclass(frozen=True, slots=True)
class ProjectActionWorkflowFactory:
    """Builds project-action workflow runners from grouped compatibility dependencies."""

    git: ProjectActionWorkflowGitSources
    commit: ProjectActionWorkflowCommitSources
    pull_request: ProjectActionWorkflowPullRequestSources
    review: ProjectActionWorkflowReviewSources

    def build(self) -> ProjectActionWorkflowRunner:
        return ProjectActionWorkflowRunner(
            git=ProjectActionGitWorkflowDependencies(
                resolve_git_root_fn=self.git.resolve_git_root_fn,
                which_fn=self.git.which_fn,
                git_output_fn=self.git.git_output_fn,
                run_git_fn=self.git.run_git_fn,
                print_error_fn=self.git.print_error_fn,
                print_process_output_fn=self.git.print_process_output_fn,
                run_process_fn=self.git.run_process_fn,
            ),
            commit=ProjectActionCommitWorkflowDependencies(
                partition_envctl_protected_paths_fn=self.commit.partition_envctl_protected_paths_fn,
                ordered_unique_paths_fn=self.commit.ordered_unique_paths_fn,
            ),
            pull_request=ProjectActionPullRequestWorkflowDependencies(
                resolve_base_branch_fn=self.pull_request.resolve_base_branch_fn,
                existing_pr_url_fn=self.pull_request.existing_pr_url_fn,
                probe_dirty_worktree_fn=self.probe_dirty_worktree,
                run_commit_action_fn=self.pull_request.run_commit_action_fn,
                pr_title_fn=self.pull_request.pr_title_fn,
                pr_body_fn=self.pull_request.pr_body_fn,
                write_pr_body_file_fn=self.pull_request.write_pr_body_file_fn,
                run_pr_action_fn=self.pull_request.run_pr_action_fn,
                add_ship_pr_label_fn=self.pull_request.add_ship_pr_label_fn,
                github_pr_checks_fn=self.pull_request.github_pr_checks_fn,
            ),
            review=ProjectActionReviewWorkflowDependencies(
                resolve_analyze_mode_fn=self.review.resolve_analyze_mode_fn,
                resolve_original_plan_fn=self.review.resolve_original_plan_fn,
                resolve_review_base_fn=self.review.resolve_review_base_fn,
                analysis_iterations_fn=self.analysis_iterations,
                run_analyze_helper_fn=self.run_analyze_helper,
                tree_diffs_output_path_fn=self.review.tree_diffs_output_path_fn,
                original_plan_markdown_lines_fn=self.original_plan_markdown_lines,
            ),
        )

    def probe_dirty_worktree(self, project_root: Path, repo_root: Path, project_name: str) -> DirtyWorktreeReport:
        return self.pull_request.probe_dirty_worktree_source_fn(project_root, repo_root, project_name=project_name)

    def analysis_iterations(self, context: ReviewActionContext, mode: str) -> list[str]:
        return self.review.analysis_iterations_source_fn(context, mode=mode)

    def run_analyze_helper(
        self,
        context: ReviewActionContext,
        helper: Path,
        iterations: list[str],
        mode: str,
        scope: str,
        review_base: ReviewBaseResolution | None,
        original_plan: OriginalPlanResolution,
    ) -> int:
        return self.review.run_analyze_helper_source_fn(
            context=context,
            helper=helper,
            iterations=iterations,
            mode=mode,
            scope=scope,
            review_base=review_base,
            original_plan=original_plan,
        )

    def original_plan_markdown_lines(self, original_plan: OriginalPlanResolution) -> list[str]:
        return self.review.original_plan_markdown_lines_source_fn(original_plan, include_contents=True)
