from __future__ import annotations

from pathlib import Path
from typing import Callable

from envctl_engine.shared.node_tooling import detect_python_bin
from envctl_engine.shared.python_project_metadata import pyproject_has_tool_table


def root_unittest_discover_command(
    base_dir: Path,
    *,
    detect_python_bin_fn: Callable[[Path, Path], str | None] = detect_python_bin,
) -> list[str] | None:
    python_exe = detect_python_bin_fn(base_dir, base_dir)
    if not python_exe:
        return None
    return [
        python_exe,
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-t",
        ".",
        "-p",
        "test_*.py",
    ]


def root_pytest_command(
    base_dir: Path,
    *,
    detect_python_bin_fn: Callable[[Path, Path], str | None] = detect_python_bin,
) -> list[str] | None:
    if not (base_dir / "tests").is_dir():
        return None
    if not root_has_pytest_config(base_dir):
        return None
    python_exe = detect_python_bin_fn(base_dir, base_dir)
    if not python_exe:
        return None
    return [python_exe, "-m", "pytest", "tests"]


def root_has_pytest_config(base_dir: Path) -> bool:
    pyproject = base_dir / "pyproject.toml"
    if pyproject_has_tool_table(pyproject, "pytest"):
        return True
    if (base_dir / "pytest.ini").is_file():
        return True
    for name in ("tox.ini", "setup.cfg"):
        path = base_dir / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        normalized = text.lower()
        if "[pytest]" in normalized or "[tool:pytest]" in normalized:
            return True
    return False


def backend_pytest_command(
    base_dir: Path,
    *,
    detect_python_bin_fn: Callable[[Path, Path], str | None] = detect_python_bin,
) -> list[str] | None:
    backend_dir = base_dir / "backend"
    if not backend_dir.is_dir():
        return None
    if not (backend_dir / "tests").is_dir():
        return None
    if not ((backend_dir / "pyproject.toml").is_file() or (backend_dir / "requirements.txt").is_file()):
        return None
    python_exe = detect_python_bin_fn(backend_dir, base_dir)
    if not python_exe:
        return None
    return [python_exe, "-m", "pytest", str(backend_dir / "tests")]
