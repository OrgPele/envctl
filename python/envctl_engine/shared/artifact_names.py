from __future__ import annotations

import re
from pathlib import Path


_UNSAFE_ARTIFACT_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_artifact_stem(value: object, *, fallback: str = "artifact") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    safe = _UNSAFE_ARTIFACT_CHARS.sub("_", text).strip("._-")
    return safe or fallback


def project_artifact_dir(root: Path, project_name: object) -> Path:
    return root / safe_artifact_stem(project_name, fallback="project")


def project_command_artifact_path(root: Path, *, project_name: object, command_name: object) -> Path:
    safe_project = safe_artifact_stem(project_name, fallback="project")
    safe_command = safe_artifact_stem(command_name, fallback="command")
    return root / f"{safe_project}_{safe_command}.txt"
