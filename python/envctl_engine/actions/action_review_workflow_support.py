from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from envctl_engine.actions import action_review_plan_support as review_plan_support
from envctl_engine.actions.action_review_artifact_support import write_markdown_lines
from envctl_engine.actions.action_review_output_support import print_review_completion


def run_review_workflow(
    context: Any,
    *,
    resolve_git_root_fn: Callable[[Path, Path], Path],
    git_available: bool,
    git_output_fn: Callable[[Path, list[str]], str],
    resolve_analyze_mode_fn: Callable[[Any], str],
    resolve_original_plan_fn: Callable[[Any], review_plan_support.OriginalPlanResolution],
    resolve_review_base_fn: Callable[[Any, Path], review_plan_support.ReviewBaseResolution],
    analysis_iterations_fn: Callable[[Any, str], list[str]],
    run_analyze_helper_fn: Callable[
        [
            Any,
            Path,
            list[str],
            str,
            str,
            review_plan_support.ReviewBaseResolution | None,
            review_plan_support.OriginalPlanResolution,
        ],
        int,
    ],
    tree_diffs_output_path_fn: Callable[[Any, str, str], Path],
    original_plan_markdown_lines_fn: Callable[
        [review_plan_support.OriginalPlanResolution],
        list[str],
    ],
    sanitize_label_fn: Callable[[str], str],
) -> int:
    git_root = resolve_git_root_fn(context.project_root, context.repo_root)
    if not git_available:
        print("git is required for review action")
        return 1

    mode = resolve_analyze_mode_fn(context)
    scope = str(context.env.get("ENVCTL_ANALYZE_SCOPE", "all")).strip().lower() or "all"
    original_plan = resolve_original_plan_fn(context)
    review_base: review_plan_support.ReviewBaseResolution | None = None
    if mode == "single" or str(context.env.get("ENVCTL_REVIEW_BASE", "")).strip():
        try:
            review_base = resolve_review_base_fn(context, git_root)
        except review_plan_support.ReviewBaseResolutionError as exc:
            print(str(exc))
            return 1

    helper = context.repo_root / "utils" / "analyze-tree-changes.sh"
    if helper.is_file() and os.access(helper, os.X_OK):
        iterations = analysis_iterations_fn(context, mode)
        if iterations:
            return run_analyze_helper_fn(
                context,
                helper,
                iterations,
                mode,
                scope,
                review_base,
                original_plan,
            )

    if review_base is None:
        return _write_unbased_review_summary(
            context,
            git_root=git_root,
            mode=mode,
            scope=scope,
            original_plan=original_plan,
            git_output_fn=git_output_fn,
            tree_diffs_output_path_fn=tree_diffs_output_path_fn,
            original_plan_markdown_lines_fn=original_plan_markdown_lines_fn,
            sanitize_label_fn=sanitize_label_fn,
        )

    return _write_based_review_summary(
        context,
        git_root=git_root,
        mode=mode,
        scope=scope,
        review_base=review_base,
        original_plan=original_plan,
        git_output_fn=git_output_fn,
        tree_diffs_output_path_fn=tree_diffs_output_path_fn,
        original_plan_markdown_lines_fn=original_plan_markdown_lines_fn,
        sanitize_label_fn=sanitize_label_fn,
    )


def _write_unbased_review_summary(
    context: Any,
    *,
    git_root: Path,
    mode: str,
    scope: str,
    original_plan: review_plan_support.OriginalPlanResolution,
    git_output_fn: Callable[[Path, list[str]], str],
    tree_diffs_output_path_fn: Callable[[Any, str, str], Path],
    original_plan_markdown_lines_fn: Callable[[review_plan_support.OriginalPlanResolution], list[str]],
    sanitize_label_fn: Callable[[str], str],
) -> int:
    diff_stat = git_output_fn(git_root, ["diff", "--stat"]).strip()
    status = git_output_fn(git_root, ["status", "--porcelain"]).strip()
    output_path = tree_diffs_output_path_fn(
        context,
        "review",
        f"review_{sanitize_label_fn(context.project_name)}_{mode}",
    )
    write_markdown_lines(
        output_path,
        [
            f"# Review Summary: {context.project_name}",
            "",
            f"Mode: {mode}",
            f"Scope: {scope}",
            "",
            *original_plan_markdown_lines_fn(original_plan),
            "## Diff Stat",
            diff_stat or "(no diff)",
            "",
            "## Working Tree",
            status or "(clean)",
            "",
        ],
    )
    _print_review_ready(context, mode=mode, scope=scope, output_path=output_path)
    return 0


def _write_based_review_summary(
    context: Any,
    *,
    git_root: Path,
    mode: str,
    scope: str,
    review_base: review_plan_support.ReviewBaseResolution,
    original_plan: review_plan_support.OriginalPlanResolution,
    git_output_fn: Callable[[Path, list[str]], str],
    tree_diffs_output_path_fn: Callable[[Any, str, str], Path],
    original_plan_markdown_lines_fn: Callable[[review_plan_support.OriginalPlanResolution], list[str]],
    sanitize_label_fn: Callable[[str], str],
) -> int:
    diff_left = review_base.merge_base or review_base.base_ref
    diff_stat = git_output_fn(git_root, ["diff", "--find-renames", "--stat", diff_left]).strip()
    changed_files = git_output_fn(git_root, ["diff", "--find-renames", "--name-status", diff_left]).strip()
    full_diff = git_output_fn(git_root, ["diff", "--find-renames", diff_left]).strip()
    status = git_output_fn(git_root, ["status", "--porcelain", "--untracked-files=all"]).strip()
    output_path = tree_diffs_output_path_fn(
        context,
        "review",
        f"review_{sanitize_label_fn(context.project_name)}_{mode}",
    )
    write_markdown_lines(
        output_path,
        [
            f"# Review Summary: {context.project_name}",
            "",
            f"Mode: {mode}",
            f"Scope: {scope}",
            "",
            *original_plan_markdown_lines_fn(original_plan),
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
    _print_review_ready(context, mode=mode, scope=scope, output_path=output_path)
    return 0


def _print_review_ready(context: Any, *, mode: str, scope: str, output_path: Path) -> None:
    print_review_completion(
        context,
        mode=mode,
        scope=scope,
        output_dir=output_path.parent,
        summary_path=output_path,
        all_in_one_path=output_path,
        stats=[],
        tree_count=1,
    )
