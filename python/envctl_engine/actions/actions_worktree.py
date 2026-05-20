from __future__ import annotations

import json
import os
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


WORKTREE_CODE_INTELLIGENCE_PATH = Path(".envctl-state") / "code-intelligence.json"


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

    cgc_cleanup_message = _delete_worktree_cgc_context(
        worktree_root=resolved_target,
        process_runner=process_runner,
    )

    completed = process_runner.run(
        ["git", "-C", str(resolved_repo), "worktree", "remove", "--force", str(resolved_target)],
        cwd=resolved_repo,
        timeout=30.0,
    )
    if getattr(completed, "returncode", 1) == 0:
        return WorktreeDeleteResult(
            True,
            _with_cgc_cleanup_message(f"removed via git worktree: {resolved_target}", cgc_cleanup_message),
        )

    stderr = str(getattr(completed, "stderr", "") or "").strip()
    stdout = str(getattr(completed, "stdout", "") or "").strip()
    error = stderr or stdout or "git worktree remove failed"
    try:
        shutil.rmtree(resolved_target)
    except OSError as exc:
        return WorktreeDeleteResult(
            False,
            _with_cgc_cleanup_message(f"{error}; fallback remove failed: {exc}", cgc_cleanup_message),
        )
    return WorktreeDeleteResult(
        True,
        _with_cgc_cleanup_message(f"{error}; fallback removed: {resolved_target}", cgc_cleanup_message),
    )


def _with_cgc_cleanup_message(message: str, cgc_cleanup_message: str | None) -> str:
    if not cgc_cleanup_message:
        return message
    return f"{message}; {cgc_cleanup_message}"


def _delete_worktree_cgc_context(
    *,
    worktree_root: Path,
    process_runner: _ProcessRunnerProtocol,
) -> str | None:
    context = _worktree_cgc_context_from_metadata(worktree_root)
    if not context:
        return None
    env = dict(os.environ)
    env["ENVCTL_CGC_CONTEXT_TO_DELETE"] = context
    try:
        result = process_runner.run(
            ["sh", "-c", "printf 'y\\n' | cgc context delete \"$ENVCTL_CGC_CONTEXT_TO_DELETE\""],
            cwd=worktree_root,
            env=env,
            timeout=60.0,
        )
    except OSError as exc:
        return f"CGC context cleanup failed for {context}: {exc}"
    if getattr(result, "returncode", 1) == 0:
        return f"CGC context deleted: {context}"
    stderr = str(getattr(result, "stderr", "") or "").strip()
    stdout = str(getattr(result, "stdout", "") or "").strip()
    detail = stderr or stdout or "cgc context delete failed"
    return f"CGC context cleanup failed for {context}: {detail}"


def _worktree_cgc_context_from_metadata(worktree_root: Path) -> str:
    metadata_path = worktree_root / WORKTREE_CODE_INTELLIGENCE_PATH
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if payload.get("cgc_context_managed") is False:
        return ""
    context = str(payload.get("cgc_context") or "").strip()
    return context
