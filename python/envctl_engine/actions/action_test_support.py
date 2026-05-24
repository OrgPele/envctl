from __future__ import annotations

from pathlib import Path
import shutil
from typing import Callable, Mapping, Sequence

from envctl_engine.actions.actions_test import (
    TestCommandSpec,
    append_frontend_test_path,
    build_test_args,
    classify_test_command_source,
    normalize_frontend_test_path,
    default_test_commands,
    is_package_test_command,
    is_pytest_command,
    is_unittest_command,
)
from envctl_engine.actions.action_test_spinner_support import (
    TestSuiteSpinnerGroup as TestSuiteSpinnerGroup,
    rich_progress_available as rich_progress_available,
)
from envctl_engine.actions.action_test_manifest_support import (
    FailedTestManifest,
    FailedTestManifestEntry,
    frontend_failed_files_from_failed_tests,
    load_failed_test_manifest,
    normalize_unittest_test_identifier,
    resolve_unittest_test_identifier_for_project,
    sanitize_failed_test_identifiers,
)
from envctl_engine.actions.action_test_support_models import TestExecutionSpec, TestTargetContext
from envctl_engine.shared.node_tooling import detect_package_manager, detect_python_bin
from envctl_engine.shared.parsing import parse_bool

__all__ = [
    "FailedTestManifest",
    "FailedTestManifestEntry",
    "TestExecutionSpec",
    "TestSuiteSpinnerGroup",
    "TestTargetContext",
    "_configured_or_default_test_spec",
    "_configured_test_command_cwd",
    "_failed_rerun_spec_for_entry",
    "_pyproject_uses_poetry",
    "build_failed_test_execution_specs",
    "build_test_execution_specs",
    "build_test_target_contexts",
    "frontend_failed_files_from_failed_tests",
    "is_backend_only_selection",
    "load_failed_test_manifest",
    "normalize_backend_python_test_command",
    "normalize_unittest_test_identifier",
    "resolve_unittest_test_identifier_for_project",
    "rich_progress_available",
    "sanitize_failed_test_identifiers",
]


def build_test_target_contexts(targets: Sequence[object], *, repo_root: Path) -> list[TestTargetContext]:
    contexts: list[TestTargetContext] = []
    if targets:
        for target in targets:
            name = str(getattr(target, "name", "")).strip()
            root_raw = str(getattr(target, "root", "")).strip()
            if not root_raw:
                continue
            project_name = name or Path(root_raw).name
            contexts.append(
                TestTargetContext(
                    project_name=project_name,
                    project_root=Path(root_raw),
                    target_obj=target,
                )
            )
        if contexts:
            return contexts
    return [
        TestTargetContext(
            project_name="Main",
            project_root=repo_root,
            target_obj=None,
        )
    ]


def build_test_execution_specs(
    *,
    shared_raw_command: str | None,
    backend_raw_command: str | None,
    frontend_raw_command: str | None,
    target_contexts: Sequence[TestTargetContext],
    repo_root: Path,
    include_backend: bool,
    include_frontend: bool,
    frontend_test_path: str | None,
    run_all: bool,
    untested: bool,
    split_command: Callable[[str, Mapping[str, str]], list[str]],
    replacements_for_target: Callable[[object | None], Mapping[str, str]],
    is_legacy_tree_test_script: Callable[[list[str]], bool],
) -> list[TestExecutionSpec]:
    source = "detected"
    execution_specs: list[TestExecutionSpec] = []
    if shared_raw_command is not None:
        source = "configured"
        parsed_command: list[str] | None = None
        for target in target_contexts:
            command = split_command(shared_raw_command, replacements_for_target(target.target_obj))
            cwd = target.project_root
            if include_frontend and not include_backend and is_package_test_command(command):
                cwd = _configured_test_command_cwd(target.project_root, include_frontend=True)
                command = append_frontend_test_path(
                    command,
                    frontend_test_path,
                    project_root=target.project_root,
                    command_cwd=cwd,
                )
            if parsed_command is None:
                parsed_command = command
            if is_legacy_tree_test_script(command):
                parsed_command = command
                break
            classified_source = classify_test_command_source(
                command,
                include_backend=include_backend,
                include_frontend=include_frontend,
            )
            execution_specs.append(
                TestExecutionSpec(
                    index=0,
                    spec=TestCommandSpec(command=command, cwd=cwd, source=classified_source),
                    args=[],
                    resolved_source=classified_source,
                    project_name=target.project_name,
                    project_root=target.project_root,
                    target_obj=target.target_obj,
                )
            )
        if parsed_command is None:
            parsed_command = split_command(shared_raw_command, replacements_for_target(None))
            if include_frontend and not include_backend and is_package_test_command(parsed_command):
                parsed_command = append_frontend_test_path(
                    parsed_command,
                    frontend_test_path,
                    project_root=repo_root,
                    command_cwd=repo_root,
                )
        if is_legacy_tree_test_script(parsed_command):
            project_names = [target.project_name for target in target_contexts]
            execution_specs = [
                TestExecutionSpec(
                    index=0,
                    spec=TestCommandSpec(command=parsed_command, cwd=repo_root, source="configured"),
                    args=build_test_args(project_names, run_all=run_all, untested=untested),
                    resolved_source=source,
                    project_name="all-targets",
                    project_root=repo_root,
                    target_obj=None,
                )
            ]
    else:
        for target in target_contexts:
            target_specs: list[TestCommandSpec] = []
            if include_backend:
                backend_spec = _configured_or_default_test_spec(
                    raw_command=backend_raw_command,
                    target=target,
                    repo_root=repo_root,
                    include_backend=True,
                    include_frontend=False,
                    frontend_test_path=None,
                    split_command=split_command,
                    replacements_for_target=replacements_for_target,
                )
                if backend_spec is not None:
                    target_specs.append(backend_spec)
            if include_frontend:
                frontend_spec = _configured_or_default_test_spec(
                    raw_command=frontend_raw_command,
                    target=target,
                    repo_root=repo_root,
                    include_backend=False,
                    include_frontend=True,
                    frontend_test_path=frontend_test_path,
                    split_command=split_command,
                    replacements_for_target=replacements_for_target,
                )
                if frontend_spec is not None:
                    target_specs.append(frontend_spec)
            for spec in target_specs:
                execution_specs.append(
                    TestExecutionSpec(
                        index=0,
                        spec=spec,
                        args=[],
                        resolved_source=spec.source,
                        project_name=target.project_name,
                        project_root=target.project_root,
                        target_obj=target.target_obj,
                    )
                )
    return [
        TestExecutionSpec(
            index=index,
            spec=spec.spec,
            args=spec.args,
            resolved_source=spec.resolved_source,
            project_name=spec.project_name,
            project_root=spec.project_root,
            target_obj=spec.target_obj,
        )
        for index, spec in enumerate(execution_specs, start=1)
    ]


