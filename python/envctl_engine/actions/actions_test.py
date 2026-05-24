from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from typing import Callable, Sequence

from envctl_engine.actions.actions_test_classification import (
    build_test_args,
    classify_test_command_source,
    is_package_test_command,
    is_pytest_command,
    is_unittest_command,
)
from envctl_engine.actions.actions_test_frontend_paths import (
    _directory_contains_test_files,
    _frontend_dir_name_from_package_root,
    _frontend_package_root_for_config,
    _frontend_test_package_root,
    _frontend_test_path_candidates,
    _suggest_frontend_test_path_for_package_root,
    append_frontend_test_path,
    canonicalize_frontend_test_path,
    normalize_frontend_test_path,
)
from envctl_engine.actions.actions_test_models import (
    SuggestionConfidence,
    SuggestionTarget,
    TestCommandSpec,
    TestCommandSuggestion,
    TestPathSuggestion,
)
from envctl_engine.shared.node_tooling import detect_package_manager, detect_python_bin, load_package_json

__all__ = [
    "SuggestionConfidence",
    "SuggestionTarget",
    "TestCommandSpec",
    "TestCommandSuggestion",
    "TestPathSuggestion",
    "_directory_contains_test_files",
    "_frontend_dir_name_from_package_root",
    "_frontend_package_root_for_config",
    "_frontend_test_package_root",
    "_frontend_test_path_candidates",
    "_suggest_frontend_test_path_for_package_root",
    "append_frontend_test_path",
    "build_test_args",
    "canonicalize_frontend_test_path",
    "classify_test_command_source",
    "default_test_command",
    "default_test_commands",
    "ensure_repo_local_test_prereqs",
    "frontend_test_path_suggestions",
    "is_package_test_command",
    "is_pytest_command",
    "is_unittest_command",
    "normalize_frontend_test_path",
    "suggest_action_test_command",
    "suggest_backend_test_command",
    "suggest_frontend_test_command",
    "suggest_frontend_test_path",
    "test_command_suggestions",
]


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
    for suggestion in frontend_test_path_suggestions(base_dir):
        if suggestion.confidence == "high":
            return suggestion.path
    return None


def test_command_suggestions(
    base_dir: Path,
    *,
    include_backend: bool = True,
    include_frontend: bool = True,
    frontend_test_path: str | None = None,
) -> list[TestCommandSuggestion]:
    suggestions: list[TestCommandSuggestion] = []
    if include_backend:
        backend_pytest = _backend_pytest_command(base_dir)
        if backend_pytest is not None:
            suggestions.append(
                _test_command_suggestion(
                    TestCommandSpec(command=backend_pytest, cwd=base_dir, source="backend_pytest"),
                    target="backend",
                    is_default=True,
                )
            )
        root_pytest = _root_pytest_command(base_dir)
        if root_pytest is not None:
            suggestions.append(
                _test_command_suggestion(
                    TestCommandSpec(command=root_pytest, cwd=base_dir, source="root_pytest"),
                    target="backend",
                    is_default=not suggestions,
                )
            )
        elif (base_dir / "tests").is_dir():
            root_unittest = _root_unittest_discover_command(base_dir)
            if root_unittest is not None:
                suggestions.append(
                    _test_command_suggestion(
                        TestCommandSpec(command=root_unittest, cwd=base_dir, source="root_unittest"),
                        target="backend",
                        is_default=not suggestions,
                    )
                )
    if include_frontend:
        frontend_package_test = _frontend_package_manager_test_command(base_dir)
        if frontend_package_test is not None:
            suggestions.append(
                _test_command_suggestion(
                    TestCommandSpec(
                        command=append_frontend_test_path(
                            frontend_package_test,
                            frontend_test_path,
                            project_root=base_dir,
                            command_cwd=base_dir / "frontend",
                        ),
                        cwd=base_dir / "frontend",
                        source="frontend_package_test",
                    ),
                    target="frontend",
                    is_default=True,
                )
            )
        elif _frontend_test_package_root(base_dir) is None:
            root_package_test = _root_package_manager_test_command(base_dir)
            if root_package_test is not None:
                suggestions.append(
                    _test_command_suggestion(
                        TestCommandSpec(
                            command=append_frontend_test_path(
                                root_package_test,
                                frontend_test_path,
                                project_root=base_dir,
                                command_cwd=base_dir,
                            ),
                            cwd=base_dir,
                            source="package_test",
                        ),
                        target="frontend",
                        is_default=True,
                    )
                )
    return suggestions


def frontend_test_path_suggestions(base_dir: Path) -> list[TestPathSuggestion]:
    package_root = _frontend_test_package_root(base_dir)
    if package_root is None:
        return []
    frontend_dir_name = _frontend_dir_name_from_package_root(base_dir, package_root)
    suggestions: list[TestPathSuggestion] = []
    for relative_path, source, label, confidence, reason in _frontend_test_path_candidates(package_root):
        canonical = canonicalize_frontend_test_path(
            relative_path,
            project_root=base_dir,
            frontend_dir_name=frontend_dir_name,
        )
        if canonical is None:
            continue
        suggestions.append(
            TestPathSuggestion(
                path=canonical,
                source=source,
                label=label,
                confidence=confidence,
                reason=reason,
                is_default=confidence == "high" and not any(item.confidence == "high" for item in suggestions),
            )
        )
    return suggestions


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
            root_pytest = _root_pytest_command(base_dir)
            if root_pytest is not None:
                commands.append(TestCommandSpec(command=root_pytest, cwd=base_dir, source="root_pytest"))
            else:
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


