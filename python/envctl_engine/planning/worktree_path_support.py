from __future__ import annotations

from pathlib import Path
from typing import Any

from envctl_engine.runtime.command_router import Route
from envctl_engine.ui.path_links import render_path_fragment_for_terminal


def preferred_tree_root_for_feature(*, base_dir: Path, trees_dir_name: str, feature: str) -> Path:
    normalized = str(trees_dir_name).strip().rstrip("/")
    if not normalized:
        return base_dir / "trees" / feature
    flat_candidate = base_dir / f"{normalized}-{feature}"
    if flat_candidate.is_dir():
        return flat_candidate
    return base_dir / normalized / feature


def trees_root_for_worktree(*, base_dir: Path, trees_dir_name: str, worktree_root: Path) -> Path:
    normalized = str(trees_dir_name).strip().rstrip("/")
    nested_root = base_dir / (normalized or "trees")
    flat_parent = nested_root.parent.resolve()
    flat_prefix = f"{Path(normalized).name}-" if normalized else "trees-"
    resolved_target = worktree_root.resolve()
    resolved_nested = nested_root.resolve()
    if resolved_nested == resolved_target or resolved_nested in resolved_target.parents:
        return nested_root

    current = resolved_target
    while current != flat_parent and flat_parent in current.parents:
        if current.parent == flat_parent and current.name.startswith(flat_prefix):
            return current
        current = current.parent
    return nested_root


def planning_root(*, planning_dir: Path) -> Path:
    return planning_dir


def planning_done_root(*, planning_dir: Path) -> Path:
    return planning_root(planning_dir=planning_dir).parent / "done"


def render_planning_path(
    *,
    absolute_path: Path,
    display_text: str,
    env: dict[str, str],
    stream: Any,
    interactive_tty: bool | None = None,
) -> str:
    return render_path_fragment_for_terminal(
        absolute_path,
        display_text=display_text,
        env=env,
        stream=stream,
        interactive_tty=interactive_tty,
    )


def setup_worktree_requested(route: Route) -> bool:
    return bool(route.flags.get("setup_worktrees")) or bool(route.flags.get("setup_worktree"))


def resolve_planning_selection_target(
    *,
    target_token: str,
    planning_files: list[str],
    planning_dir: Path,
    base_dir: Path,
) -> str:
    token = target_token.strip()
    if not token:
        raise ValueError("Missing planning selection target.")
    if token.isdigit():
        index = int(token)
        if 1 <= index <= len(planning_files):
            return planning_files[index - 1]
        raise ValueError(f"Invalid plan index: {token}")

    normalized = token.replace("\\", "/").lstrip("./")
    planning_raw = str(planning_dir).replace("\\", "/").rstrip("/")
    base_raw = str(base_dir).replace("\\", "/").rstrip("/")
    if normalized.startswith(f"{planning_raw}/"):
        normalized = normalized[len(planning_raw) + 1 :]
    if normalized.startswith(f"{base_raw}/"):
        normalized = normalized[len(base_raw) + 1 :]
    planning_rel = ""
    try:
        planning_rel = str(planning_dir.relative_to(base_dir)).replace("\\", "/").rstrip("/")
    except ValueError:
        planning_rel = ""
    if planning_rel and normalized.startswith(f"{planning_rel}/"):
        normalized = normalized[len(planning_rel) + 1 :]
    if not normalized.endswith(".md"):
        normalized = f"{normalized}.md"

    if normalized in planning_files:
        return normalized
    basename_matches = [plan for plan in planning_files if Path(plan).name == Path(normalized).name]
    if len(basename_matches) == 1:
        return basename_matches[0]
    if len(basename_matches) > 1:
        raise ValueError(f"Planning file name '{target_token}' is ambiguous. Use folder/name.")
    raise ValueError(f"Planning file not found: {target_token}")
