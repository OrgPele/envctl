from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Callable, ClassVar, Sequence

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


@dataclass(frozen=True, slots=True)
class TestCommandDiscovery:
    __test__: ClassVar[bool] = False

    base_dir: Path
    include_backend: bool = True
    include_frontend: bool = True
    frontend_test_path: str | None = None
    detect_python_bin_fn: Callable[[Path, Path], str | None] = detect_python_bin

    def default_command(self) -> list[str] | None:
        commands = self.default_commands()
        if not commands:
            return None
        return list(commands[0].command)

    def suggest_action_command(self) -> str | None:
        commands = self.default_commands()
        if len(commands) != 1:
            return None
        return command_text(commands[0].command)

    def suggest_backend_command(self) -> str | None:
        commands = self._with_scope(include_backend=True, include_frontend=False).default_commands()
        if len(commands) != 1:
            return None
        return command_text(commands[0].command)

    def suggest_frontend_command(self) -> str | None:
        commands = self._with_scope(include_backend=False, include_frontend=True).default_commands()
        if len(commands) != 1:
            return None
        return command_text(commands[0].command)

    def suggest_frontend_path(self) -> str | None:
        for suggestion in self.frontend_path_suggestions():
            if suggestion.confidence == "high":
                return suggestion.path
        return None

    def suggestions(self) -> list[TestCommandSuggestion]:
        suggestions: list[TestCommandSuggestion] = []
        if self.include_backend:
            suggestions.extend(self._backend_suggestions(default_taken=bool(suggestions)))
        if self.include_frontend:
            suggestions.extend(self._frontend_suggestions())
        return suggestions

    def frontend_path_suggestions(self) -> list[TestPathSuggestion]:
        package_root = _frontend_test_package_root(self.base_dir)
        if package_root is None:
            return []
        frontend_dir_name = _frontend_dir_name_from_package_root(self.base_dir, package_root)
        suggestions: list[TestPathSuggestion] = []
        for relative_path, source, label, confidence, reason in _frontend_test_path_candidates(package_root):
            canonical = canonicalize_frontend_test_path(
                relative_path,
                project_root=self.base_dir,
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

    def default_commands(self) -> list[TestCommandSpec]:
        commands: list[TestCommandSpec] = []

        if self.include_backend:
            backend_pytest = backend_pytest_command(self.base_dir, detect_python_bin_fn=self.detect_python_bin_fn)
            if backend_pytest is not None:
                commands.append(TestCommandSpec(command=backend_pytest, cwd=self.base_dir, source="backend_pytest"))

        if self.include_frontend:
            frontend_package_test = frontend_package_manager_test_command(self.base_dir)
            if frontend_package_test is not None:
                commands.append(
                    TestCommandSpec(
                        command=append_frontend_test_path(
                            frontend_package_test,
                            self.frontend_test_path,
                            project_root=self.base_dir,
                            command_cwd=self.base_dir / "frontend",
                        ),
                        cwd=self.base_dir / "frontend",
                        source="frontend_package_test",
                    )
                )

        if commands:
            return commands

        if self.include_backend:
            commands.extend(self._fallback_backend_commands())

        if not commands and self.include_frontend:
            package_test = package_manager_test_command(self.base_dir)
            if package_test is not None:
                commands.append(
                    TestCommandSpec(
                        command=append_frontend_test_path(
                            package_test,
                            self.frontend_test_path,
                            project_root=self.base_dir,
                            command_cwd=self.base_dir,
                        ),
                        cwd=self.base_dir,
                        source="package_test",
                    )
                )
        return commands

    def _backend_suggestions(self, *, default_taken: bool) -> list[TestCommandSuggestion]:
        suggestions: list[TestCommandSuggestion] = []
        backend_pytest = backend_pytest_command(self.base_dir, detect_python_bin_fn=self.detect_python_bin_fn)
        if backend_pytest is not None:
            suggestions.append(
                test_command_suggestion(
                    TestCommandSpec(command=backend_pytest, cwd=self.base_dir, source="backend_pytest"),
                    target="backend",
                    is_default=not default_taken,
                )
            )
        root_pytest = root_pytest_command(self.base_dir, detect_python_bin_fn=self.detect_python_bin_fn)
        if root_pytest is not None:
            suggestions.append(
                test_command_suggestion(
                    TestCommandSpec(command=root_pytest, cwd=self.base_dir, source="root_pytest"),
                    target="backend",
                    is_default=not default_taken and not suggestions,
                )
            )
        elif (self.base_dir / "tests").is_dir():
            root_unittest = root_unittest_discover_command(
                self.base_dir,
                detect_python_bin_fn=self.detect_python_bin_fn,
            )
            if root_unittest is not None:
                suggestions.append(
                    test_command_suggestion(
                        TestCommandSpec(command=root_unittest, cwd=self.base_dir, source="root_unittest"),
                        target="backend",
                        is_default=not default_taken and not suggestions,
                    )
                )
        return suggestions

    def _frontend_suggestions(self) -> list[TestCommandSuggestion]:
        frontend_package_test = frontend_package_manager_test_command(self.base_dir)
        if frontend_package_test is not None:
            return [
                test_command_suggestion(
                    TestCommandSpec(
                        command=append_frontend_test_path(
                            frontend_package_test,
                            self.frontend_test_path,
                            project_root=self.base_dir,
                            command_cwd=self.base_dir / "frontend",
                        ),
                        cwd=self.base_dir / "frontend",
                        source="frontend_package_test",
                    ),
                    target="frontend",
                    is_default=True,
                )
            ]
        if _frontend_test_package_root(self.base_dir) is not None:
            return []
        root_package_test = root_package_manager_test_command(self.base_dir)
        if root_package_test is None:
            return []
        return [
            test_command_suggestion(
                TestCommandSpec(
                    command=append_frontend_test_path(
                        root_package_test,
                        self.frontend_test_path,
                        project_root=self.base_dir,
                        command_cwd=self.base_dir,
                    ),
                    cwd=self.base_dir,
                    source="package_test",
                ),
                target="frontend",
                is_default=True,
            )
        ]

    def _fallback_backend_commands(self) -> list[TestCommandSpec]:
        tests_dir = self.base_dir / "tests"
        if not tests_dir.is_dir():
            return []
        root_pytest = root_pytest_command(self.base_dir, detect_python_bin_fn=self.detect_python_bin_fn)
        if root_pytest is not None:
            return [TestCommandSpec(command=root_pytest, cwd=self.base_dir, source="root_pytest")]
        root_unittest = root_unittest_discover_command(self.base_dir, detect_python_bin_fn=self.detect_python_bin_fn)
        if root_unittest is not None:
            return [TestCommandSpec(command=root_unittest, cwd=self.base_dir, source="root_unittest")]
        return []

    def _with_scope(self, *, include_backend: bool, include_frontend: bool) -> TestCommandDiscovery:
        return TestCommandDiscovery(
            self.base_dir,
            include_backend=include_backend,
            include_frontend=include_frontend,
            frontend_test_path=self.frontend_test_path,
            detect_python_bin_fn=self.detect_python_bin_fn,
        )


def default_test_command(
    base_dir: Path,
    *,
    detect_python_bin_fn: Callable[[Path, Path], str | None] = detect_python_bin,
) -> list[str] | None:
    return TestCommandDiscovery(base_dir, detect_python_bin_fn=detect_python_bin_fn).default_command()


def suggest_action_test_command(
    base_dir: Path,
    *,
    detect_python_bin_fn: Callable[[Path, Path], str | None] = detect_python_bin,
) -> str | None:
    return TestCommandDiscovery(base_dir, detect_python_bin_fn=detect_python_bin_fn).suggest_action_command()


def suggest_backend_test_command(
    base_dir: Path,
    *,
    detect_python_bin_fn: Callable[[Path, Path], str | None] = detect_python_bin,
) -> str | None:
    return TestCommandDiscovery(base_dir, detect_python_bin_fn=detect_python_bin_fn).suggest_backend_command()


def suggest_frontend_test_command(base_dir: Path) -> str | None:
    return TestCommandDiscovery(base_dir).suggest_frontend_command()


def suggest_frontend_test_path(base_dir: Path) -> str | None:
    return TestCommandDiscovery(base_dir).suggest_frontend_path()


def test_command_suggestions(
    base_dir: Path,
    *,
    include_backend: bool = True,
    include_frontend: bool = True,
    frontend_test_path: str | None = None,
    detect_python_bin_fn: Callable[[Path, Path], str | None] = detect_python_bin,
) -> list[TestCommandSuggestion]:
    return TestCommandDiscovery(
        base_dir,
        include_backend=include_backend,
        include_frontend=include_frontend,
        frontend_test_path=frontend_test_path,
        detect_python_bin_fn=detect_python_bin_fn,
    ).suggestions()


def frontend_test_path_suggestions(base_dir: Path) -> list[TestPathSuggestion]:
    return TestCommandDiscovery(base_dir).frontend_path_suggestions()


def default_test_commands(
    base_dir: Path,
    *,
    include_backend: bool = True,
    include_frontend: bool = True,
    frontend_test_path: str | None = None,
    detect_python_bin_fn: Callable[[Path, Path], str | None] = detect_python_bin,
) -> list[TestCommandSpec]:
    return TestCommandDiscovery(
        base_dir,
        include_backend=include_backend,
        include_frontend=include_frontend,
        frontend_test_path=frontend_test_path,
        detect_python_bin_fn=detect_python_bin_fn,
    ).default_commands()


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
