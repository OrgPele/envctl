from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GeneratedWorktreeIdentity:
    project_name: str
    branch_name: str
    selector: str
    path_segments: tuple[str, str]


def worktree_project_name(*, feature: str, iteration: str | int) -> str:
    return f"{str(feature).strip()}-{str(iteration).strip()}"


def generated_worktree_identity(*, feature: str, iteration: str | int) -> GeneratedWorktreeIdentity:
    project_name = worktree_project_name(feature=feature, iteration=iteration)
    return GeneratedWorktreeIdentity(
        project_name=project_name,
        branch_name=project_name,
        selector=project_name,
        path_segments=(str(feature).strip(), str(iteration).strip()),
    )
