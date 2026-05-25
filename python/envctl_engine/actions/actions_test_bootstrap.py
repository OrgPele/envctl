from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tomllib
from typing import Callable


def ensure_repo_local_test_prereqs(
    project_root: Path,
    *,
    emit_status: Callable[[str], None] | None = None,
    run_process: Callable[..., object] = subprocess.run,
    python_executable: str | None = None,
    which_fn: Callable[[str], str | None] | None = None,
) -> None:
    root = Path(project_root).resolve()
    if not is_envctl_repo(root):
        return

    repo_python = root / ".venv" / "bin" / "python"
    if repo_python.is_file() and repo_local_test_python_ready(repo_python, run_process=run_process):
        return

    if not repo_python.is_file():
        emit_bootstrap_status(emit_status, f"Creating repo-local .venv for envctl test actions in {root}")
        bootstrap_python = bootstrap_python_executable(python_executable=python_executable, which_fn=which_fn)
        run_bootstrap_command([bootstrap_python, "-m", "venv", str(root / ".venv")], cwd=root, run_process=run_process)

    emit_bootstrap_status(emit_status, f"Installing repo-local envctl test prerequisites in {root / '.venv'}")
    run_bootstrap_command(
        [str(repo_python), "-m", "pip", "install", "-e", ".[dev]"],
        cwd=root,
        run_process=run_process,
    )


def emit_bootstrap_status(emit_status: Callable[[str], None] | None, message: str) -> None:
    if callable(emit_status):
        emit_status(message)


def is_envctl_repo(project_root: Path) -> bool:
    pyproject = project_root / "pyproject.toml"
    package_root = project_root / "python" / "envctl_engine"
    if not pyproject.is_file() or not package_root.is_dir():
        return False
    try:
        payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    project = payload.get("project")
    if not isinstance(project, dict):
        return False
    return str(project.get("name", "")).strip() == "envctl"


def repo_local_test_python_ready(
    python_bin: Path,
    *,
    run_process: Callable[..., object] = subprocess.run,
) -> bool:
    result = run_process(
        [str(python_bin), "-c", "import build, prompt_toolkit, psutil, pytest, rich, textual"],
        cwd=python_bin.parent.parent.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    return int(getattr(result, "returncode", 1)) == 0


def bootstrap_python_executable(
    *,
    python_executable: str | None = None,
    which_fn: Callable[[str], str | None] | None = None,
) -> str:
    import shutil

    which = which_fn or shutil.which
    candidates = [
        which("python3.12"),
        python_executable if python_executable else sys.executable if sys.executable else None,
        which("python3"),
        which("python"),
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    raise RuntimeError(
        "Unable to bootstrap repo-local envctl test prerequisites: no Python interpreter was found. "
        "Run uv sync --extra dev --python 3.12."
    )


def run_bootstrap_command(
    command: list[str],
    *,
    cwd: Path,
    run_process: Callable[..., object] = subprocess.run,
) -> None:
    result = run_process(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if int(getattr(result, "returncode", 1)) == 0:
        return
    output_lines = [
        line.strip()
        for line in f"{getattr(result, 'stdout', '')}\n{getattr(result, 'stderr', '')}".splitlines()
        if line.strip()
    ]
    detail = output_lines[0] if output_lines else f"exit {getattr(result, 'returncode', 1)}"
    rendered = " ".join(str(part) for part in command)
    raise RuntimeError(
        "Failed to bootstrap repo-local envctl test prerequisites "
        f"with `{rendered}`: {detail}\n"
        "Run uv sync --extra dev --python 3.12"
    )
