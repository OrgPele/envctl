from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Mapping

import envctl_engine.actions.action_commit_support as commit_support
import envctl_engine.actions.action_git_state_support as git_state_support
import envctl_engine.actions.action_pr_message_support as pr_message_support
import envctl_engine.actions.action_review_artifact_support as review_artifact_support
import envctl_engine.actions.action_review_base_support as review_base_support
import envctl_engine.actions.action_review_iteration_support as review_iteration_support
import envctl_engine.actions.action_review_original_plan_support as review_original_plan_support
import envctl_engine.actions.action_ship_support as ship_support
import envctl_engine.actions.project_action_workflow_factory as workflow_factory
from envctl_engine.actions.action_protected_artifacts import (
    EnvctlProtectedPathPartition,
    ordered_unique_paths as _ordered_unique_paths,
    partition_envctl_protected_paths as _partition_envctl_protected_paths,
    status_candidate_path as _status_candidate_path,
)
from envctl_engine.actions.action_review_output_support import (
    display_path as _display_path,
    print_review_completion as _print_review_completion,
    print_review_completion_rich as _print_review_completion_rich,
    review_colorizer as _review_colorizer,
)
from envctl_engine.actions.action_review_context import ReviewActionContext
from envctl_engine.actions.project_action_workflows import ProjectActionWorkflowRunner
from envctl_engine.shared.parsing import parse_bool

PR_BODY_MAX_CHARS = 48_000
PR_TITLE_MAX_CHARS = 240
COMMIT_MESSAGE_MAX_CHARS = commit_support.COMMIT_MESSAGE_MAX_CHARS
WORKTREE_PROVENANCE_SCHEMA_VERSION = 1
WORKTREE_PROVENANCE_PATH = Path(".envctl-state") / "worktree-provenance.json"
PLANNING_ROOT = Path("todo") / "plans"
DONE_PLANNING_ROOT = Path("todo") / "done"
ENVCTL_COMMIT_LEDGER_NAME = commit_support.ENVCTL_COMMIT_LEDGER_NAME
ENVCTL_COMMIT_POINTER_MARKER = commit_support.ENVCTL_COMMIT_POINTER_MARKER

__all__ = [
    "ActionProjectContext",
    "DirtyWorktreeReport",
    "EnvctlProtectedPathPartition",
    "OriginalPlanResolution",
    "ReviewBaseResolution",
    "ReviewBaseResolutionError",
    "_display_path",
    "_latest_changelog_commit_message",
    "_main_task_title",
    "_normalize_text_block",
    "_normalize_title_text",
    "_parse_merge_tree_conflicts",
    "_partition_envctl_protected_paths",
    "_pr_body",
    "_pr_commit_messages",
    "_pr_diff_stat",
    "_pr_title",
    "_print_review_completion",
    "_print_review_completion_rich",
    "_read_text",
    "_review_colorizer",
    "_status_candidate_path",
    "_truncate_pr_body",
    "_unmerged_stage_entries",
    "_write_pr_body_file",
    "detect_default_branch",
    "existing_pr_url",
    "probe_dirty_worktree",
    "resolve_git_root",
    "run_commit_action",
    "run_pr_action",
    "run_review_action",
    "run_ship_action",
]


@dataclass(frozen=True, slots=True)
class ActionProjectContext:
    repo_root: Path
    project_root: Path
    project_name: str
    env: Mapping[str, str]

    @property
    def interactive(self) -> bool:
        return parse_bool(self.env.get("ENVCTL_ACTION_INTERACTIVE"), False) and bool(sys.stdin.isatty())


ReviewBaseResolution = review_base_support.ReviewBaseResolution
ReviewBaseResolutionError = review_base_support.ReviewBaseResolutionError
OriginalPlanResolution = review_original_plan_support.OriginalPlanResolution

