from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from envctl_engine.shared.node_tooling import detect_package_manager, detect_python_bin, load_package_json


@dataclass(frozen=True)
class TestCommandSpec:
    command: list[str]
    cwd: Path
    source: str


def default_test_command(base_dir: Path) -> list[str] | None:
    commands = default_test_commands(base_dir)
    if not commands:
        return None
    return list(commands[0].command)


def default_test_commands(
    base_dir: Path,
    *,
    include_backend: bool = True,
    include_frontend: bool = True,
) -> list[TestCommandSpec]:
    commands: list[TestCommandSpec] = []

    backend_pytest = _backend_pytest_command(base_dir) if include_backend else None
    if backend_pytest is not None:
        commands.append(TestCommandSpec(command=backend_pytest, cwd=base_dir, source="backend_pytest"))

    frontend_package_test = _frontend_package_manager_test_command(base_dir) if include_frontend else None
    if frontend_package_test is not None:
        commands.append(
            TestCommandSpec(
                command=frontend_package_test,
                cwd=base_dir / "frontend",
                source="frontend_package_test",
            )
        )

    if commands:
        return commands

    if include_backend:
        tests_dir = base_dir / "tests"
        if tests_dir.is_dir():
            root_unittest = _root_unittest_discover_command(base_dir)
            if root_unittest is not None:
                commands.append(TestCommandSpec(command=root_unittest, cwd=base_dir, source="root_unittest"))

    if not commands and include_frontend:
        package_test = _package_manager_test_command(base_dir)
        if package_test is not None:
            # Root package scripts should run from repo root.
            commands.append(TestCommandSpec(command=package_test, cwd=base_dir, source="package_test"))
    return commands


def build_test_args(project_names: Sequence[str], *, run_all: bool, untested: bool) -> list[str]:
    args: list[str] = []
    if not run_all and project_names:
        projects_arg = ",".join(project_names)
        args.append(f"projects={projects_arg}")
    if untested:
        args.append("untested=true")
    return args


def _root_unittest_discover_command(base_dir: Path) -> list[str] | None:
    python_exe = detect_python_bin(base_dir, base_dir)
    if not python_exe:
        return None
    return [
        python_exe,
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
        "-p",
        "test_*.py",
    ]


def _backend_pytest_command(base_dir: Path) -> list[str] | None:
    backend_dir = base_dir / "backend"
    if not backend_dir.is_dir():
        return None
    if not (backend_dir / "tests").is_dir():
        return None
    if not ((backend_dir / "pyproject.toml").is_file() or (backend_dir / "requirements.txt").is_file()):
        return None
    python_exe = detect_python_bin(backend_dir, base_dir)
    if not python_exe:
        return None
    return [python_exe, "-m", "pytest", str(backend_dir / "tests")]


def _package_manager_test_command(base_dir: Path) -> list[str] | None:
    for package_root in (base_dir, base_dir / "frontend"):
        package_json = package_root / "package.json"
        if not package_json.is_file():
            continue
        payload = load_package_json(package_json)
        if payload is None:
            continue
        scripts = payload.get("scripts")
        if not isinstance(scripts, dict):
            continue
        test_script = scripts.get("test")
        if not isinstance(test_script, str) or not test_script.strip():
            continue
        manager = detect_package_manager(package_root)
        if manager is None:
            continue
        return [manager, "run", "test"]
    return None


def _frontend_package_manager_test_command(base_dir: Path) -> list[str] | None:
    package_root = base_dir / "frontend"
    package_json = package_root / "package.json"
    if not package_json.is_file():
        return None
    payload = load_package_json(package_json)
    if payload is None:
        return None
    scripts = payload.get("scripts")
    if not isinstance(scripts, dict):
        return None
    test_script = scripts.get("test")
    if not isinstance(test_script, str) or not test_script.strip():
        return None
    manager = detect_package_manager(package_root)
    if manager is None:
        return None
    return [manager, "run", "test"]
