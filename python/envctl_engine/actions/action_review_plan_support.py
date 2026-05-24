from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any, Callable, Mapping

from envctl_engine.actions.action_review_output_support import (
    parse_review_stats,
    print_review_completion,
    print_review_failure,
    prune_review_output_dir,
)
from envctl_engine.planning import planning_feature_name

WORKTREE_PROVENANCE_SCHEMA_VERSION = 1
WORKTREE_PROVENANCE_PATH = Path(".envctl-state") / "worktree-provenance.json"
PLANNING_ROOT = Path("todo") / "plans"
DONE_PLANNING_ROOT = Path("todo") / "done"


@dataclass(frozen=True, slots=True)
class ReviewBaseResolution:
    base_branch: str
    base_ref: str
    source: str
    merge_base: str


class ReviewBaseResolutionError(RuntimeError):
    """Raised when envctl cannot determine a usable review base."""


@dataclass(frozen=True, slots=True)
class OriginalPlanResolution:
    path: Path | None
    source: str


def resolve_original_plan(context: Any) -> OriginalPlanResolution:
    if context.project_root.resolve() == context.repo_root.resolve():
        return OriginalPlanResolution(path=None, source="not_applicable")

    provenance = read_worktree_provenance(context.project_root)
    recorded_plan = str(provenance.get("plan_file", "")).strip()
    resolved = resolve_plan_file_from_record(provenance_root=context.repo_root, recorded_plan=recorded_plan)
    if resolved is not None:
        return OriginalPlanResolution(path=resolved, source="provenance")

    inferred = infer_original_plan_file(
        context.repo_root,
        feature_name=feature_name_from_project_name(context.project_name),
    )
    if inferred is not None:
        return OriginalPlanResolution(path=inferred, source="feature_inference")
    return OriginalPlanResolution(path=None, source="unresolved")


def read_worktree_provenance(project_root: Path) -> dict[str, object]:
    path = project_root / WORKTREE_PROVENANCE_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def resolve_plan_file_from_record(*, provenance_root: Path, recorded_plan: str) -> Path | None:
    normalized = str(recorded_plan or "").strip()
    if not normalized:
        return None
    relative = Path(normalized.replace("\\", "/").lstrip("./"))
    for root in (PLANNING_ROOT, DONE_PLANNING_ROOT):
        candidate = provenance_root / root / relative
        if candidate.is_file():
            return candidate.resolve()
    return None


def infer_original_plan_file(repo_root: Path, *, feature_name: str) -> Path | None:
    normalized_feature = str(feature_name).strip()
    if not normalized_feature:
        return None
    matches: list[Path] = []
    for root in (PLANNING_ROOT, DONE_PLANNING_ROOT):
        planning_root = repo_root / root
        if not planning_root.is_dir():
            continue
        for candidate in sorted(planning_root.glob("*/*.md")):
            if candidate.name == "README.md":
                continue
            relative = candidate.relative_to(planning_root)
            if planning_feature_name(str(relative).replace("\\", "/")) != normalized_feature:
                continue
            matches.append(candidate.resolve())
    if len(matches) == 1:
        return matches[0]
    return None


def feature_name_from_project_name(project_name: str) -> str:
    normalized = str(project_name).strip()
    return re.sub(r"-\d+$", "", normalized)


def original_plan_markdown_lines(resolution: OriginalPlanResolution, *, include_contents: bool) -> list[str]:
    resolved_path = str(resolution.path) if resolution.path is not None else "(unresolved)"
    lines = [
        "## Original plan file",
        resolved_path,
        "",
        "## Original plan resolution",
        resolution.source,
        "",
    ]
    if include_contents:
        plan_text = read_text(resolution.path) if resolution.path is not None else ""
        lines.extend(
            [
                "## Original plan",
                plan_text or "(unavailable)",
                "",
            ]
        )
    return lines


def augment_review_output_dir(output_dir: Path, *, original_plan: OriginalPlanResolution) -> None:
    augment_review_markdown_file(output_dir / "all.md", original_plan=original_plan, include_contents=True)
    augment_review_markdown_file(output_dir / "summary.md", original_plan=original_plan, include_contents=False)