def _workflow_runner() -> ProjectActionWorkflowRunner:
    return workflow_factory.ProjectActionWorkflowFactory(
        git=workflow_factory.ProjectActionWorkflowGitSources(
            resolve_git_root_fn=resolve_git_root,
            which_fn=shutil.which,
            git_output_fn=_git_output,
            run_git_fn=_run_git,
            print_error_fn=_print_error,
            print_process_output_fn=_print_process_output,
            run_process_fn=subprocess.run,
        ),
        commit=workflow_factory.ProjectActionWorkflowCommitSources(
            partition_envctl_protected_paths_fn=_partition_envctl_protected_paths,
            ordered_unique_paths_fn=_ordered_unique_paths,
        ),
        pull_request=workflow_factory.ProjectActionWorkflowPullRequestSources(
            resolve_base_branch_fn=_resolve_pr_base_branch,
            existing_pr_url_fn=existing_pr_url,
            probe_dirty_worktree_source_fn=probe_dirty_worktree,
            run_commit_action_fn=run_commit_action,
            pr_title_fn=_pr_title,
            pr_body_fn=_pr_body,
            write_pr_body_file_fn=_write_pr_body_file,
            run_pr_action_fn=run_pr_action,
            github_pr_checks_fn=_github_pr_checks,
        ),
        review=workflow_factory.ProjectActionWorkflowReviewSources(
            resolve_analyze_mode_fn=_resolve_analyze_mode,
            resolve_original_plan_fn=_resolve_original_plan,
            resolve_review_base_fn=_resolve_review_base,
            analysis_iterations_source_fn=_analysis_iterations,
            run_analyze_helper_source_fn=_run_analyze_helper,
            tree_diffs_output_path_fn=_tree_diffs_output_path,
            original_plan_markdown_lines_source_fn=_original_plan_markdown_lines,
        ),
    ).build()


def run_commit_action(context: ActionProjectContext) -> int:
    return _workflow_runner().run_commit_action(context)


def _unstage_envctl_protected_paths(git_root: Path, paths: list[str]) -> subprocess.CompletedProcess[str]:
    return commit_support.unstage_envctl_protected_paths(git_root, paths, run_git=_run_git)


def _pr_title(context: ActionProjectContext, git_root: Path, head_branch: str) -> str:
    return pr_message_support.pr_title(
        context,
        git_root,
        head_branch,
        git_output=_git_output,
        max_chars=PR_TITLE_MAX_CHARS,
    )


def _pr_body(context: ActionProjectContext, git_root: Path, head_branch: str, base_branch: str) -> str:
    return pr_message_support.pr_body(
        context,
        git_root,
        head_branch,
        base_branch,
        git_output=_git_output,
        max_chars=PR_BODY_MAX_CHARS,
    )


def _pr_commit_messages(git_root: Path, *, head_branch: str, base_branch: str) -> str:
    return pr_message_support.pr_commit_messages(
        git_root,
        head_branch=head_branch,
        base_branch=base_branch,
        git_output=_git_output,
        max_chars=PR_BODY_MAX_CHARS,
    )


def _pr_diff_stat(git_root: Path, *, head_branch: str, base_branch: str) -> str:
    return pr_message_support.pr_diff_stat(
        git_root,
        head_branch=head_branch,
        base_branch=base_branch,
        git_output=_git_output,
    )


def _pr_commit_range(git_root: Path, *, head_branch: str, base_branch: str) -> str:
    return pr_message_support.pr_commit_range(
        git_root,
        head_branch=head_branch,
        base_branch=base_branch,
        git_output=_git_output,
    )


def _pr_compare_range(git_root: Path, *, head_branch: str, base_branch: str) -> str:
    return pr_message_support.pr_compare_range(
        git_root,
        head_branch=head_branch,
        base_branch=base_branch,
        git_output=_git_output,
    )


def _pr_base_ref(git_root: Path, base_branch: str) -> str:
    return pr_message_support.pr_base_ref(git_root, base_branch, git_output=_git_output)


def _existing_merge_conflict_report(git_root: Path, *, branch: str) -> dict[str, object]:
    return ship_support.existing_merge_conflict_report(git_root, branch=branch, git_output=_git_output)


