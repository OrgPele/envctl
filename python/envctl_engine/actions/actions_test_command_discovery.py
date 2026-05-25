from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Callable, Sequence

from envctl_engine.actions.actions_test_frontend_paths import (
    _frontend_dir_name_from_package_root,
    _frontend_test_package_root,
    _frontend_test_path_candidates,
    append_frontend_test_path,
    canonicalize_frontend_test_path,
)
from envctl_engine.actions.actions_test_models import (
    SuggestionConfidence,
    SuggestionTarget,
    TestCommandSpec,
    TestCommandSuggestion,
    TestPathSuggestion,
)
from envctl_engine.shared.node_tooling import detect_package_manager, detect_python_bin, load_package_json


def default_test_command(
    base_dir: Path,
    *,
    detect_python_bin_fn: Callable[[Path, Path], str | None] = detect_python_bin,
) -> list[str] | None:
    commands = default_test_commands(base_dir, detect_python_bin_fn=detect_python_bin_fn)
    if not commands:
        return None
    return list(commands[0].command)


def suggest_action_test_command(
    base_dir: Path,
    *,
    detect_python_bin_fn: Callable[[Path, Path], str | None] = detect_python_bin,
) -> str | None:
    commands = default_test_commands(base_dir, detect_python_bin_fn=detect_python_bin_fn)
    if len(commands) != 1:
        return None
    return " ".join(str(part) for part in commands[0].command)


def suggest_backend_test_command(
    base_dir: Path,
    *,
    detect_python_bin_fn: Callable[[Path, Path], str | None] = detect_python_bin,
) -> str | None:
    commands = default_test_commands(
        base_dir,
        include_backend=True,
        include_frontend=False,
        detect_python_bin_fn=detect_python_bin_fn,
    )
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
    detect_python_bin_fn: Callable[[Path, Path], str | None] = detect_python_bin,
) -> list[TestCommandSuggestion]:
    suggestions: list[TestCommandSuggestion] = []
    if include_backend:
        backend_pytest = backend_pytest_command(base_dir, detect_python_bin_fn=detect_python_bin_fn)
        if backend_pytest is not None:
            suggestions.append(
                test_command_suggestion(
                    TestCommandSpec(command=backend_pytest, cwd=base_dir, source="backend_pytest"),
                    target="backend",
                    is_default=True,
                )
            )
        root_pytest = root_pytest_command(base_dir, detect_python_bin_fn=detect_python_bin_fn)
        if root_pytest is not None:
            suggestions.append(
                test_command_suggestion(
                    TestCommandSpec(command=root_pytest, cwd=base_dir, source="root_pytest"),
                    target="backend",
                    is_default=not suggestions,
                )
            )
        elif (base_dir / "tests").is_dir():
            root_unittest = root_unittest_discover_command(base_dir, detect_python_bin_fn=detect_python_bin_fn)
            if root_unittest is not None:
                suggestions.append(
                    test_command_suggestion(
                        TestCommandSpec(command=root_unittest, cwd=base_dir, source="root_unittest"),
                        target="backend",
                        is_default=not suggestions,
                    )
                )
    if include_frontend:
        frontend_package_test = frontend_package_manager_test_command(base_dir)
        if frontend_package_test is not None:
            suggestions.append(
                test_command_suggestion(
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
            root_package_test = root_package_manager_test_command(base_dir)
            if root_package_test is not None:
                suggestions.append(
                    test_command_suggestion(
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
    detect_python_bin_fn: Callable[[Path, Path], str | None] = detect_python_bin,
) -> list[TestCommandSpec]:
    commands: list[TestCommandSpec] = []

    backend_pytest = (
        backend_pytest_command(base_dir, detect_python_bin_fn=detect_python_bin_fn) if include_backend else None
    )
    if backend_pytest is not None:
        commands.append(TestCommandSpec(command=backend_pytest, cwd=base_dir, source="backend_pytest"))

    frontend_package_test = frontend_package_manager_test_command(base_dir) if include_frontend else None
    if frontend_package_test is not None:
        commands.append(
            TestCommandSpec(
                command=append_frontend_test_path(
                    frontend_package_test,
                    frontend_test_path,
                    project_root=base_dir,
                    command_cwd=base_dir / "frontend",
                ),
                cwd=base_dir / "frontend",
                source="frontend_package_test",
            )
        )

    if commands:
        return commands

    if include_backend:
        tests_dir = base_dir / "tests"
        if tests_dir.is_dir():
            root_pytest = root_pytest_command(base_dir, detect_python_bin_fn=detect_python_bin_fn)
            if root_pytest is not None:
                commands.append(TestCommandSpec(command=root_pytest, cwd=base_dir, source="root_pytest"))
            else:
                root_unittest = root_unittest_discover_command(base_dir, detect_python_bin_fn=detect_python_bin_fn)
                if root_unittest is not None:
                    commands.append(TestCommandSpec(command=root_unittest, cwd=base_dir, source="root_unittest"))

    if not commands and include_frontend:
        package_test = package_manager_test_command(base_dir)
        if package_test is not None:
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


def command_text(command: Sequence[str]) -> str:
    return " ".join(str(part) for part in command)


def test_command_suggestion(
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
        command_text=command_text(spec.command),
        command=list(spec.command),
        cwd=spec.cwd,
        source=spec.source,
        label=labels.get(spec.source, "Test command"),
        confidence=confidence_by_source.get(spec.source, "medium"),
        reason=reasons.get(spec.source, "Detected from local project files."),
        target=target,
        is_default=is_default,
    )


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


def package_manager_test_command(base_dir: Path) -> list[str] | None:
    for package_root in (base_dir, base_dir / "frontend"):
        command = package_manager_test_command_for_root(package_root)
        if command is not None:
            return command
    return None


def frontend_package_manager_test_command(base_dir: Path) -> list[str] | None:
    package_root = _frontend_test_package_root(base_dir)
    if package_root is None:
        return None
    return package_manager_test_command_for_root(package_root)


def root_package_manager_test_command(base_dir: Path) -> list[str] | None:
    return package_manager_test_command_for_root(base_dir)


def package_manager_test_command_for_root(package_root: Path) -> list[str] | None:
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