def _configured_or_default_test_spec(
    *,
    raw_command: str | None,
    target: TestTargetContext,
    repo_root: Path,
    include_backend: bool,
    include_frontend: bool,
    frontend_test_path: str | None,
    split_command: Callable[[str, Mapping[str, str]], list[str]],
    replacements_for_target: Callable[[object | None], Mapping[str, str]],
) -> TestCommandSpec | None:
    if raw_command is not None:
        command = split_command(raw_command, replacements_for_target(target.target_obj))
        source = "configured_frontend" if include_frontend else "configured_backend"
        if include_backend:
            if is_pytest_command(command):
                source = "backend_pytest"
            elif is_unittest_command(command):
                source = "root_unittest"
            command = normalize_backend_python_test_command(command, target.project_root)
        if include_frontend and is_package_test_command(command):
            command = append_frontend_test_path(
                command,
                frontend_test_path,
                project_root=target.project_root,
                command_cwd=_configured_test_command_cwd(target.project_root, include_frontend=True),
            )
            source = "frontend_package_test"
        cwd = _configured_test_command_cwd(target.project_root, include_frontend=include_frontend)
        return TestCommandSpec(
            command=command,
            cwd=cwd,
            source=source,
        )
    target_specs = default_test_commands(
        target.project_root,
        include_backend=include_backend,
        include_frontend=include_frontend,
        frontend_test_path=frontend_test_path,
    )
    if not target_specs and target.project_root != repo_root:
        target_specs = default_test_commands(
            repo_root,
            include_backend=include_backend,
            include_frontend=include_frontend,
            frontend_test_path=frontend_test_path,
        )
    if not target_specs:
        return None
    return target_specs[0]


def _configured_test_command_cwd(project_root: Path, *, include_frontend: bool) -> Path:
    if include_frontend and (project_root / "frontend" / "package.json").is_file():
        return project_root / "frontend"
    return project_root


def normalize_backend_python_test_command(command: Sequence[str], project_root: Path) -> list[str]:
    rendered = [str(part) for part in command]
    if not rendered or rendered[0] not in {"python", "python3", "python3.12"}:
        return rendered

    backend_root = project_root / "backend"
    pyproject = backend_root / "pyproject.toml"
    if pyproject.is_file() and _pyproject_uses_poetry(pyproject) and shutil.which("poetry"):
        return ["poetry", "--project", str(backend_root), "run", "python", *rendered[1:]]

    python_exe = detect_python_bin(backend_root, project_root)
    if python_exe and "/" in python_exe:
        return [python_exe, *rendered[1:]]
    return rendered


def _pyproject_uses_poetry(pyproject: Path) -> bool:
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return "[tool.poetry]" in text or "[tool.pdm]" in text


