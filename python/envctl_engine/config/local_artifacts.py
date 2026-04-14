from __future__ import annotations

from pathlib import PurePath

ENVCTL_LOCAL_ARTIFACT_PATTERNS: tuple[str, ...] = (
    ".envctl*",
    "MAIN_TASK.md",
    "OLD_TASK_*.md",
    "trees/",
    "trees-*",
)


def envctl_local_artifact_patterns() -> tuple[str, ...]:
    return ENVCTL_LOCAL_ARTIFACT_PATTERNS


def is_envctl_local_artifact_path(path_text: str) -> bool:
    normalized = str(path_text or "").strip().replace("\\", "/")
    if not normalized:
        return False
    parts = [part for part in PurePath(normalized).parts if part not in {".", ""}]
    if not parts:
        return False
    first = parts[0]
    last = parts[-1]
    if first == "trees" or first.startswith("trees-"):
        return True
    if any(part.startswith(".envctl") for part in parts):
        return True
    if last == "MAIN_TASK.md":
        return True
    return last.startswith("OLD_TASK_") and last.endswith(".md")
