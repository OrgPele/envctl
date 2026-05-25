from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Callable, Mapping

WORKTREE_PROVENANCE_SCHEMA_VERSION = 1
WORKTREE_PROVENANCE_PATH = Path(".envctl-state") / "worktree-provenance.json"


@dataclass(frozen=True, slots=True)
class ReviewBaseResolution:
    base_branch: str
    base_ref: str
    source: str
    merge_base: str


class ReviewBaseResolutionError(RuntimeError):
    """Raised when envctl cannot determine a usable review base."""


def resolve_review_base(
    context: object,
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
