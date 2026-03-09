from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from envctl_engine.actions.action_utils import detect_repo_python


def default_review_command(base_dir: Path) -> list[str] | None:
    python_bin = detect_repo_python(base_dir)
    if python_bin is None:
        return None
    return [python_bin, "-m", "envctl_engine.actions.actions_cli", "review"]


@dataclass(slots=True)
class MigrateCommandResolution:
    command: list[str] | None
    cwd: Path
    error: str | None = None


def default_migrate_command(project_root: Path) -> MigrateCommandResolution:
    backend_dir = project_root / "backend"
    if not backend_dir.is_dir():
        backend_dir = project_root

    python_bin = detect_repo_python(backend_dir)
    if python_bin is None:
        return MigrateCommandResolution(
            command=None,
            cwd=backend_dir,
            error=f"backend python interpreter not found under {backend_dir}",
        )
    return MigrateCommandResolution(
        command=[str(python_bin), "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        error=None,
    )
