from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path


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


def resolve_planning_files(
    *,
    selection_raw: str,
    planning_files: list[str],
    base_dir: Path,
    planning_dir: Path,
    requested_cli: str = "",
) -> OrderedDict[str, int]:
    if not selection_raw.strip():
        raise ValueError("empty planning selection")
    if not planning_files:
        raise ValueError(f"No planning files found in {planning_dir}.")

    tokenized = [part.strip() for part in selection_raw.split(",")]
    plan_counts: OrderedDict[str, int] = OrderedDict()
    duplicate_for_both = str(requested_cli or "").strip().lower() == "both"

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

        increment = 2 if duplicate_for_both else 1
        plan_counts[match] = plan_counts.get(match, 0) + increment

    if not plan_counts:
        raise ValueError("No planning files selected.")
    return plan_counts


def planning_feature_name(rel_path: str) -> str:
    normalized = rel_path.strip().replace("\\", "/").lstrip("./")
    folder = normalized.split("/", 1)[0] if "/" in normalized else normalized
    filename = Path(normalized).name
    stem = filename[:-3] if filename.lower().endswith(".md") else filename
    return slugify_planning_feature(f"{folder}_{stem}")


def slugify_planning_feature(value: str) -> str:
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
