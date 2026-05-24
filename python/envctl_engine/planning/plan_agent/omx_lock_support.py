from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

from envctl_engine.planning.plan_agent.constants import (
    _OMX_TMUX_EXTENDED_KEYS_RELATIVE_PATH,
    _OMX_TMUX_LOCK_STALE_SECONDS,
)


def cleanup_stale_omx_tmux_locks(runtime: Any, *, worktree_root: Path, omx_root: Path | None = None) -> None:
    roots = [Path(worktree_root).resolve()]
    if omx_root is not None:
        resolved_omx_root = Path(omx_root).expanduser().resolve(strict=False)
        if resolved_omx_root not in roots:
            roots.insert(0, resolved_omx_root)
    removed_roots: list[str] = []
    for root in roots:
        if cleanup_stale_omx_tmux_locks_under_root(root):
            removed_roots.append(str(root))
    if removed_roots:
        runtime._emit(
            "planning.agent_launch.omx_lock_cleanup",
            worktree=str(Path(worktree_root).resolve()),
            transport="omx",
        )


def cleanup_stale_omx_tmux_locks_under_root(root: Path) -> bool:
    lock_root = Path(root).resolve() / _OMX_TMUX_EXTENDED_KEYS_RELATIVE_PATH
    if not lock_root.is_dir():
        return False
    removed_any = False
    now = time.time()
    for child in lock_root.iterdir():
        if not child.name.endswith(".lock"):
            continue
        try:
            age_seconds = max(0.0, now - child.stat().st_mtime)
        except OSError:
            continue
        if age_seconds < _OMX_TMUX_LOCK_STALE_SECONDS:
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
            removed_any = True
            continue
        try:
            child.unlink()
        except OSError:
            continue
        removed_any = True
    return removed_any
