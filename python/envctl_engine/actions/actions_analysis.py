from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from envctl_engine.actions.action_utils import detect_envctl_python, detect_repo_python


def default_review_command(base_dir: Path) -> list[str] | None:
    _ = base_dir
    python_bin = detect_envctl_python()
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

    pyproject = backend_dir / "pyproject.toml"
    if pyproject.is_file() and _pyproject_uses_poetry(pyproject) and shutil.which("poetry"):
        return MigrateCommandResolution(
            command=["poetry", "--project", str(backend_dir), "run", "alembic", "upgrade", "head"],
            cwd=backend_dir,
            error=None,
        )

    for env_dir in (backend_dir / ".venv", backend_dir / "venv", project_root / ".venv", project_root / "venv"):
        alembic_bin = env_dir / "bin" / "alembic"
        if alembic_bin.is_file():
            return MigrateCommandResolution(
                command=[str(alembic_bin), "upgrade", "head"],
                cwd=backend_dir,
                error=None,
            )

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


def _pyproject_uses_poetry(pyproject: Path) -> bool:
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return "[tool.poetry]" in text or "[tool.pdm]" in text