def build_failed_test_execution_specs(
    *,
    target_contexts: Sequence[TestTargetContext],
    repo_root: Path,
    manifests_by_project: Mapping[str, FailedTestManifest],
    shared_raw_command: str | None,
    backend_raw_command: str | None,
    frontend_raw_command: str | None,
) -> list[TestExecutionSpec]:
    execution_specs: list[TestExecutionSpec] = []
    unsupported: list[str] = []
    for target in target_contexts:
        manifest = manifests_by_project.get(target.project_name)
        if manifest is None:
            continue
        for entry in manifest.entries:
            spec = _failed_rerun_spec_for_entry(
                entry,
                project_name=target.project_name,
                project_root=target.project_root,
                repo_root=repo_root,
                target_obj=target.target_obj,
            )
            if isinstance(spec, str):
                unsupported.append(spec)
                continue
            if spec is not None:
                execution_specs.append(spec)
    if unsupported:
        first = unsupported[0]
        raise RuntimeError(first)
    return [
        TestExecutionSpec(
            index=index,
            spec=spec.spec,
            args=spec.args,
            resolved_source=spec.resolved_source,
            project_name=spec.project_name,
            project_root=spec.project_root,
            target_obj=spec.target_obj,
        )
        for index, spec in enumerate(execution_specs, start=1)
    ]


def _failed_rerun_spec_for_entry(
    entry: FailedTestManifestEntry,
    *,
    project_name: str,
    project_root: Path,
    repo_root: Path,
    target_obj: object | None,
) -> TestExecutionSpec | str | None:
    source = entry.source
    if source in {"backend_pytest", "root_pytest"}:
        if not entry.failed_tests:
            return None
        python_roots = (project_root / "backend", project_root, repo_root) if source == "backend_pytest" else (
            project_root,
            repo_root,
        )
        python_exe = detect_python_bin(*python_roots)
        if not python_exe:
            suite_name = "backend pytest" if source == "backend_pytest" else "root pytest"
            return (
                f"Failed-only reruns are unavailable for {project_name} {suite_name} "
                "because no Python interpreter was found."
            )
        command = [python_exe, "-m", "pytest", *entry.failed_tests]
        if source == "backend_pytest":
            command = normalize_backend_python_test_command(command, project_root)
        return TestExecutionSpec(
            index=0,
            spec=TestCommandSpec(
                command=command,
                cwd=project_root,
                source=source,
            ),
            args=[],
            resolved_source=source,
            project_name=project_name,
            project_root=project_root,
            target_obj=target_obj,
        )
    if source == "root_unittest":
        failed_tests = [
            normalized
            for value in entry.failed_tests
            if (normalized := resolve_unittest_test_identifier_for_project(value, project_root))
        ]
        if not failed_tests:
            return None
        python_exe = detect_python_bin(project_root, repo_root)
        if not python_exe:
            return (
                f"Failed-only reruns are unavailable for {project_name} unittest "
                "because no Python interpreter was found."
            )
        return TestExecutionSpec(
            index=0,
            spec=TestCommandSpec(
                command=[python_exe, "-m", "unittest", *failed_tests],
                cwd=project_root,
                source=source,
            ),
            args=[],
            resolved_source=source,
            project_name=project_name,
            project_root=project_root,
            target_obj=target_obj,
        )
    if source in {"frontend_package_test", "package_test"}:
        package_root = project_root / "frontend" if source == "frontend_package_test" else project_root
        failed_files = [
            normalized
            for value in entry.failed_files
            if (
                normalized := normalize_frontend_test_path(
                    value,
                    project_root=project_root,
                    command_cwd=package_root,
                )
            )
        ]
        if not failed_files:
            return None
        manager = detect_package_manager(package_root)
        if not manager:
            return (
                f"Failed-only reruns are unavailable for {project_name} {entry.suite or source} "
                "because no supported package manager was detected."
            )
        command = [manager, "run", "test", "--", *failed_files]
        return TestExecutionSpec(
            index=0,
            spec=TestCommandSpec(
                command=command,
                cwd=package_root,
                source=source,
            ),
            args=[],
            resolved_source=source,
            project_name=project_name,
            project_root=project_root,
            target_obj=target_obj,
        )
    if source == "configured":
        return (
            f"Failed-only reruns are not supported for {project_name} "
            "because the previous test run used a custom configured command."
        )
    return f"Failed-only reruns are not supported for {project_name} ({source}). Run the full suite first."


def is_backend_only_selection(
    backend_flag: object, frontend_flag: object, service_types: set[str]
) -> tuple[bool, bool]:
    include_backend = backend_flag if isinstance(backend_flag, bool) else parse_bool(backend_flag, True)
    include_frontend = frontend_flag if isinstance(frontend_flag, bool) else parse_bool(frontend_flag, True)
    if backend_flag is None and frontend_flag is None:
        if service_types == {"backend"}:
            include_backend = True
            include_frontend = False
        elif service_types == {"frontend"}:
            include_backend = False
            include_frontend = True
    return include_backend, include_frontend
