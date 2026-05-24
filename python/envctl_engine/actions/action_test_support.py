from __future__ import annotations

import ast
from dataclasses import dataclass
import json
from pathlib import Path
import re
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
from envctl_engine.shared.node_tooling import detect_package_manager, detect_python_bin
from envctl_engine.shared.parsing import parse_bool
from envctl_engine.test_output.parser_pytest import PytestOutputParser


@dataclass(frozen=True)
class TestTargetContext:
    project_name: str
    project_root: Path
    target_obj: object | None


@dataclass(frozen=True)
class TestExecutionSpec:
    index: int
    spec: TestCommandSpec
    args: list[str]
    resolved_source: str
    project_name: str
    project_root: Path
    target_obj: object | None = None


@dataclass(frozen=True)
class FailedTestManifestEntry:
    source: str
    suite: str
    failed_tests: tuple[str, ...]
    failed_files: tuple[str, ...]
    invalid_failed_tests: int = 0


@dataclass(frozen=True)
class FailedTestManifest:
    generated_at: str
    head: str
    status_hash: str
    status_lines: int
    entries: tuple[FailedTestManifestEntry, ...]


def sanitize_failed_test_identifiers(*, source: str, failed_tests: Sequence[str]) -> tuple[tuple[str, ...], int]:
    if source not in {"backend_pytest", "root_pytest"}:
        if source == "root_unittest":
            kept: list[str] = []
            invalid = 0
            seen: set[str] = set()
            for raw in failed_tests:
                candidate = normalize_unittest_test_identifier(str(raw).strip())
                if not candidate:
                    invalid += 1
                    continue
                if candidate in seen:
                    continue
                seen.add(candidate)
                kept.append(candidate)
            return tuple(kept), invalid
        normalized = tuple(str(value).strip() for value in failed_tests if str(value).strip())
        return normalized, 0
    kept: list[str] = []
    invalid = 0
    seen: set[str] = set()
    for raw in failed_tests:
        candidate = str(raw).strip()
        if not candidate:
            continue
        if not PytestOutputParser._is_valid_pytest_nodeid(candidate):
            invalid += 1
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        kept.append(candidate)
    return tuple(kept), invalid


_UNITTEST_TEST_ID_RE = r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+"


def normalize_unittest_test_identifier(raw: str) -> str | None:
    candidate = str(raw).strip()
    if not candidate:
        return None
    if re.fullmatch(_UNITTEST_TEST_ID_RE, candidate):
        return candidate
    display_match = re.fullmatch(rf"[^()]+\s+\(({_UNITTEST_TEST_ID_RE})\)", candidate)
    if display_match:
        return display_match.group(1)
    return None


def resolve_unittest_test_identifier_for_project(raw: str, project_root: Path) -> str | None:
    candidate = normalize_unittest_test_identifier(raw)
    if not candidate:
        return None
    tests_root = project_root / "tests"
    if not tests_root.is_dir():
        return candidate
    if _unittest_identifier_exists_for_project(candidate, project_root):
        return candidate
    prefixed = f"tests.{candidate}"
    if _unittest_identifier_exists_for_project(prefixed, project_root):
        return prefixed
    return None


def _unittest_identifier_exists_for_project(identifier: str, project_root: Path) -> bool:
    parts = [part for part in str(identifier).split(".") if part]
    if len(parts) < 3:
        return False
    module_parts = parts[:-2]
    class_name = parts[-2]
    method_name = parts[-1]
    if not module_parts:
        return False
    module_path = project_root.joinpath(*module_parts)
    file_path = module_path.with_suffix(".py")
    if not file_path.is_file():
        init_path = module_path / "__init__.py"
        if not init_path.is_file():
            return False
        file_path = init_path
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return False
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name == method_name:
                    return True
            return False
    return False


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


def load_failed_test_manifest(path: Path) -> FailedTestManifest | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    entries_raw = payload.get("entries")
    if not isinstance(entries_raw, list):
        return None
    entries: list[FailedTestManifestEntry] = []
    for raw_entry in entries_raw:
        if not isinstance(raw_entry, dict):
            continue
        source = str(raw_entry.get("source", "") or "").strip()
        suite = str(raw_entry.get("suite", "") or "").strip()
        sanitized_failed_tests, invalid_failed_tests = sanitize_failed_test_identifiers(
            source=source,
            failed_tests=[
                value.strip() for value in raw_entry.get("failed_tests", []) if isinstance(value, str) and value.strip()
            ],
        )
        raw_failed_files = [
            value.strip() for value in raw_entry.get("failed_files", []) if isinstance(value, str) and value.strip()
        ]
        if source in {"frontend_package_test", "package_test"}:
            derived_failed_files = frontend_failed_files_from_failed_tests(sanitized_failed_tests)
            merged_failed_files: list[str] = []
            seen_failed_files: set[str] = set()
            for failed_file in [*raw_failed_files, *derived_failed_files]:
                if failed_file in seen_failed_files:
                    continue
                seen_failed_files.add(failed_file)
                merged_failed_files.append(failed_file)
            failed_files = tuple(merged_failed_files)
        else:
            failed_files = tuple(raw_failed_files)
        if not source or (not sanitized_failed_tests and not failed_files):
            continue
        entries.append(
            FailedTestManifestEntry(
                source=source,
                suite=suite,
                failed_tests=sanitized_failed_tests,
                failed_files=failed_files,
                invalid_failed_tests=invalid_failed_tests,
            )
        )
    return FailedTestManifest(
        generated_at=str(payload.get("generated_at", "") or ""),
        head=str(payload.get("git_state", {}).get("head", "") or "")
        if isinstance(payload.get("git_state"), dict)
        else "",
        status_hash=(
            str(payload.get("git_state", {}).get("status_hash", "") or "")
            if isinstance(payload.get("git_state"), dict)
            else ""
        ),
        status_lines=(
            int(payload.get("git_state", {}).get("status_lines", 0) or 0)
            if isinstance(payload.get("git_state"), dict)
            else 0
        ),
        entries=tuple(entries),
    )


def frontend_failed_files_from_failed_tests(failed_tests: Sequence[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in failed_tests:
        text = str(raw).strip()
        if not text:
            continue
        file_name = text.split("::", 1)[0].strip()
        if not file_name or file_name in seen:
            continue
        seen.add(file_name)
        ordered.append(file_name)
    return ordered


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