def _command_text(command: Sequence[str]) -> str:
    return " ".join(str(part) for part in command)


def _test_command_suggestion(
    spec: TestCommandSpec,
    *,
    target: SuggestionTarget,
    is_default: bool,
) -> TestCommandSuggestion:
    labels = {
        "backend_pytest": "Backend pytest",
        "root_pytest": "Root pytest",
        "root_unittest": "Root unittest discover",
        "frontend_package_test": "Frontend package test",
        "package_test": "Root package test",
        "configured": "Configured test command",
    }
    confidence_by_source: dict[str, SuggestionConfidence] = {
        "backend_pytest": "high",
        "root_pytest": "high",
        "root_unittest": "medium",
        "frontend_package_test": "high",
        "package_test": "medium",
        "configured": "high",
    }
    reasons = {
        "backend_pytest": "Detected backend pytest from backend/tests plus backend Python metadata.",
        "root_pytest": "Detected root pytest from tests/ plus pytest configuration.",
        "root_unittest": "Detected root tests/ without pytest metadata; unittest discover is the safe fallback.",
        "frontend_package_test": "Detected frontend package test script from frontend/package.json.",
        "package_test": "Detected root package test script from package.json.",
        "configured": "Configured test command.",
    }
    return TestCommandSuggestion(
        command_text=_command_text(spec.command),
        command=list(spec.command),
        cwd=spec.cwd,
        source=spec.source,
        label=labels.get(spec.source, "Test command"),
        confidence=confidence_by_source.get(spec.source, "medium"),
        reason=reasons.get(spec.source, "Detected from local project files."),
        target=target,
        is_default=is_default,
    )


def ensure_repo_local_test_prereqs(
    project_root: Path,
    *,
    emit_status: Callable[[str], None] | None = None,
) -> None:
    root = Path(project_root).resolve()
    if not _is_envctl_repo(root):
        return

    repo_python = root / ".venv" / "bin" / "python"
    if repo_python.is_file() and _repo_local_test_python_ready(repo_python):
        return

    if not repo_python.is_file():
        _emit_bootstrap_status(emit_status, f"Creating repo-local .venv for envctl test actions in {root}")
        bootstrap_python = _bootstrap_python_executable()
        _run_bootstrap_command([bootstrap_python, "-m", "venv", str(root / ".venv")], cwd=root)

    _emit_bootstrap_status(emit_status, f"Installing repo-local envctl test prerequisites in {root / '.venv'}")
    _run_bootstrap_command([str(repo_python), "-m", "pip", "install", "-e", ".[dev]"], cwd=root)


def _emit_bootstrap_status(emit_status: Callable[[str], None] | None, message: str) -> None:
    if callable(emit_status):
        emit_status(message)


def _is_envctl_repo(project_root: Path) -> bool:
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


def _repo_local_test_python_ready(python_bin: Path) -> bool:
    result = subprocess.run(
        [str(python_bin), "-c", "import build, prompt_toolkit, psutil, pytest, rich, textual"],
        cwd=python_bin.parent.parent.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    return int(result.returncode) == 0


def _bootstrap_python_executable() -> str:
    candidates = [
        shutil.which("python3.12"),
        sys.executable if sys.executable else None,
        shutil.which("python3"),
        shutil.which("python"),
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    raise RuntimeError(
        "Unable to bootstrap repo-local envctl test prerequisites: no Python interpreter was found. "
        "Run uv sync --extra dev --python 3.12."
    )


def _run_bootstrap_command(command: list[str], *, cwd: Path) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if int(result.returncode) == 0:
        return
    output_lines = [line.strip() for line in f"{result.stdout}\n{result.stderr}".splitlines() if line.strip()]
    detail = output_lines[0] if output_lines else f"exit {result.returncode}"
    rendered = " ".join(str(part) for part in command)
    raise RuntimeError(
        "Failed to bootstrap repo-local envctl test prerequisites "
        f"with `{rendered}`: {detail}\n"
        "Run uv sync --extra dev --python 3.12"
    )


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


def _root_pytest_command(base_dir: Path) -> list[str] | None:
    if not (base_dir / "tests").is_dir():
        return None
    if not _root_has_pytest_config(base_dir):
        return None
    python_exe = detect_python_bin(base_dir, base_dir)
    if not python_exe:
        return None
    return [python_exe, "-m", "pytest", "tests"]


def _root_has_pytest_config(base_dir: Path) -> bool:
    pyproject = base_dir / "pyproject.toml"
    if pyproject.is_file():
        try:
            payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            payload = {}
        tool = payload.get("tool") if isinstance(payload, dict) else None
        if isinstance(tool, dict) and "pytest" in tool:
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
        command = _package_manager_test_command_for_root(package_root)
        if command is not None:
            return command
    return None


def _frontend_package_manager_test_command(base_dir: Path) -> list[str] | None:
    package_root = _frontend_test_package_root(base_dir)
    if package_root is None:
        return None
    return _package_manager_test_command_for_root(package_root)


def _root_package_manager_test_command(base_dir: Path) -> list[str] | None:
    return _package_manager_test_command_for_root(base_dir)


def _package_manager_test_command_for_root(package_root: Path) -> list[str] | None:
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
