from __future__ import annotations

import re
import subprocess
from pathlib import Path

from envctl_engine.planning.worktree_identity import worktree_project_name

OMX_ARTIFACT_DIR_NAME = ".omx"
ENVCTL_STATE_DIR_NAME = ".envctl-state"
STATE_ONLY_TREE_PROJECT_ROOT_ENTRIES = frozenset({OMX_ARTIFACT_DIR_NAME, ENVCTL_STATE_DIR_NAME})
_ITERATION_RE = re.compile(r"^(?:\d+|iter[-_]?\d+)$", re.IGNORECASE)
_IGNORED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    OMX_ARTIFACT_DIR_NAME,
    ENVCTL_STATE_DIR_NAME,
    "venv",
    "__pycache__",
    "node_modules",
    "src",
    "dist",
    "build",
    "backend",
    "frontend",
}


def discover_tree_projects(base_dir: Path, trees_dir_name: str) -> list[tuple[str, Path]]:
    tree_roots = _discover_tree_roots(base_dir, trees_dir_name)
    if not tree_roots:
        return []

    projects: list[tuple[str, Path]] = []
    seen: set[str] = set()
    normalized = trees_dir_name.strip().rstrip("/")
    flat_prefix = f"{Path(normalized).name}-" if normalized else "trees-"

    for tree_root in tree_roots:
        root_name = tree_root.name
        if root_name.startswith(flat_prefix):
            feature_name = root_name[len(flat_prefix) :].strip()
            if feature_name and not _is_ignored(feature_name):
                _append_feature_projects(projects, seen, feature_name, tree_root)
            continue

        children = sorted(path for path in tree_root.iterdir() if path.is_dir())
        for feature_dir in children:
            if _is_ignored(feature_dir.name):
                continue
            _append_feature_projects(projects, seen, feature_dir.name, feature_dir)

    return sorted(projects, key=lambda item: item[0])


def filter_projects_for_plan(
    projects: list[tuple[str, Path]],
    passthrough_args: list[str],
    *,
    strict_no_match: bool = False,
) -> list[tuple[str, Path]]:
    selectors: list[str] = []
    for token in passthrough_args:
        if token.startswith("-"):
            continue
        for part in token.split(","):
            normalized = part.strip().lower()
            if normalized:
                selectors.append(normalized)
    if not selectors:
        return projects

    filtered = [project for project in projects if any(sel in project[0].lower() for sel in selectors)]
    if filtered:
        return filtered
    return [] if strict_no_match else projects


def _discover_tree_roots(base_dir: Path, trees_dir_name: str) -> list[Path]:
    normalized = trees_dir_name.strip().rstrip("/")
    if not normalized:
        return []

    roots: list[Path] = []
    if Path(normalized).is_absolute():
        absolute = Path(normalized)
        if absolute.is_dir():
            roots.append(absolute)
        return roots

    direct = base_dir / normalized
    if direct.is_dir():
        roots.append(direct)

    for candidate in sorted(base_dir.glob(f"{normalized}-*")):
        if candidate.is_dir():
            roots.append(candidate)
    return roots


def _append_feature_projects(
    projects: list[tuple[str, Path]],
    seen: set[str],
    feature_name: str,
    feature_dir: Path,
) -> None:
    nested_iters = sorted(
        path
        for path in feature_dir.iterdir()
        if path.is_dir() and _is_iteration_name(path.name) and not _is_ignored(path.name)
    )
    if nested_iters:
        for iter_dir in nested_iters:
            if not _looks_like_tree_project_root(iter_dir):
                continue
            project_name = _branch_project_name_for_worktree(iter_dir) or worktree_project_name(
                feature=feature_name,
                iteration=iter_dir.name,
            )
            _append_project(projects, seen, project_name, iter_dir)
        return

    direct_child_worktrees = sorted(
        path
        for path in feature_dir.iterdir()
        if path.is_dir()
        and not _is_ignored(path.name)
        and (path / ".git").exists()
        and _looks_like_tree_project_root(path)
    )
    for child_dir in direct_child_worktrees:
        project_name = _branch_project_name_for_worktree(child_dir) or "_".join(
            part for part in (_slugify_underscore(feature_name), _slugify_underscore(child_dir.name)) if part
        )
        if project_name:
            _append_project(projects, seen, project_name, child_dir)
    if direct_child_worktrees and not (feature_dir / ".git").exists():
        return

    if _append_direct_child_worktree_projects(projects, seen, feature_dir):
        return

    if not _looks_like_tree_project_root(feature_dir):
        return
    project_name = _branch_project_name_for_worktree(feature_dir) or feature_name
    _append_project(projects, seen, project_name, feature_dir)


def _append_project(projects: list[tuple[str, Path]], seen: set[str], project_name: str, project_root: Path) -> None:
    dedupe_key = f"{project_name}|{project_root.resolve()}"
    if dedupe_key in seen:
        return
    seen.add(dedupe_key)
    projects.append((project_name, project_root))


def _append_direct_child_worktree_projects(
    projects: list[tuple[str, Path]],
    seen: set[str],
    feature_dir: Path,
) -> bool:
    appended = False
    for child in sorted(path for path in feature_dir.iterdir() if path.is_dir() and not _is_ignored(path.name)):
        if not (child / ".git").exists():
            continue
        if not _looks_like_tree_project_root(child):
            continue
        project_name = _branch_project_name_for_worktree(child) or child.name
        dedupe_key = f"{project_name}|{child.resolve()}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        projects.append((project_name, child))
        appended = True
    return appended


def _branch_project_name_for_worktree(worktree_root: Path) -> str | None:
    if not (worktree_root / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=worktree_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError, Exception):
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    if not branch or branch == "HEAD":
        return None
    return branch


def _looks_like_tree_project_root(path: Path) -> bool:
    try:
        entries = list(path.iterdir())
    except OSError:
        return False
    entry_names = {entry.name for entry in entries}
    if entry_names and entry_names.issubset(STATE_ONLY_TREE_PROJECT_ROOT_ENTRIES):
        return False
    return True


def _is_iteration_name(name: str) -> bool:
    return bool(_ITERATION_RE.match(name.strip()))


def _is_ignored(name: str) -> bool:
    return name.strip().lower() in _IGNORED_DIR_NAMES


def _slugify_underscore(value: str) -> str:
    lowered = value.strip().lower()
    chars = [char if char.isalnum() else "_" for char in lowered]
    slug = "_".join(part for part in "".join(chars).split("_") if part)
    return slug
