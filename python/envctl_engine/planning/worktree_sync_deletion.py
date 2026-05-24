from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


def delete_feature_worktrees(
    *,
    feature: str,
    candidates: list[tuple[str, Path]],
    remove_count: int,
    project_sort_key_for_feature: Callable[[str, str], tuple[int, object]],
    active_protection_reason: Callable[..., str],
    blast_worktree_before_delete: Callable[..., object] | None,
    delete_worktree: Callable[..., object],
    repo_root: Path,
    trees_root_for_worktree: Callable[[Path], Path],
    process_runner: Any,
    emit: Callable[..., None],
) -> str | None:
    if remove_count <= 0:
        return None
    ordered = sorted(
        candidates,
        key=lambda item: project_sort_key_for_feature(item[0], feature),
        reverse=True,
    )
    deleted_count = 0
    for name, root in ordered:
        if deleted_count >= remove_count:
            break
        protection_reason = active_protection_reason(name=name, root=root)
        if protection_reason:
            emit(
                "planning.worktree.cleanup.skipped_active_ai_session",
                worktree=name,
                root=str(Path(root).resolve(strict=False)),
                reason=protection_reason,
            )
            continue
        if callable(blast_worktree_before_delete):
            warnings = blast_worktree_before_delete(
                project_name=name,
                project_root=root,
                source_command="blast-worktree",
            )
            if not isinstance(warnings, list):
                warnings = []
            for warning in warnings:
                emit(
                    "cleanup.worktree.warning",
                    project=name,
                    warning=warning,
                    source_command="blast-worktree",
                )
        result = delete_worktree(
            repo_root=repo_root,
            trees_root=trees_root_for_worktree(root),
            worktree_root=root,
            process_runner=process_runner,
        )
        if not bool(getattr(result, "success", False)):
            return str(getattr(result, "message", "") or "Failed to delete worktree.")
        deleted_count += 1
    return None
