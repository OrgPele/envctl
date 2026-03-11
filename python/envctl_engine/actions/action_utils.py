from __future__ import annotations

from pathlib import Path
import shutil
import sys


def detect_envctl_python() -> str | None:
    runtime_python = str(getattr(sys, "executable", "") or "").strip()
    if runtime_python:
        return runtime_python
    for exe in ("python3.12", "python3", "python"):
        resolved = shutil.which(exe)
        if resolved:
            return resolved
    return None


def envctl_python_root() -> Path:
    return Path(__file__).resolve().parents[2]


def detect_repo_python(base_dir: Path) -> str | None:
    candidates = [base_dir / ".venv" / "bin" / "python", base_dir / "venv" / "bin" / "python"]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    for exe in ("python3.12", "python3", "python"):
        resolved = shutil.which(exe)
        if resolved:
            return resolved
    runtime_python = str(getattr(sys, "executable", "") or "").strip()
    if runtime_python:
        return runtime_python
    return None
