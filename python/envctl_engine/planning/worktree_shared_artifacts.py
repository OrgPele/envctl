from __future__ import annotations

import os
from pathlib import Path


def link_repo_local_shared_artifacts(*, repo_root: Path, target: Path) -> None:
    if not target.is_dir():
        return
    # Compatibility links are intentionally limited to setup-worktree and placeholder fallback paths.
    # Plan-agent launches prepare per-worktree dependencies before prompt submission instead of relying
    # on shared repo-local node_modules/venv artifacts that can go stale across branches.
    link_specs = (
        ("backend/venv", repo_root / "backend" / "venv"),
        ("backend/.env", repo_root / "backend" / ".env"),
        ("frontend/node_modules", repo_root / "frontend" / "node_modules"),
    )
    for relative_target, source_path in link_specs:
        if not source_path.exists():
            continue
        worktree_path = target / relative_target
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        if os.path.lexists(worktree_path):
            try:
                if worktree_path.is_symlink() and worktree_path.resolve() == source_path.resolve():
                    continue
            except OSError:
                pass
            if worktree_path.is_symlink():
                try:
                    worktree_path.unlink()
                except OSError:
                    continue
            else:
                continue
        try:
            worktree_path.symlink_to(source_path)
        except OSError:
            continue
