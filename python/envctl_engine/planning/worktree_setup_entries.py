from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from envctl_engine.shared.parsing import parse_int

RawProject = tuple[str, Path]


def coerce_setup_entries(
    *,
    flags: Mapping[str, object],
    flag_name: str,
    value_name: str,
) -> list[tuple[str, str]]:
    raw = flags.get(flag_name)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise RuntimeError(f"Invalid {flag_name} flag payload.")
    entries: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise RuntimeError(f"Invalid {flag_name} flag payload.")
        feature = str(item.get("feature", "")).strip()
        value = str(item.get(value_name, "")).strip()
        if not feature:
            raise RuntimeError(f"Missing feature for {flag_name}.")
        if "/" in feature or feature in {".", ".."}:
            raise RuntimeError(f"Invalid feature name for {flag_name}: {feature}")
        if not value:
            raise RuntimeError(f"Missing {value_name} for {flag_name}.")
        entries.append((feature, value))
    return entries


def resolve_included_setup_worktrees(
    *,
    raw_projects: list[RawProject],
    setup_features: list[str],
    selected_names: set[str],
    include_tokens: list[str],
) -> tuple[set[str], list[str]]:
    resolved_names = set(selected_names)
    project_lookup = {name.lower(): name for name, _root in raw_projects}
    missing: list[str] = []
    for token in include_tokens:
        direct = project_lookup.get(token.lower())
        if direct is not None:
            resolved_names.add(direct)
            continue
        resolved = None
        if token.isdigit():
            for feature in setup_features:
                candidate_name = f"{feature}-{token}"
                candidate = project_lookup.get(candidate_name.lower())
                if candidate is not None:
                    resolved = candidate
                    break
        if resolved is not None:
            resolved_names.add(resolved)
        else:
            missing.append(token)
    return resolved_names, missing


def apply_multi_setup_entry(
    *,
    feature: str,
    count_raw: str,
    raw_projects: list[RawProject],
    feature_project_candidates: Callable[..., list[RawProject]],
    update: Callable[[str], None],
    create_feature_worktrees: Callable[..., str | None],
    discover_tree_projects: Callable[[], list[RawProject]],
) -> tuple[list[RawProject], set[str]]:
    count = parse_int(count_raw, -1)
    if count < 1:
        raise RuntimeError(f"Invalid count for --setup-worktrees {feature}: {count_raw}")
    before = {name for name, _root in feature_project_candidates(projects=raw_projects, feature=feature)}
    update(f"Setting up {count} worktree(s) for {feature}...")
    create_error = create_feature_worktrees(
        feature=feature,
        count=count,
        plan_file=f"_setup/{feature}.md",
    )
    if create_error:
        raise RuntimeError(create_error)
    refreshed_projects = discover_tree_projects()
    candidates = feature_project_candidates(projects=refreshed_projects, feature=feature)
    after = {name for name, _root in candidates}
    created = after.difference(before)
    return refreshed_projects, (created or after)


def apply_single_setup_entry(
    *,
    feature: str,
    iteration_raw: str,
    raw_projects: list[RawProject],
    preferred_tree_root_for_feature: Callable[[str], Path],
    trees_root_for_worktree: Callable[[Path], Path],
    delete_worktree: Callable[..., tuple[bool, str]],
    create_single_worktree: Callable[..., str | None],
    discover_tree_projects: Callable[[], list[RawProject]],
    update: Callable[[str], None],
    repo_root: Path,
    process_runner: Any,
    setup_worktree_existing: bool,
    setup_worktree_recreate: bool,
    path_exists: Callable[[Path], bool] | None = None,
) -> tuple[list[RawProject], str]:
    del raw_projects
    if not iteration_raw.isdigit() or int(iteration_raw) < 1:
        raise RuntimeError(f"Invalid iteration for --setup-worktree {feature}: {iteration_raw}")
    iteration = str(int(iteration_raw))
    target_root = preferred_tree_root_for_feature(feature) / iteration
    exists = path_exists or Path.exists
    update(f"Ensuring worktree {feature}/{iteration}...")
    if exists(target_root):
        if setup_worktree_recreate:
            success, message = delete_worktree(
                repo_root=repo_root,
                trees_root=trees_root_for_worktree(target_root),
                worktree_root=target_root,
                process_runner=process_runner,
            )
            if not success:
                raise RuntimeError(message)
        elif not setup_worktree_existing:
            raise RuntimeError(
                f"Worktree {feature}/{iteration} already exists. "
                "Use --setup-worktree-existing or --setup-worktree-recreate."
            )
    if not exists(target_root):
        create_error = create_single_worktree(feature=feature, iteration=iteration)
        if create_error:
            raise RuntimeError(create_error)
    return discover_tree_projects(), f"{feature}-{iteration}"
