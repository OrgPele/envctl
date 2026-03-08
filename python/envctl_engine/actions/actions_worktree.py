from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class _ProcessRunnerProtocol(Protocol):
    def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
        ...


@dataclass(slots=True)
class WorktreeDeleteResult:
    success: bool
    message: str


def delete_worktree_path(
    *,
    repo_root: Path,
    trees_root: Path,
    worktree_root: Path,
    process_runner: _ProcessRunnerProtocol,
    dry_run: bool = False,
) -> WorktreeDeleteResult:
    resolved_repo = repo_root.resolve()
    resolved_trees = trees_root.resolve()
    resolved_target = worktree_root.resolve()

    if resolved_repo not in resolved_trees.parents and resolved_trees != resolved_repo:
        return WorktreeDeleteResult(False, f"invalid trees root: {resolved_trees}")
    if resolved_trees not in resolved_target.parents:
        return WorktreeDeleteResult(False, f"refusing to delete non-tree path: {resolved_target}")
    if not resolved_target.exists():
        return WorktreeDeleteResult(True, f"already removed: {resolved_target}")
    if dry_run:
        return WorktreeDeleteResult(True, f"dry-run: {resolved_target}")

    completed = process_runner.run(
        ["git", "-C", str(resolved_repo), "worktree", "remove", "--force", str(resolved_target)],
        cwd=resolved_repo,
        timeout=30.0,
    )
    if getattr(completed, "returncode", 1) == 0:
        return WorktreeDeleteResult(True, f"removed via git worktree: {resolved_target}")

    stderr = str(getattr(completed, "stderr", "") or "").strip()
    stdout = str(getattr(completed, "stdout", "") or "").strip()
    error = stderr or stdout or "git worktree remove failed"
    try:
        shutil.rmtree(resolved_target)
    except OSError as exc:
        return WorktreeDeleteResult(False, f"{error}; fallback remove failed: {exc}")
    return WorktreeDeleteResult(True, f"{error}; fallback removed: {resolved_target}")
