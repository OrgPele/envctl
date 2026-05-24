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
import envctl_engine.actions.action_pr_workflow_support as pr_workflow_support
import envctl_engine.actions.action_review_workflow_support as review_workflow_support
import envctl_engine.actions.action_review_plan_support as review_plan_support
import envctl_engine.actions.action_ship_support as ship_support
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
    "sanitize_label",
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


ReviewBaseResolution = review_plan_support.ReviewBaseResolution
ReviewBaseResolutionError = review_plan_support.ReviewBaseResolutionError
OriginalPlanResolution = review_plan_support.OriginalPlanResolution


def run_commit_action(context: ActionProjectContext) -> int:
    return commit_support.run_commit_workflow(
        context,
        resolve_git_root=resolve_git_root,
        git_available=shutil.which("git") is not None,
        git_output=_git_output,
        run_git=_run_git,
        print_error=_print_error,
        partition_envctl_protected_paths=_partition_envctl_protected_paths,
        ordered_unique_paths=_ordered_unique_paths,
    )


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
    return pr_workflow_support.run_pr_workflow(
        context,
        resolve_git_root_fn=resolve_git_root,
        git_available=shutil.which("git") is not None,
        git_output_fn=_git_output,
        resolve_base_branch_fn=_resolve_pr_base_branch,
        existing_pr_url_fn=existing_pr_url,
        probe_dirty_worktree_fn=_probe_dirty_worktree_from_pr_workflow,
        run_commit_action_fn=run_commit_action,
        pr_title_fn=_pr_title,
        pr_body_fn=_pr_body,
        write_pr_body_file_fn=_write_pr_body_file,
        print_process_output_fn=_print_process_output,
        gh_path=shutil.which("gh"),
        run_process_fn=subprocess.run,
    )


def run_ship_action(context: ActionProjectContext) -> int:
    return ship_support.run_ship_workflow(
        context,
        resolve_git_root=resolve_git_root,
        git_available=shutil.which("git") is not None,
        git_output=_git_output,
        run_git=_run_git,
        resolve_base_branch=_resolve_pr_base_branch,
        resolve_base_ref=_pr_base_ref,
        run_commit_action=run_commit_action,
        run_pr_action=run_pr_action,
        probe_dirty_worktree=probe_dirty_worktree,
        existing_pr_url=existing_pr_url,
        partition_envctl_protected_paths=_partition_envctl_protected_paths,
        ordered_unique_paths=_ordered_unique_paths,
        github_pr_checks=_github_pr_checks,
    )


def _ship_protected_paths(git_root: Path) -> list[str]:
    return ship_support.ship_protected_paths(
        git_root,
        git_output=_git_output,
        partition_envctl_protected_paths=_partition_envctl_protected_paths,
        ordered_unique_paths=_ordered_unique_paths,
    )


def run_review_action(context: ActionProjectContext) -> int:
    return review_workflow_support.run_review_workflow(
        context,
        resolve_git_root_fn=resolve_git_root,
        git_available=shutil.which("git") is not None,
        git_output_fn=_git_output,
        resolve_analyze_mode_fn=_resolve_analyze_mode,
        resolve_original_plan_fn=_resolve_original_plan,
        resolve_review_base_fn=_resolve_review_base,
        analysis_iterations_fn=lambda review_context, mode: _analysis_iterations(
            review_context,
            mode=mode,
        ),
        run_analyze_helper_fn=_run_analyze_helper_from_workflow,
        tree_diffs_output_path_fn=_tree_diffs_output_path_from_workflow,
        original_plan_markdown_lines_fn=lambda original_plan: _original_plan_markdown_lines(
            original_plan,
            include_contents=True,
        ),
        sanitize_label_fn=sanitize_label,
    )


DirtyWorktreeReport = git_state_support.DirtyWorktreeReport


def resolve_git_root(project_root: Path, repo_root: Path) -> Path:
    return git_state_support.resolve_git_root(project_root, repo_root)


def probe_dirty_worktree(project_root: Path, repo_root: Path, *, project_name: str = "") -> DirtyWorktreeReport:
    return git_state_support.probe_dirty_worktree(
        project_root,
        repo_root,
        project_name=project_name,
        git_output=_git_output,
    )


def _probe_dirty_worktree_from_pr_workflow(
    project_root: Path,
    repo_root: Path,
    project_name: str,
) -> DirtyWorktreeReport:
    return probe_dirty_worktree(project_root, repo_root, project_name=project_name)


def _classify_dirty_porcelain(status_output: str) -> tuple[bool, bool, bool]:
    return git_state_support.classify_dirty_porcelain(status_output)


def detect_default_branch(git_root: Path) -> str:
    return git_state_support.detect_default_branch(git_root, git_output=_git_output)


def existing_pr_url(git_root: Path, branch: str) -> str:
    return git_state_support.existing_pr_url(
        git_root,
        branch,
        gh_path=shutil.which("gh"),
        run_process=subprocess.run,
    )


def sanitize_label(value: str) -> str:
    return git_state_support.sanitize_label(value)


def _resolve_original_plan(context: ActionProjectContext) -> OriginalPlanResolution:
    return review_plan_support.resolve_original_plan(context)


