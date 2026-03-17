from __future__ import annotations

ENVCTL_LOCAL_ARTIFACT_PATTERNS: tuple[str, ...] = (
    ".envctl*",
    "MAIN_TASK.md",
    "OLD_TASK_*.md",
    "trees/",
    "trees-*",
)


def envctl_local_artifact_patterns() -> tuple[str, ...]:
    return ENVCTL_LOCAL_ARTIFACT_PATTERNS
