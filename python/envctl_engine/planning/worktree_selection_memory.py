from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path


def plan_selection_memory_path(*, runtime_root: Path) -> Path:
    return runtime_root / "planning_selection.json"


def load_plan_selection_memory(*, runtime_root: Path, runtime_legacy_root: Path) -> dict[str, int]:
    path = plan_selection_memory_path(runtime_root=runtime_root)
    legacy_path = runtime_legacy_root / "planning_selection.json"
    for candidate in (path, legacy_path):
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(payload, dict):
            continue
        remembered = payload.get("selected_counts", {})
        if not isinstance(remembered, dict):
            continue
        result: dict[str, int] = {}
        for key, value in remembered.items():
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed >= 0:
                result[str(key)] = parsed
        if result:
            return result
    return {}


def save_plan_selection_memory(
    *,
    runtime_root: Path,
    runtime_legacy_root: Path,
    selected_counts: dict[str, int],
) -> None:
    path = plan_selection_memory_path(runtime_root=runtime_root)
    payload = {
        "selected_counts": dict(sorted({k: int(v) for k, v in selected_counts.items() if int(v) > 0}.items())),
        "saved_at": datetime.now(UTC).isoformat(),
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    path.write_text(text, encoding="utf-8")
    runtime_legacy_root.mkdir(parents=True, exist_ok=True)
    (runtime_legacy_root / "planning_selection.json").write_text(text, encoding="utf-8")


def initial_plan_selected_counts(
    *,
    planning_files: list[str],
    existing_counts: dict[str, int],
    remembered_counts: dict[str, int],
) -> dict[str, int]:
    selected_counts: dict[str, int] = {}
    for plan_file in planning_files:
        existing = int(existing_counts.get(plan_file, 0))
        remembered_value = int(remembered_counts.get(plan_file, 0))
        selected_counts[plan_file] = existing if existing > 0 else max(remembered_value, 0)
    return selected_counts
