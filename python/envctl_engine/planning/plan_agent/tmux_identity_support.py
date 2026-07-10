from __future__ import annotations

from pathlib import Path
from typing import Any

from envctl_engine.runtime.codex_tmux_support import (
    _sanitize_name as _sanitize_tmux_name,
    _tmux_session_exists,
)

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree
from envctl_engine.planning.plan_agent.workflow_build import _tab_title_for_worktree


def tmux_session_name_for_worktree(repo_root: Path, worktree: CreatedPlanWorktree, *, cli: str) -> str:
    repo_root = Path(repo_root).resolve()
    worktree_root = Path(worktree.root).resolve()
    relative = worktree_root.relative_to(repo_root)
    relative_slug = _sanitize_tmux_name(str(relative), fallback=worktree.name)
    cli_slug = _sanitize_tmux_name(str(cli).strip().lower(), fallback="cli")
    return _sanitize_tmux_name(f"envctl-{repo_root.name}-{relative_slug}-{cli_slug}", fallback="envctl-worktree")


def next_available_tmux_session_name(runtime: Any, session_name: str) -> str:
    if not _tmux_session_exists(runtime, session_name):
        return session_name
    index = 2
    while True:
        candidate = _sanitize_tmux_name(f"{session_name}-{index}", fallback=session_name)
        if not _tmux_session_exists(runtime, candidate):
            return candidate
        index += 1


def tmux_window_name_for_worktree(worktree: CreatedPlanWorktree) -> str:
    return _sanitize_tmux_name(_tab_title_for_worktree(worktree.name), fallback="implementation")


__all__ = tuple(name for name in globals() if not name.startswith("__"))
