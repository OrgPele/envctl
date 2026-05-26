from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from envctl_engine.planning.planning_files import planning_feature_name
from envctl_engine.planning.worktree_identity import worktree_project_name
from envctl_engine.planning.worktree_path_support import preferred_tree_root_for_feature


@dataclass(frozen=True, slots=True)
class PlanProjectPrediction:
    name: str
    root: Path
    plan_file: str
    action: str


def select_projects_for_plan_files(
    *,
    projects: list[tuple[str, Path]],
    plan_counts: OrderedDict[str, int],
) -> list[tuple[str, Path]]:
    if not plan_counts:
        return []

    selected: list[tuple[str, Path]] = []
    seen: set[str] = set()

    for plan_file, count in plan_counts.items():
        if count <= 0:
            continue
        feature = planning_feature_name(plan_file)
        candidates = _candidate_projects(projects, feature=feature)
        for name, root in candidates[:count]:
            dedupe_key = f"{name}|{root}"
            if dedupe_key in seen:
                continue
            selected.append((name, root))
            seen.add(dedupe_key)

    return selected


def predict_plan_projects(
    *,
    projects: list[tuple[str, Path]],
    plan_counts: OrderedDict[str, int],
    base_dir: Path,
    trees_dir_name: str,
) -> list[PlanProjectPrediction]:
    if not plan_counts:
        return []

    predictions: list[PlanProjectPrediction] = []
    seen: set[str] = set()

    for plan_file, count in plan_counts.items():
        if count <= 0:
            continue
        feature = planning_feature_name(plan_file)
        candidates = _candidate_projects(projects, feature=feature)
        for name, root in candidates[:count]:
            dedupe_key = f"{name}|{root}"
            if dedupe_key in seen:
                continue
            predictions.append(
                PlanProjectPrediction(
                    name=name,
                    root=Path(root),
                    plan_file=plan_file,
                    action="reuse",
                )
            )
            seen.add(dedupe_key)

        existing_iterations = _existing_feature_iterations(candidates, feature=feature)
        feature_root = preferred_tree_root_for_feature(
            base_dir=base_dir,
            trees_dir_name=trees_dir_name,
            feature=feature,
        )
        missing = max(0, count - len(candidates))
        for _ in range(missing):
            iteration = _next_available_iteration(existing_iterations)
            root = feature_root / str(iteration)
            name = worktree_project_name(feature=feature, iteration=iteration)
            dedupe_key = f"{name}|{root}"
            if dedupe_key in seen:
                existing_iterations.add(iteration)
                continue
            predictions.append(
                PlanProjectPrediction(
                    name=name,
                    root=root,
                    plan_file=plan_file,
                    action="create",
                )
            )
            seen.add(dedupe_key)
            existing_iterations.add(iteration)

    return predictions


def planning_existing_counts(
    *,
    projects: list[tuple[str, Path]],
    planning_files: list[str],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for plan_file in planning_files:
        feature = planning_feature_name(plan_file)
        count = 0
        for name, _root in projects:
            lowered = name.lower()
            if lowered == feature.lower() or lowered.startswith(f"{feature.lower()}-"):
                count += 1
        counts[plan_file] = count
    return counts


def _candidate_projects(projects: list[tuple[str, Path]], *, feature: str) -> list[tuple[str, Path]]:
    candidates = [
        project
        for project in projects
        if project[0].lower() == feature.lower() or project[0].lower().startswith(f"{feature.lower()}-")
    ]
    candidates.sort(key=lambda project: _project_sort_key(project[0], feature))
    return candidates


def _existing_feature_iterations(candidates: list[tuple[str, Path]], *, feature: str) -> set[int]:
    iterations: set[int] = set()
    prefix = f"{feature.lower()}-"
    for name, root in candidates:
        lowered = str(name).strip().lower()
        suffix = lowered[len(prefix) :] if lowered.startswith(prefix) else ""
        parsed = _parse_iteration_suffix(suffix)
        if parsed is not None:
            iterations.add(parsed)
            continue
        parsed = _parse_iteration_suffix(Path(root).name)
        if parsed is not None:
            iterations.add(parsed)
    return iterations


def _parse_iteration_suffix(value: str) -> int | None:
    normalized = str(value).strip().lower()
    if not normalized:
        return None
    if normalized.isdigit():
        return int(normalized)
    match = re.fullmatch(r"iter[-_]?(\d+)", normalized)
    if match:
        return int(match.group(1))
    return None


def _next_available_iteration(existing_iters: set[int]) -> int:
    candidate = 1
    while candidate in existing_iters:
        candidate += 1
    return candidate


def _project_sort_key(project_name: str, feature: str) -> tuple[int, object]:
    lowered = project_name.lower()
    feature_prefix = f"{feature.lower()}-"
    if lowered == feature.lower():
        return (0, 0)
    if not lowered.startswith(feature_prefix):
        return (3, lowered)
    suffix = lowered[len(feature_prefix) :]
    if suffix.isdigit():
        return (1, int(suffix))
    iter_match = re.fullmatch(r"iter[-_]?(\d+)", suffix)
    if iter_match:
        return (1, int(iter_match.group(1)))
    return (2, suffix)