def _predicted_merge_conflict_report(
    context: ActionProjectContext,
    git_root: Path,
    *,
    branch: str,
) -> dict[str, object]:
    return ship_support.predicted_merge_conflict_report(
        context,
        git_root,
        branch=branch,
        resolve_base_branch=_resolve_pr_base_branch,
        resolve_base_ref=_pr_base_ref,
        run_git=_run_git,
        git_output=_git_output,
    )


def _unmerged_stage_entries(git_root: Path) -> dict[str, list[dict[str, str]]]:
    return ship_support.unmerged_stage_entries(git_root, git_output=_git_output)


_parse_merge_tree_conflicts = ship_support.parse_merge_tree_conflicts
_github_pr_checks = ship_support.github_pr_checks
_ship_payload = ship_support.ship_payload
_print_ship_result = ship_support.print_ship_result
_recent_text_excerpt = pr_message_support.recent_text_excerpt
_truncate_recent_entries = pr_message_support.truncate_recent_entries
_latest_changelog_commit_message = pr_message_support.latest_changelog_commit_message
_select_changelog_subject = pr_message_support.select_changelog_subject
_main_task_title = pr_message_support.main_task_title_from_project
_normalize_title_text = pr_message_support.normalize_title_text
_truncate_pr_body = pr_message_support.truncate_pr_body
_normalize_text_block = pr_message_support.normalize_text_block
_read_text = pr_message_support.read_text
_write_pr_body_file = pr_message_support.write_pr_body_file


def run_pr_action(context: ActionProjectContext) -> int:
    return _workflow_runner().run_pr_action(context)


def run_ship_action(context: ActionProjectContext) -> int:
    return _workflow_runner().run_ship_action(context)


def _ship_protected_paths(git_root: Path) -> list[str]:
    return ship_support.ship_protected_paths(
        git_root,
        git_output=_git_output,
        partition_envctl_protected_paths=_partition_envctl_protected_paths,
        ordered_unique_paths=_ordered_unique_paths,
    )


def run_review_action(context: ActionProjectContext) -> int:
    return _workflow_runner().run_review_action(context)


DirtyWorktreeReport = git_state_support.DirtyWorktreeReport
resolve_git_root = git_state_support.resolve_git_root
_classify_dirty_porcelain = git_state_support.classify_dirty_porcelain


def probe_dirty_worktree(project_root: Path, repo_root: Path, *, project_name: str = "") -> DirtyWorktreeReport:
    return git_state_support.probe_dirty_worktree(
        project_root,
        repo_root,
        project_name=project_name,
        git_output=_git_output,
    )


def detect_default_branch(git_root: Path) -> str:
    return git_state_support.detect_default_branch(git_root, git_output=_git_output)


def existing_pr_url(git_root: Path, branch: str) -> str:
    return git_state_support.existing_pr_url(
        git_root,
        branch,
        gh_path=shutil.which("gh"),
        run_process=subprocess.run,
    )


_resolve_original_plan = review_original_plan_support.resolve_original_plan
_read_worktree_provenance = review_original_plan_support.read_worktree_provenance
_resolve_plan_file_from_record = review_original_plan_support.resolve_plan_file_from_record
_infer_original_plan_file = review_original_plan_support.infer_original_plan_file
_feature_name_from_project_name = review_original_plan_support.feature_name_from_project_name
_original_plan_markdown_lines = review_original_plan_support.original_plan_markdown_lines
_augment_review_output_dir = review_original_plan_support.augment_review_output_dir
_augment_review_markdown_file = review_original_plan_support.augment_review_markdown_file


def _resolve_commit_message(
    context: ActionProjectContext,
    *,
    branch: str,
) -> tuple[str, str, str | None, Path | None]:
    return commit_support.resolve_commit_message(context, branch=branch)


def _read_commit_ledger_segment(path: Path) -> tuple[str, str | None]:
    return commit_support.read_commit_ledger_segment(path)


def _advance_commit_ledger_pointer(path: Path) -> str | None:
    return commit_support.advance_commit_ledger_pointer(path)


