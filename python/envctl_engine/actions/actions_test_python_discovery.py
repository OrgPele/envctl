from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from envctl_engine.shared.node_tooling import PythonBinDetector, detect_python_bin
from envctl_engine.shared.python_project_metadata import pyproject_has_tool_table


_PYTHON_PROJECT_MARKER_NAMES = ("pyproject.toml", "requirements.txt")


def root_unittest_discover_command(
    base_dir: Path,
    *,
    detect_python_bin_fn: PythonBinDetector = detect_python_bin,
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
    detect_python_bin_fn: PythonBinDetector = detect_python_bin,
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
    detect_python_bin_fn: PythonBinDetector = detect_python_bin,
) -> list[str] | None:
    backend_dir = base_dir / "backend"
    backend_roots = backend_python_roots(base_dir)
    if not backend_dir.is_dir():
        return None
    if not (backend_dir / "tests").is_dir():
        return None
    if not backend_python_project_marker_exists(backend_roots):
        return None
    python_exe = detect_python_bin_fn(backend_dir, base_dir)
    if not python_exe:
        return None
    return [python_exe, "-m", "pytest", str(backend_dir / "tests")]


def backend_python_roots(project_root: Path) -> tuple[Path, ...]:
    backend_root = project_root / "backend"
    if backend_root.is_dir():
        return (backend_root, project_root)
    return (project_root,)


def backend_python_project_marker_exists(backend_roots: Sequence[Path]) -> bool:
    return any(_python_project_marker_exists(root) for root in backend_roots)


def backend_poetry_project_root(
    backend_roots: Sequence[Path],
    *,
    pyproject_uses_poetry_fn: Callable[[Path], bool],
) -> Path | None:
    for root in backend_roots:
        if not _python_project_marker_exists(root):
            continue
        if pyproject_uses_poetry_fn(root / "pyproject.toml"):
            return root
        return None
    return None


def _python_project_marker_exists(root: Path) -> bool:
    return any((root / name).is_file() for name in _PYTHON_PROJECT_MARKER_NAMES)
