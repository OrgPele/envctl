from __future__ import annotations

from dataclasses import dataclass
import os
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


def suggest_action_test_command(base_dir: Path) -> str | None:
    commands = default_test_commands(base_dir)
    if len(commands) != 1:
        return None
    return " ".join(str(part) for part in commands[0].command)


def suggest_backend_test_command(base_dir: Path) -> str | None:
    commands = default_test_commands(base_dir, include_backend=True, include_frontend=False)
    if len(commands) != 1:
        return None
    return " ".join(str(part) for part in commands[0].command)


def suggest_frontend_test_command(base_dir: Path) -> str | None:
    commands = default_test_commands(base_dir, include_backend=False, include_frontend=True)
    if len(commands) != 1:
        return None
    return " ".join(str(part) for part in commands[0].command)


def suggest_frontend_test_path(base_dir: Path) -> str | None:
    package_root = _frontend_test_package_root(base_dir)
    if package_root is None:
        return None
    suggested = _suggest_frontend_test_path_for_package_root(package_root)
    if not suggested:
        return None
    return canonicalize_frontend_test_path(
        suggested,
        project_root=base_dir,
        frontend_dir_name=_frontend_dir_name_from_package_root(base_dir, package_root),
    )


def default_test_commands(
    base_dir: Path,
    *,
    include_backend: bool = True,
    include_frontend: bool = True,
    frontend_test_path: str | None = None,
) -> list[TestCommandSpec]:
    commands: list[TestCommandSpec] = []

    backend_pytest = _backend_pytest_command(base_dir) if include_backend else None
    if backend_pytest is not None:
        commands.append(TestCommandSpec(command=backend_pytest, cwd=base_dir, source="backend_pytest"))

    frontend_package_test = _frontend_package_manager_test_command(base_dir) if include_frontend else None
    if frontend_package_test is not None:
        commands.append(
            TestCommandSpec(
                command=append_frontend_test_path(
                    frontend_package_test,
                    frontend_test_path,
                    project_root=base_dir,
                    command_cwd=base_dir / "frontend",
                ),
                # Frontend package tests run from the frontend app root.
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
            commands.append(
                TestCommandSpec(
                    command=append_frontend_test_path(
                        package_test,
                        frontend_test_path,
                        project_root=base_dir,
                        command_cwd=base_dir,
                    ),
                    cwd=base_dir,
                    source="package_test",
                )
            )
    return commands


def append_frontend_test_path(
    command: Sequence[str],
    frontend_test_path: str | None,
    *,
    project_root: Path | None = None,
    command_cwd: Path | None = None,
) -> list[str]:
    rendered = [str(part) for part in command]
    path_value = normalize_frontend_test_path(
        frontend_test_path,
        project_root=project_root,
        command_cwd=command_cwd,
    )
    if not path_value:
        return rendered
    if path_value in rendered:
        return rendered
    if "--" in rendered:
        return [*rendered, path_value]
    return [*rendered, "--", path_value]


def normalize_frontend_test_path(
    frontend_test_path: str | None,
    *,
    project_root: Path | None,
    command_cwd: Path | None,
) -> str | None:
    text = str(frontend_test_path or "").strip()
    if not text:
        return None
    normalized = text.replace("\\", "/").strip()
    if not normalized:
        return None
    normalized = normalized.rstrip("/")
    if not normalized:
        return None
    if command_cwd is None or project_root is None:
        return normalized
    if os.path.isabs(normalized):
        try:
            relative = os.path.relpath(normalized, command_cwd)
        except ValueError:
            return normalized
        return relative or "."
    try:
        relative_cwd = command_cwd.resolve().relative_to(project_root.resolve())
    except ValueError:
        return normalized
    prefix = relative_cwd.as_posix().rstrip("/")
    if not prefix or prefix == ".":
        return normalized
    if normalized == prefix:
        return "."
    prefixed = f"{prefix}/"
    if normalized.startswith(prefixed):
        trimmed = normalized[len(prefixed) :].strip("/")
        return trimmed or "."
    return normalized


def canonicalize_frontend_test_path(
    frontend_test_path: str | None,
    *,
    project_root: Path,
    frontend_dir_name: str | None = None,
) -> str | None:
    text = str(frontend_test_path or "").strip()
    if not text:
        return None
    normalized = text.replace("\\", "/").strip().rstrip("/")
    if not normalized:
        return None
    if os.path.isabs(normalized):
        return normalized
    package_root = _frontend_package_root_for_config(project_root, frontend_dir_name)
    if package_root is None:
        return normalized
    package_prefix = _frontend_dir_name_from_package_root(project_root, package_root)
    if not package_prefix:
        return normalized
    if normalized == package_prefix or normalized.startswith(f"{package_prefix}/"):
        return normalized
    package_candidate = package_root / normalized
    project_candidate = project_root / normalized
    if package_candidate.exists() or not project_candidate.exists():
        return f"{package_prefix}/{normalized}"
    return normalized


def is_package_test_command(command: Sequence[str]) -> bool:
    rendered = [str(part).strip() for part in command if str(part).strip()]
    if not rendered:
        return False
    first = rendered[0]
    if first in {"npm", "pnpm", "bun"}:
        return len(rendered) >= 3 and rendered[1] == "run" and rendered[2] == "test"
    if first == "yarn":
        return (len(rendered) >= 2 and rendered[1] == "test") or (
            len(rendered) >= 3 and rendered[1] == "run" and rendered[2] == "test"
        )
    return False


def is_pytest_command(command: Sequence[str]) -> bool:
    rendered = [str(part).strip() for part in command if str(part).strip()]
    if len(rendered) < 3:
        return False
    return rendered[1] == "-m" and rendered[2] == "pytest"


def is_unittest_command(command: Sequence[str]) -> bool:
    rendered = [str(part).strip() for part in command if str(part).strip()]
    if len(rendered) < 3:
        return False
    return rendered[1] == "-m" and rendered[2] == "unittest"


def classify_test_command_source(
    command: Sequence[str],
    *,
    include_backend: bool,
    include_frontend: bool,
) -> str:
    if include_backend and is_pytest_command(command):
        return "backend_pytest"
    if include_backend and is_unittest_command(command):
        return "root_unittest"
    if include_frontend and is_package_test_command(command):
        return "frontend_package_test" if not include_backend else "package_test"
    return "configured"


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
        "-t",
        ".",
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
    package_root = _frontend_test_package_root(base_dir)
    if package_root is None:
        return None
    package_json = package_root / "package.json"
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


def _frontend_test_package_root(base_dir: Path) -> Path | None:
    package_root = base_dir / "frontend"
    package_json = package_root / "package.json"
    if not package_json.is_file():
        return None
    return package_root


def _frontend_package_root_for_config(project_root: Path, frontend_dir_name: str | None) -> Path | None:
    configured = str(frontend_dir_name or "").strip().strip("/")
    if configured and configured != ".":
        candidate = project_root / configured
        if candidate.exists() or candidate.parent.exists():
            return candidate
    return _frontend_test_package_root(project_root)


def _frontend_dir_name_from_package_root(project_root: Path, package_root: Path) -> str | None:
    try:
        package_prefix = package_root.resolve().relative_to(project_root.resolve()).as_posix().rstrip("/")
    except ValueError:
        return None
    return package_prefix or None


def _suggest_frontend_test_path_for_package_root(package_root: Path) -> str | None:
    preferred = ("tests", "test", "__tests__", "src", "app", "ui", "client")
    for relative_name in preferred:
        candidate = package_root / relative_name
        if not candidate.is_dir():
            continue
        if _directory_contains_test_files(candidate):
            return relative_name
    for fallback in ("src", "app", "ui", "client", "tests", "test", "__tests__"):
        candidate = package_root / fallback
        if candidate.is_dir():
            return fallback
    return None


def _directory_contains_test_files(path: Path) -> bool:
    patterns = (
        "*.test.*",
        "*.spec.*",
    )
    for pattern in patterns:
        if next(path.rglob(pattern), None) is not None:
            return True
    return False