def _resolve_pr_base_branch(context: ActionProjectContext, git_root: Path) -> str:
    explicit = str(context.env.get("ENVCTL_PR_BASE", "")).strip()
    if explicit:
        return explicit
    return detect_default_branch(git_root)


_resolve_analyze_mode = review_iteration_support.resolve_analyze_mode


def _resolve_review_base(context: ReviewActionContext, git_root: Path) -> ReviewBaseResolution:
    return review_base_support.resolve_review_base(
        context,
        git_root,
        detect_default_branch_fn=detect_default_branch,
        git_output_fn=_git_output,
    )


def _resolve_provenance_review_base(
    git_root: Path,
    provenance: Mapping[str, object] | None,
) -> ReviewBaseResolution | None:
    return review_base_support.resolve_provenance_review_base(
        git_root,
        provenance,
        git_output_fn=_git_output,
    )


def _resolve_upstream_review_base(git_root: Path) -> ReviewBaseResolution | None:
    return review_base_support.resolve_upstream_review_base(git_root, git_output_fn=_git_output)


def _resolve_review_base_candidate(
    git_root: Path,
    *,
    base_branch: str,
    source: str,
    preferred_ref: str = "",
) -> ReviewBaseResolution | None:
    return review_base_support.resolve_review_base_candidate(
        git_root,
        base_branch=base_branch,
        source=source,
        preferred_ref=preferred_ref,
        git_output_fn=_git_output,
    )


def _resolve_review_base_ref(git_root: Path, *, base_branch: str, preferred_ref: str = "") -> str:
    return review_base_support.resolve_review_base_ref(
        git_root,
        base_branch=base_branch,
        preferred_ref=preferred_ref,
        git_output_fn=_git_output,
    )


_branch_name_from_ref = review_base_support.branch_name_from_ref
_load_worktree_provenance = review_base_support.load_worktree_provenance
_write_commit_message_file = commit_support.write_commit_message_file
_atomic_write = commit_support.atomic_write


def _analysis_iterations(context: ReviewActionContext, *, mode: str) -> list[str]:
    return review_iteration_support.analysis_iterations(context, mode=mode)


_project_family_dir = review_iteration_support.project_family_dir
_git_iteration_dirs = review_iteration_support.git_iteration_dirs


def _run_analyze_helper(
    *,
    context: ReviewActionContext,
    helper: Path,
    iterations: list[str],
    mode: str,
    scope: str,
    review_base: ReviewBaseResolution | None,
    original_plan: OriginalPlanResolution,
) -> int:
    return review_iteration_support.run_analyze_helper(
        context=context,
        helper=helper,
        iterations=iterations,
        mode=mode,
        scope=scope,
        review_base=review_base,
        original_plan=original_plan,
        run_process_fn=subprocess.run,
    )


_file_has_text = review_artifact_support.file_has_text


def _tree_changelog_path(context: ReviewActionContext) -> Path | None:
    return review_artifact_support.tree_changelog_path(context)


def _summary_output_path(repo_root: Path, directory: str, prefix: str, label: str | None = None) -> Path:
    return review_artifact_support.summary_output_path(
        repo_root,
        directory,
        prefix,
        label,
    )


def _tree_diffs_root(context: ReviewActionContext) -> Path:
    return review_iteration_support.tree_diffs_root(context)


def _tree_diffs_output_path(
    context: ReviewActionContext,
    directory: str,
    prefix: str,
    label: str | None = None,
) -> Path:
    return review_iteration_support.tree_diffs_output_path(
        context,
        directory,
        prefix,
        label,
    )


_write_markdown_lines = review_artifact_support.write_markdown_lines


def _run_git(git_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return git_state_support.run_git(git_root, args, run_process=subprocess.run)


def _git_output(git_root: Path, args: list[str]) -> str:
    return git_state_support.git_output(git_root, args, run_git_fn=_run_git)


_print_process_output = git_state_support.print_process_output


def _print_error(prefix: str, result: subprocess.CompletedProcess[str]) -> None:
    git_state_support.print_error(prefix, result)
