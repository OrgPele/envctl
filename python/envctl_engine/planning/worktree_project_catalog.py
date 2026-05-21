from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from pathlib import Path


def project_sort_key_for_feature(project_name: str, feature: str) -> tuple[int, object]:
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


def feature_project_candidates(
    *,
    projects: Sequence[tuple[str, Path]],
    feature: str,
) -> list[tuple[str, Path]]:
    lowered_feature = feature.lower()
    prefix = f"{lowered_feature}-"
    candidates = [
        project
        for project in projects
        if project[0].lower() == lowered_feature or project[0].lower().startswith(prefix)
    ]
    candidates.sort(key=lambda item: project_sort_key_for_feature(item[0], feature))
    return candidates


def cleanup_empty_feature_root(
    *,
    preferred_tree_root_for_feature: Callable[[str], Path],
    feature: str,
) -> None:
    feature_root = preferred_tree_root_for_feature(feature)
    if not feature_root.is_dir():
        return
    try:
        next(feature_root.iterdir())
    except StopIteration:
        try:
            feature_root.rmdir()
        except OSError:
            return
