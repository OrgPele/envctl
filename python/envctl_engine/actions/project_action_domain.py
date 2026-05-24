from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Mapping

import envctl_engine.actions.action_commit_support as commit_support
import envctl_engine.actions.action_git_state_support as git_state_support
import envctl_engine.actions.action_pr_message_support as pr_message_support
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
    git_root = resolve_git_root(context.project_root, context.repo_root)
    if shutil.which("git") is None:
        print("git is required for pr action")
        return 1

    head_branch = _git_output(git_root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip() or "unknown"
    if head_branch in {"HEAD", "unknown"}:
        print(f"Skipping {context.project_name} (detached HEAD).")
        return 0
    base_branch = _resolve_pr_base_branch(context, git_root)

    existing_url = existing_pr_url(git_root, head_branch)
    if existing_url:
        print(f"PR already exists: {existing_url}")
        return 0

    dirty_report = probe_dirty_worktree(context.project_root, context.repo_root, project_name=context.project_name)
    if dirty_report.dirty:
        print(f"Dirty worktree detected for {context.project_name}; committing and pushing before PR creation.")
        commit_code = run_commit_action(context)
        if commit_code != 0:
            return commit_code

    helper = context.repo_root / "utils" / "create-pr.sh"
    if helper.is_file() and os.access(helper, os.X_OK):
        command = [str(helper)]
        if base_branch:
            command.extend(["--base", base_branch])
        command.extend(["--head", head_branch, "--workdir", str(git_root)])
        created = subprocess.run(
            command,
            cwd=str(context.repo_root),
            text=True,
            capture_output=True,
            check=False,
        )
        _print_process_output(created)
        if created.returncode != 0:
            return 1
        return 0

    gh_path = shutil.which("gh")
    if gh_path is None:
        print("gh is required for pr action when utils/create-pr.sh is unavailable")
        return 1
    title = _pr_title(context, git_root, head_branch)
    body = _pr_body(context, git_root, head_branch, base_branch)
    body_file = _write_pr_body_file(body)
    args = [gh_path, "pr", "create", "--title", title, "--body-file", str(body_file), "--head", head_branch]
    if base_branch:
        args.extend(["--base", base_branch])
    try:
        created = subprocess.run(args, cwd=str(git_root), text=True, capture_output=True, check=False)
        _print_process_output(created)
        if created.returncode != 0:
            return 1
        return 0
    finally:
        try:
            body_file.unlink()
        except OSError:
            pass


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
    git_root = resolve_git_root(context.project_root, context.repo_root)
    if shutil.which("git") is None:
        print("git is required for review action")
        return 1

    mode = _resolve_analyze_mode(context)
    scope = str(context.env.get("ENVCTL_ANALYZE_SCOPE", "all")).strip().lower() or "all"
    original_plan = _resolve_original_plan(context)
    review_base: ReviewBaseResolution | None = None
    if mode == "single" or str(context.env.get("ENVCTL_REVIEW_BASE", "")).strip():
        try:
            review_base = _resolve_review_base(context, git_root)
        except ReviewBaseResolutionError as exc:
            print(str(exc))
            return 1

    helper = context.repo_root / "utils" / "analyze-tree-changes.sh"
    if helper.is_file() and os.access(helper, os.X_OK):
        iterations = _analysis_iterations(context, mode=mode)
        if iterations:
            return _run_analyze_helper(
                context=context,
                helper=helper,
                iterations=iterations,
                mode=mode,
                scope=scope,
                review_base=review_base,
                original_plan=original_plan,
            )

    if review_base is None:
        diff_stat = _git_output(git_root, ["diff", "--stat"]).strip()
        status = _git_output(git_root, ["status", "--porcelain"]).strip()
        output_path = _tree_diffs_output_path(
            context,
            "review",
            f"review_{sanitize_label(context.project_name)}_{mode}",
        )
        _write_markdown_lines(
            output_path,
            [
                f"# Review Summary: {context.project_name}",
                "",
                f"Mode: {mode}",
                f"Scope: {scope}",
                "",
                *_original_plan_markdown_lines(original_plan, include_contents=True),
                "## Diff Stat",
                diff_stat or "(no diff)",
                "",
                "## Working Tree",
                status or "(clean)",
                "",
            ],
        )
        _print_review_completion(
            context,
            mode=mode,
            scope=scope,
            output_dir=output_path.parent,
            summary_path=output_path,
            all_in_one_path=output_path,
            stats=[],
            tree_count=1,
        )
        return 0

    diff_left = review_base.merge_base or review_base.base_ref
    diff_stat = _git_output(git_root, ["diff", "--find-renames", "--stat", diff_left]).strip()
    changed_files = _git_output(git_root, ["diff", "--find-renames", "--name-status", diff_left]).strip()
    full_diff = _git_output(git_root, ["diff", "--find-renames", diff_left]).strip()
    status = _git_output(git_root, ["status", "--porcelain", "--untracked-files=all"]).strip()
    output_path = _tree_diffs_output_path(
        context,
        "review",
        f"review_{sanitize_label(context.project_name)}_{mode}",
    )
    _write_markdown_lines(
        output_path,
        [
            f"# Review Summary: {context.project_name}",
            "",
            f"Mode: {mode}",
            f"Scope: {scope}",
            "",
            *_original_plan_markdown_lines(original_plan, include_contents=True),
            "## Base branch",
            review_base.base_branch,
            "",
            "## Base resolution source",
            review_base.source,
            "",
            "## Base ref",
            review_base.base_ref,
            "",
            "## Merge base",
            review_base.merge_base or "(merge-base unavailable)",
            "",
            "## Diff Stat",
            diff_stat or "(no diff)",
            "",
            "## Changed files",
            changed_files or "(no changed files)",
            "",
            "## Full diff",
            full_diff or "(no diff)",
            "",
            "## Working tree / untracked files",
            status or "(clean)",
            "",
        ],
    )
    _print_review_completion(
        context,
        mode=mode,
        scope=scope,
        output_dir=output_path.parent,
        summary_path=output_path,
        all_in_one_path=output_path,
        stats=[],
        tree_count=1,
    )
    return 0


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


def _tree_changelog_path(context: ActionProjectContext) -> Path | None:
    tree_name = "main" if context.project_name.strip().lower() == "main" else context.project_name.strip()
    candidate = context.project_root / "docs" / "changelog" / f"{sanitize_label(tree_name)}_changelog.md"
    if candidate.is_file() and _file_has_text(candidate):
        return candidate
    return None


def _file_has_text(path: Path) -> bool:
    return commit_support.file_has_text(path)


def _summary_output_path(repo_root: Path, directory: str, prefix: str, label: str | None = None) -> Path:
    output_dir = repo_root / directory
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    if label:
        return output_dir / f"{prefix}_{sanitize_label(label)}_{timestamp}.md"
    return output_dir / f"{prefix}_{timestamp}.md"


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


def _write_markdown_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines), encoding="utf-8")


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