def augment_review_markdown_file(path: Path, *, original_plan: OriginalPlanResolution, include_contents: bool) -> None:
    if not path.is_file():
        return
    original_text = read_text(path)
    if not original_text:
        return
    if "## Original plan file" in original_text:
        return
    metadata_block = "\n".join(original_plan_markdown_lines(original_plan, include_contents=include_contents)).strip()
    if not metadata_block:
        return
    lines = original_text.splitlines()
    if lines and lines[0].startswith("# "):
        title = lines[0]
        remainder = "\n".join(lines[1:]).strip()
        rewritten = f"{title}\n\n{metadata_block}\n\n{remainder}".rstrip() + "\n"
    else:
        rewritten = f"{metadata_block}\n\n{original_text.strip()}".rstrip() + "\n"
    atomic_write(path, rewritten)


def resolve_analyze_mode(context: Any) -> str:
    explicit = str(context.env.get("ENVCTL_ANALYZE_MODE", "")).strip().lower()
    if explicit in {"single", "grouped"}:
        return explicit
    return "single"


def resolve_review_base(
    context: Any,
    git_root: Path,
    *,
    detect_default_branch_fn: Callable[[Path], str],
    git_output_fn: Callable[[Path, list[str]], str],
) -> ReviewBaseResolution:
    explicit = str(context.env.get("ENVCTL_REVIEW_BASE", "")).strip()
    if explicit:
        resolved = resolve_review_base_candidate(
            git_root,
            base_branch=explicit,
            source="explicit",
            git_output_fn=git_output_fn,
        )
        if resolved is None:
            raise ReviewBaseResolutionError(
                f"Review base '{explicit}' could not be resolved. "
                + "Supply --review-base <branch> with an existing branch."
            )
        return resolved

    if context.project_root.resolve() != context.repo_root.resolve():
        provenance = load_worktree_provenance(context.project_root)
        resolved = resolve_provenance_review_base(git_root, provenance, git_output_fn=git_output_fn)
        if resolved is not None:
            return resolved

    resolved = resolve_upstream_review_base(git_root, git_output_fn=git_output_fn)
    if resolved is not None:
        return resolved

    default_branch = detect_default_branch_fn(git_root).strip()
    resolved = resolve_review_base_candidate(
        git_root,
        base_branch=default_branch,
        source="default_branch",
        git_output_fn=git_output_fn,
    )
    if resolved is not None:
        return resolved
    raise ReviewBaseResolutionError("Unable to resolve a review base automatically. Supply --review-base <branch>.")


def resolve_provenance_review_base(
    git_root: Path,
    provenance: Mapping[str, object] | None,
    *,
    git_output_fn: Callable[[Path, list[str]], str],
) -> ReviewBaseResolution | None:
    if not provenance:
        return None
    source_branch = str(provenance.get("source_branch", "")).strip()
    source_ref = str(provenance.get("source_ref", "")).strip()
    if source_branch:
        return resolve_review_base_candidate(
            git_root,
            base_branch=source_branch,
            source="provenance",
            preferred_ref=source_ref,
            git_output_fn=git_output_fn,
        )
    if source_ref:
        return resolve_review_base_candidate(
            git_root,
            base_branch=branch_name_from_ref(source_ref),
            source="provenance",
            preferred_ref=source_ref,
            git_output_fn=git_output_fn,
        )
    return None


