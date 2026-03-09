from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path

_ITERATION_RE = re.compile(r"^(?:\d+|iter[-_]?\d+)$", re.IGNORECASE)
_IGNORED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "src",
    "dist",
    "build",
    "backend",
    "frontend",
}


def list_planning_files(planning_dir: Path) -> list[str]:
    if not planning_dir.is_dir():
        return []

    files: list[str] = []
    for group_dir in sorted(path for path in planning_dir.iterdir() if path.is_dir()):
        if group_dir.name.lower() == "done":
            continue
        for file_path in sorted(path for path in group_dir.iterdir() if path.is_file()):
            if file_path.suffix.lower() != ".md":
                continue
            if file_path.name == "README.md":
                continue
            if file_path.name.endswith("_PLAN.md"):
                continue
            relative = file_path.relative_to(planning_dir)
            files.append(str(relative).replace("\\", "/"))
    return files


def discover_tree_projects(base_dir: Path, trees_dir_name: str) -> list[tuple[str, Path]]:
    tree_roots = _discover_tree_roots(base_dir, trees_dir_name)
    if not tree_roots:
        return []

    projects: list[tuple[str, Path]] = []
    seen: set[str] = set()
    normalized = trees_dir_name.strip().rstrip("/")
    flat_prefix = f"{normalized}-"

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


def resolve_planning_files(
    *,
    selection_raw: str,
    planning_files: list[str],
    base_dir: Path,
    planning_dir: Path,
) -> OrderedDict[str, int]:
    if not selection_raw.strip():
        raise ValueError("empty planning selection")
    if not planning_files:
        raise ValueError(f"No planning files found in {planning_dir}.")

    tokenized = [part.strip() for part in selection_raw.split(",")]
    plan_counts: OrderedDict[str, int] = OrderedDict()

    for token in tokenized:
        if not token:
            continue
        normalized = _normalize_selection_token(token=token, base_dir=base_dir, planning_dir=planning_dir)
        if not normalized.endswith(".md"):
            normalized = f"{normalized}.md"

        match = ""
        if "/" in normalized:
            if normalized in planning_files:
                match = normalized
        else:
            basename_matches = [plan for plan in planning_files if Path(plan).name == normalized]
            if len(basename_matches) == 1:
                match = basename_matches[0]
            elif len(basename_matches) > 1:
                raise ValueError(f"Planning file name '{token}' is ambiguous. Use folder/name.")

        if not match:
            raise ValueError(f"Planning file not found: {token}")

        plan_counts[match] = plan_counts.get(match, 0) + 1

    if not plan_counts:
        raise ValueError("No planning files selected.")
    return plan_counts


def planning_feature_name(rel_path: str) -> str:
    normalized = rel_path.strip().replace("\\", "/").lstrip("./")
    folder = normalized.split("/", 1)[0] if "/" in normalized else normalized
    filename = Path(normalized).name
    stem = filename[:-3] if filename.lower().endswith(".md") else filename
    return _slugify_underscore(f"{folder}_{stem}")


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
        candidates = [
            project
            for project in projects
            if project[0].lower() == feature.lower() or project[0].lower().startswith(f"{feature.lower()}-")
        ]
        candidates.sort(key=lambda project: _project_sort_key(project[0], feature))
        for name, root in candidates[:count]:
            dedupe_key = f"{name}|{root}"
            if dedupe_key in seen:
                continue
            selected.append((name, root))
            seen.add(dedupe_key)

    return selected


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


def _is_iteration_name(name: str) -> bool:
    return bool(_ITERATION_RE.match(name.strip()))


def _is_ignored(name: str) -> bool:
    return name.strip().lower() in _IGNORED_DIR_NAMES


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
            project_name = f"{feature_name}-{iter_dir.name}"
            dedupe_key = f"{project_name}|{iter_dir.resolve()}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            projects.append((project_name, iter_dir))
        return

    dedupe_key = f"{feature_name}|{feature_dir.resolve()}"
    if dedupe_key in seen:
        return
    seen.add(dedupe_key)
    projects.append((feature_name, feature_dir))


def _slugify_underscore(value: str) -> str:
    lowered = value.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", lowered)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug


def _normalize_selection_token(*, token: str, base_dir: Path, planning_dir: Path) -> str:
    normalized = token.strip().replace("\\", "/")
    normalized = normalized[2:] if normalized.startswith("./") else normalized

    planning_dir_norm = str(planning_dir).replace("\\", "/").rstrip("/")
    base_dir_norm = str(base_dir).replace("\\", "/").rstrip("/")

    if normalized.startswith(f"{planning_dir_norm}/"):
        normalized = normalized[len(planning_dir_norm) + 1 :]
    if normalized.startswith(f"{base_dir_norm}/"):
        normalized = normalized[len(base_dir_norm) + 1 :]

    planning_rel = ""
    try:
        planning_rel = str(planning_dir.relative_to(base_dir)).replace("\\", "/").rstrip("/")
    except ValueError:
        planning_rel = ""
    if planning_rel and normalized.startswith(f"{planning_rel}/"):
        normalized = normalized[len(planning_rel) + 1 :]

    return normalized


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
