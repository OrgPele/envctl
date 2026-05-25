from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Any

import envctl_engine.actions.action_ship_support as ship_support
from envctl_engine.actions.action_git_state_support import DirtyWorktreeReport
from envctl_engine.actions.project_action_workflows import ProjectActionWorkflowRunner


@dataclass(frozen=True, slots=True)
class ProjectActionWorkflowFactory:
    """Builds project-action workflow runners from explicit compatibility dependencies."""

    resolve_git_root_fn: Callable[[Path, Path], Path]
    which_fn: Callable[[str], str | None]
    git_output_fn: Callable[[Path, list[str]], str]
    run_git_fn: Callable[[Path, list[str]], subprocess.CompletedProcess[str]]
    print_error_fn: Callable[[str, subprocess.CompletedProcess[str]], None]
    partition_envctl_protected_paths_fn: Callable[..., Any]
    ordered_unique_paths_fn: Callable[..., list[str]]
    resolve_base_branch_fn: Callable[[Any, Path], str]
    existing_pr_url_fn: Callable[[Path, str], str]
    probe_dirty_worktree_source_fn: Callable[..., DirtyWorktreeReport]
    run_commit_action_fn: Callable[[Any], int]
    pr_title_fn: Callable[[Any, Path, str], str]
    pr_body_fn: Callable[[Any, Path, str, str], str]
    write_pr_body_file_fn: Callable[[str], Path]
    print_process_output_fn: Callable[[subprocess.CompletedProcess[str]], None]
    run_process_fn: Callable[..., subprocess.CompletedProcess[str]]
    run_pr_action_fn: Callable[[Any], int]
    github_pr_checks_fn: ship_support.GithubPrChecks
    resolve_analyze_mode_fn: Callable[[Any], str]
    resolve_original_plan_fn: Callable[[Any], Any]
    resolve_review_base_fn: Callable[[Any, Path], Any]
    analysis_iterations_source_fn: Callable[..., list[str]]
    run_analyze_helper_source_fn: Callable[..., int]
    tree_diffs_output_path_fn: Callable[[Any, str, str], Path]
    original_plan_markdown_lines_source_fn: Callable[..., list[str]]
    sanitize_label_fn: Callable[[str], str]

    def build(self) -> ProjectActionWorkflowRunner:
        return ProjectActionWorkflowRunner(
            resolve_git_root_fn=self.resolve_git_root_fn,
            which_fn=self.which_fn,
            git_output_fn=self.git_output_fn,
            run_git_fn=self.run_git_fn,
            print_error_fn=self.print_error_fn,
            partition_envctl_protected_paths_fn=self.partition_envctl_protected_paths_fn,
            ordered_unique_paths_fn=self.ordered_unique_paths_fn,
            resolve_base_branch_fn=self.resolve_base_branch_fn,
            existing_pr_url_fn=self.existing_pr_url_fn,
            probe_dirty_worktree_fn=self.probe_dirty_worktree,
            run_commit_action_fn=self.run_commit_action_fn,
            pr_title_fn=self.pr_title_fn,
            pr_body_fn=self.pr_body_fn,
            write_pr_body_file_fn=self.write_pr_body_file_fn,
            print_process_output_fn=self.print_process_output_fn,
            run_process_fn=self.run_process_fn,
            run_pr_action_fn=self.run_pr_action_fn,
            github_pr_checks_fn=self.github_pr_checks_fn,
            resolve_analyze_mode_fn=self.resolve_analyze_mode_fn,
            resolve_original_plan_fn=self.resolve_original_plan_fn,
            resolve_review_base_fn=self.resolve_review_base_fn,
            analysis_iterations_fn=self.analysis_iterations,
            run_analyze_helper_fn=self.run_analyze_helper,
            tree_diffs_output_path_fn=self.tree_diffs_output_path_fn,
            original_plan_markdown_lines_fn=self.original_plan_markdown_lines,
            sanitize_label_fn=self.sanitize_label_fn,
        )

    def probe_dirty_worktree(self, project_root: Path, repo_root: Path, project_name: str) -> DirtyWorktreeReport:
        return self.probe_dirty_worktree_source_fn(project_root, repo_root, project_name=project_name)

    def analysis_iterations(self, context: Any, mode: str) -> list[str]:
        return self.analysis_iterations_source_fn(context, mode=mode)

    def run_analyze_helper(
        self,
        context: Any,
        helper: Path,
        iterations: list[str],
        mode: str,
        scope: str,
        review_base: Any,
        original_plan: Any,
    ) -> int:
        return self.run_analyze_helper_source_fn(
            context=context,
            helper=helper,
            iterations=iterations,
            mode=mode,
            scope=scope,
            review_base=review_base,
            original_plan=original_plan,
        )

    def original_plan_markdown_lines(self, original_plan: Any) -> list[str]:
        return self.original_plan_markdown_lines_source_fn(original_plan, include_contents=True)