def resolve_upstream_review_base(
    git_root: Path,
    *,
    git_output_fn: Callable[[Path, list[str]], str],
) -> ReviewBaseResolution | None:
    head_branch = git_output_fn(git_root, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if not head_branch or head_branch == "HEAD":
        return None
    upstream_ref = git_output_fn(git_root, ["rev-parse", "--abbrev-ref", f"{head_branch}@{{upstream}}"]).strip()
    if not upstream_ref or upstream_ref == "HEAD":
        return None
    return resolve_review_base_candidate(
        git_root,
        base_branch=branch_name_from_ref(upstream_ref),
        source="upstream",
        preferred_ref=upstream_ref,
        git_output_fn=git_output_fn,
    )


def resolve_review_base_candidate(
    git_root: Path,
    *,
    base_branch: str,
    source: str,
    git_output_fn: Callable[[Path, list[str]], str],
    preferred_ref: str = "",
) -> ReviewBaseResolution | None:
    normalized_branch = branch_name_from_ref(base_branch)
    base_ref = resolve_review_base_ref(
        git_root,
        base_branch=base_branch,
        preferred_ref=preferred_ref,
        git_output_fn=git_output_fn,
    )
    if not base_ref:
        return None
    merge_base = git_output_fn(git_root, ["merge-base", "HEAD", base_ref]).strip()
    return ReviewBaseResolution(
        base_branch=normalized_branch or base_branch.strip(),
        base_ref=base_ref,
        source=source,
        merge_base=merge_base,
    )


def resolve_review_base_ref(
    git_root: Path,
    *,
    base_branch: str,
    git_output_fn: Callable[[Path, list[str]], str],
    preferred_ref: str = "",
) -> str:
    branch = base_branch.strip()
    candidates: list[str] = []
    for candidate in (
        preferred_ref.strip(),
        branch,
        "" if not branch or branch.startswith("origin/") else f"origin/{branch}",
        "" if not branch.startswith("origin/") else branch.split("origin/", 1)[1],
    ):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    for candidate in candidates:
        if git_output_fn(git_root, ["rev-parse", "--verify", candidate]).strip():
            return candidate
    return ""


def branch_name_from_ref(ref: str) -> str:
    cleaned = ref.strip()
    if cleaned.startswith("origin/"):
        return cleaned.split("origin/", 1)[1]
    return cleaned


def load_worktree_provenance(project_root: Path) -> Mapping[str, object] | None:
    path = project_root / WORKTREE_PROVENANCE_PATH
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(loaded, dict):
        return None
    schema_version = int(loaded.get("schema_version", 0) or 0)
    if schema_version > WORKTREE_PROVENANCE_SCHEMA_VERSION:
        return None
    return loaded


def analysis_iterations(context: Any, *, mode: str) -> list[str]:
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
    context: Any,
    helper: Path,
    iterations: list[str],
    mode: str,
    scope: str,
    review_base: ReviewBaseResolution | None,
    original_plan: OriginalPlanResolution,
    sanitize_label_fn: Callable[[str], str],
    run_process_fn: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> int:
    project_root = context.project_root.resolve()
    family_dir = project_family_dir(project_root)
    if family_dir is None:
        return 1

    approach = "combine" if mode == "grouped" and len(iterations) > 1 else "optimal"
    output_dir = tree_diffs_root(context) / (
        f"analysis_{sanitize_label_fn(context.project_name)}_{sanitize_label_fn(scope)}_{mode}_"
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


def tree_diffs_root(context: Any) -> Path:
    explicit = str(context.env.get("ENVCTL_ACTION_TREE_DIFFS_ROOT", "")).strip()
    if explicit:
        root = Path(explicit).expanduser()
    else:
        repo_hash = hashlib.sha256(str(context.repo_root.resolve()).encode("utf-8")).hexdigest()[:12]
        root = Path(tempfile.gettempdir()) / "envctl-tree-diffs" / repo_hash
    root.mkdir(parents=True, exist_ok=True)
    return root


def tree_diffs_output_path(
    context: Any,
    directory: str,
    prefix: str,
    label: str | None = None,
    *,
    sanitize_label_fn: Callable[[str], str],
) -> Path:
    output_dir = tree_diffs_root(context) / directory
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
    if label:
        return output_dir / f"{prefix}_{sanitize_label_fn(label)}_{timestamp}.md"
    return output_dir / f"{prefix}_{timestamp}.md"


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        Path(temp_name).replace(path)
    finally:
        try:
            if Path(temp_name).exists():
                Path(temp_name).unlink()
        except OSError:
            pass


def first_existing_path(*paths: Path) -> Path:
    for path in paths:
        if path.is_file():
            return path
    return paths[0]