_read_worktree_provenance = review_plan_support.read_worktree_provenance
_resolve_plan_file_from_record = review_plan_support.resolve_plan_file_from_record
_infer_original_plan_file = review_plan_support.infer_original_plan_file
_feature_name_from_project_name = review_plan_support.feature_name_from_project_name
_original_plan_markdown_lines = review_plan_support.original_plan_markdown_lines
_augment_review_output_dir = review_plan_support.augment_review_output_dir
_augment_review_markdown_file = review_plan_support.augment_review_markdown_file


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


def _resolve_analyze_mode(context: ActionProjectContext) -> str:
    return review_plan_support.resolve_analyze_mode(context)


def _resolve_review_base(context: ActionProjectContext, git_root: Path) -> ReviewBaseResolution:
    return review_plan_support.resolve_review_base(
        context,
        git_root,
        detect_default_branch_fn=detect_default_branch,
        git_output_fn=_git_output,
    )


def _resolve_provenance_review_base(
    git_root: Path,
    provenance: Mapping[str, object] | None,
) -> ReviewBaseResolution | None:
    return review_plan_support.resolve_provenance_review_base(
        git_root,
        provenance,
        git_output_fn=_git_output,
    )


def _resolve_upstream_review_base(git_root: Path) -> ReviewBaseResolution | None:
    return review_plan_support.resolve_upstream_review_base(git_root, git_output_fn=_git_output)


def _resolve_review_base_candidate(
    git_root: Path,
    *,
    base_branch: str,
    source: str,
    preferred_ref: str = "",
) -> ReviewBaseResolution | None:
    return review_plan_support.resolve_review_base_candidate(
        git_root,
        base_branch=base_branch,
        source=source,
        preferred_ref=preferred_ref,
        git_output_fn=_git_output,
    )


def _resolve_review_base_ref(git_root: Path, *, base_branch: str, preferred_ref: str = "") -> str:
    return review_plan_support.resolve_review_base_ref(
        git_root,
        base_branch=base_branch,
        preferred_ref=preferred_ref,
        git_output_fn=_git_output,
    )


_branch_name_from_ref = review_plan_support.branch_name_from_ref
_load_worktree_provenance = review_plan_support.load_worktree_provenance


def _write_commit_message_file(message: str) -> Path:
    return commit_support.write_commit_message_file(message)


def _atomic_write(path: Path, text: str) -> None:
    commit_support.atomic_write(path, text)


def _analysis_iterations(context: ActionProjectContext, *, mode: str) -> list[str]:
    return review_plan_support.analysis_iterations(context, mode=mode)


_project_family_dir = review_plan_support.project_family_dir
_git_iteration_dirs = review_plan_support.git_iteration_dirs


def _run_analyze_helper(
    *,
    context: ActionProjectContext,
    helper: Path,
    iterations: list[str],
    mode: str,
    scope: str,
    review_base: ReviewBaseResolution | None,
    original_plan: OriginalPlanResolution,
) -> int:
    return review_plan_support.run_analyze_helper(
        context=context,
        helper=helper,
        iterations=iterations,
        mode=mode,
        scope=scope,
        review_base=review_base,
        original_plan=original_plan,
        sanitize_label_fn=sanitize_label,
        run_process_fn=subprocess.run,
    )


def _run_analyze_helper_from_workflow(
    context: ActionProjectContext,
    helper: Path,
    iterations: list[str],
    mode: str,
    scope: str,
    review_base: ReviewBaseResolution | None,
    original_plan: OriginalPlanResolution,
) -> int:
    return _run_analyze_helper(
        context=context,
        helper=helper,
        iterations=iterations,
        mode=mode,
        scope=scope,
        review_base=review_base,
        original_plan=original_plan,
    )


def _tree_changelog_path(context: ActionProjectContext) -> Path | None:
    return review_artifact_support.tree_changelog_path(context, sanitize_label_fn=sanitize_label)


def _file_has_text(path: Path) -> bool:
    return review_artifact_support.file_has_text(path)


def _summary_output_path(repo_root: Path, directory: str, prefix: str, label: str | None = None) -> Path:
    return review_artifact_support.summary_output_path(
        repo_root,
        directory,
        prefix,
        label,
        sanitize_label_fn=sanitize_label,
    )


def _tree_diffs_root(context: ActionProjectContext) -> Path:
    return review_plan_support.tree_diffs_root(context)


def _tree_diffs_output_path(
    context: ActionProjectContext,
    directory: str,
    prefix: str,
    label: str | None = None,
) -> Path:
    return review_plan_support.tree_diffs_output_path(
        context,
        directory,
        prefix,
        label,
        sanitize_label_fn=sanitize_label,
    )


def _tree_diffs_output_path_from_workflow(context: ActionProjectContext, directory: str, prefix: str) -> Path:
    return _tree_diffs_output_path(context, directory, prefix)


def _write_markdown_lines(path: Path, lines: list[str]) -> None:
    review_artifact_support.write_markdown_lines(path, lines)


def _run_git(git_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return git_state_support.run_git(git_root, args, run_process=subprocess.run)


def _git_output(git_root: Path, args: list[str]) -> str:
    return git_state_support.git_output(git_root, args, run_git_fn=_run_git)


def _print_process_output(result: subprocess.CompletedProcess[str]) -> None:
    git_state_support.print_process_output(result)


def _first_existing_path(*paths: Path) -> Path:
    for path in paths:
        if path.is_file():
            return path
    return paths[0]


def _print_error(prefix: str, result: subprocess.CompletedProcess[str]) -> None:
    git_state_support.print_error(prefix, result)
