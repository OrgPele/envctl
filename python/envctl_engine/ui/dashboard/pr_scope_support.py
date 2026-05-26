from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, cast

from envctl_engine.actions.project_action_domain import (
    DirtyWorktreeReport,
    probe_dirty_worktree,
    resolve_git_root,
)
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState


def dirty_pr_reports(
    owner: Any,
    route: Route,
    state: RunState,
    runtime: Any,
    *,
    probe_dirty_worktree_fn: Callable[..., DirtyWorktreeReport] = probe_dirty_worktree,
) -> list[DirtyWorktreeReport]:
    repo_root = repo_root_from_runtime(runtime)
    project_roots = project_roots_for_route(owner, route, state, runtime)
    reports_by_git_root: dict[str, DirtyWorktreeReport] = {}
    for project_name in route.projects or []:
        project_root = project_roots.get(project_name)
        if project_root is None:
            continue
        report = probe_dirty_worktree_fn(project_root, repo_root, project_name=project_name)
        git_root_key = str(report.git_root.resolve())
        if git_root_key not in reports_by_git_root:
            reports_by_git_root[git_root_key] = report
    return list(reports_by_git_root.values())


def dedupe_route_projects_by_git_root(
    owner: Any,
    route: Route,
    state: RunState,
    rt: object,
    *,
    resolve_git_root_fn: Callable[[Path, Path], Path] = resolve_git_root,
) -> Route:
    runtime_any = cast(Any, rt)
    if len(route.projects) <= 1:
        return route
    repo_root = repo_root_from_runtime(runtime_any)
    project_roots = project_roots_for_route(owner, route, state, runtime_any)
    unique_projects: list[str] = []
    seen_git_roots: set[str] = set()
    collapsed = False
    for project_name in route.projects:
        project_root = project_roots.get(project_name)
        if project_root is None:
            unique_projects.append(project_name)
            continue
        git_root = resolve_git_root_fn(project_root, repo_root)
        git_root_key = str(git_root.resolve())
        if git_root_key in seen_git_roots:
            collapsed = True
            continue
        seen_git_roots.add(git_root_key)
        unique_projects.append(project_name)
    if collapsed:
        route.projects = unique_projects
        runtime_any._emit(
            "dashboard.pr_target_scope.deduped_git_roots",
            command="pr",
            original_project_count=len(project_roots) if project_roots else len(route.projects),
            deduped_project_count=len(unique_projects),
            projects=list(unique_projects),
        )
    return route


def repo_root_from_runtime(runtime: Any) -> Path:
    base_dir = getattr(getattr(runtime, "config", None), "base_dir", Path.cwd())
    return Path(str(base_dir)).resolve()


def project_roots_for_route(owner: Any, route: Route, state: RunState, runtime: Any) -> dict[str, Path]:
    _ = owner
    repo_root = repo_root_from_runtime(runtime)
    metadata = state.metadata if isinstance(state.metadata, dict) else {}
    raw_project_roots = metadata.get("project_roots")
    project_roots: dict[str, Path] = {}
    if isinstance(raw_project_roots, dict):
        for name, root in raw_project_roots.items():
            project_name = str(name).strip()
            root_raw = str(root or "").strip()
            if not project_name or not root_raw:
                continue
            resolved = Path(root_raw)
            if not resolved.is_absolute():
                resolved = repo_root / resolved
            project_roots[project_name] = resolved.resolve()
    for project_name in route.projects or []:
        if project_name in project_roots:
            continue
        if str(project_name).strip().casefold() == "main":
            project_roots[project_name] = repo_root
    return project_roots


def pr_git_root(
    owner: Any,
    runtime: Any,
    *,
    resolve_git_root_fn: Callable[[Path, Path], Path] = resolve_git_root,
) -> Path:
    _ = owner
    base_dir = getattr(getattr(runtime, "config", None), "base_dir", None)
    if isinstance(base_dir, Path):
        return resolve_git_root_fn(base_dir, base_dir)
    if isinstance(base_dir, str) and base_dir.strip():
        candidate = Path(base_dir).resolve()
        return resolve_git_root_fn(candidate, candidate)
    return Path.cwd()
