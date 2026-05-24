from __future__ import annotations


def worktree_project_name(*, feature: str, iteration: str | int) -> str:
    return f"{str(feature).strip()}-{str(iteration).strip()}"
