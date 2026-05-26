from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Callable

from envctl_engine.actions.action_review_context import ReviewActionContext
from envctl_engine.actions.action_review_base_support import ReviewBaseResolution
from envctl_engine.actions.action_review_original_plan_support import (
    OriginalPlanResolution,
    augment_review_output_dir,
    first_existing_path,
)
from envctl_engine.actions.action_review_output_support import (
    parse_review_stats,
    print_review_completion,
    print_review_failure,
    prune_review_output_dir,
)
from envctl_engine.actions.action_review_artifact_support import timestamped_markdown_path
from envctl_engine.shared.artifact_names import safe_artifact_stem


def resolve_analyze_mode(context: ReviewActionContext) -> str:
    explicit = str(context.env.get("ENVCTL_ANALYZE_MODE", "")).strip().lower()
    if explicit in {"single", "grouped"}:
        return explicit
    return "single"


def analysis_iterations(context: ReviewActionContext, *, mode: str) -> list[str]:
    project_root = context.project_root.resolve()
    if project_root == context.repo_root.resolve():
        return []
    family_dir = project_family_dir(project_root)
    if family_dir is None:
        return []

    iterations = git_iteration_dirs(family_dir)
    if not iterations:
        return []
    if mode == "single":
        current_name = project_root.name
        if current_name in iterations:
            return [current_name]
        return [iterations[0]]
    return iterations


def project_family_dir(project_root: Path) -> Path | None:
    parent = project_root.parent
    if parent == project_root:
        return None
    if project_root.name.isdigit() and parent.is_dir():
        return parent
    child_git_dirs = git_iteration_dirs(parent)
    if child_git_dirs:
        return parent
    return None


def git_iteration_dirs(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    iterations: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        git_marker = child / ".git"
        if git_marker.is_file() or git_marker.is_dir():
            iterations.append(child.name)
    return iterations


def run_analyze_helper(
    *,
    context: ReviewActionContext,
    helper: Path,
    iterations: list[str],
    mode: str,
    scope: str,
    review_base: ReviewBaseResolution | None,
    original_plan: OriginalPlanResolution,
    run_process_fn: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> int:
    project_root = context.project_root.resolve()
    family_dir = project_family_dir(project_root)
    if family_dir is None:
        return 1

    approach = "combine" if mode == "grouped" and len(iterations) > 1 else "optimal"
    output_dir = tree_diffs_root(context) / (
        f"analysis_{safe_artifact_stem(context.project_name, fallback='project')}_"
        f"{safe_artifact_stem(scope, fallback='scope')}_{mode}_"
        f"{datetime.now(tz=UTC).strftime('%Y%m%d_%H%M%S')}"
    )
    args = [
        f"trees={','.join(iterations)}",
        f"approach={approach}",
        "output-dir=" + str(output_dir),
    ]
    if review_base is not None:
        args.extend(
            [
                f"base-branch={review_base.base_branch}",
                f"base-source={review_base.source}",
                f"base-ref={review_base.base_ref}",
            ]
        )
    if scope != "all":
        args.append(f"scope={scope}")
    if not (mode == "grouped" and len(iterations) > 1):
        args.extend(["security-check=true", "performance-check=true"])

    env_map = dict(os.environ)
    env_map.update(context.env)
    env_map["BASE_DIR"] = str(context.repo_root)
    env_map["TREES_DIR_NAME"] = str(family_dir)
    if original_plan.path is not None:
        env_map["ENVCTL_REVIEW_ORIGINAL_PLAN_FILE"] = str(original_plan.path)
    env_map["ENVCTL_REVIEW_ORIGINAL_PLAN_SOURCE"] = original_plan.source

    result = run_process_fn(
        [str(helper), *args],
        cwd=str(context.repo_root),
        env=env_map,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        augment_review_output_dir(output_dir, original_plan=original_plan)
        short_summary_path = output_dir / "summary_short.txt"
        stats = parse_review_stats(short_summary_path)
        prune_review_output_dir(output_dir, keep_names={"summary.md", "all.md"})
        print_review_completion(
            context,
            mode=mode,
            scope=scope,
            output_dir=output_dir,
            summary_path=first_existing_path(output_dir / "summary.md", output_dir / "all.md"),
            all_in_one_path=output_dir / "all.md",
            stats=stats,
            tree_count=len(iterations),
        )
    else:
        print_review_failure(
            context,
            output_dir=output_dir,
            result=result,
        )
    return result.returncode


def tree_diffs_root(context: ReviewActionContext) -> Path:
    explicit = str(context.env.get("ENVCTL_ACTION_TREE_DIFFS_ROOT", "")).strip()
    if explicit:
        root = Path(explicit).expanduser()
    else:
        repo_hash = hashlib.sha256(str(context.repo_root.resolve()).encode("utf-8")).hexdigest()[:12]
        root = Path(tempfile.gettempdir()) / "envctl-tree-diffs" / repo_hash
    root.mkdir(parents=True, exist_ok=True)
    return root


def tree_diffs_output_path(
    context: ReviewActionContext,
    directory: str,
    prefix: str,
    label: str | None = None,
) -> Path:
    return timestamped_markdown_path(tree_diffs_root(context) / directory, prefix, label)
