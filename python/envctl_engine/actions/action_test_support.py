from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
from typing import Any, Callable, Mapping, Sequence

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
from envctl_engine.shared.node_tooling import detect_package_manager, detect_python_bin
from envctl_engine.shared.parsing import parse_bool
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.test_output.failure_summary import extract_failure_summary_excerpt
from envctl_engine.test_output.parser_pytest import PytestOutputParser
from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.test_output.symbols import format_duration
from envctl_engine.ui.color_policy import colors_enabled


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


def _outcome_int(item: Mapping[str, object], key: str, *, default: int = 0) -> int:
    value = item.get(key, default)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def collect_failed_tests(
    outcomes: Sequence[Mapping[str, object]],
    *,
    project_name: str | None = None,
) -> list[tuple[str, str, str]]:
    collected: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    ordered = sorted(outcomes, key=lambda value: _outcome_int(value, "index"))
    for item in ordered:
        if project_name is not None:
            item_project_name = str(item.get("project_name", "")).strip()
            if item_project_name != project_name:
                continue
        source = str(item.get("suite", "suite"))
        parsed = item.get("parsed")
        failed_tests = list(getattr(parsed, "failed_tests", []) or []) if parsed is not None else []
        error_details = dict(getattr(parsed, "error_details", {}) or {}) if parsed is not None else {}
        suite_name = suite_display_name(source, failed_only=bool(item.get("failed_only", False)))
        for failed_test in failed_tests:
            test_name = str(failed_test).strip()
            if not test_name:
                continue
            dedupe_key = (suite_name, test_name)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            error_text = resolve_failed_test_error(error_details, test_name)
            collected.append((suite_name, test_name, error_text))
    return collected


def collect_failed_test_manifest_entries(
    outcomes: Sequence[Mapping[str, object]],
    *,
    project_name: str | None = None,
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    ordered = sorted(outcomes, key=lambda value: _outcome_int(value, "index"))
    for item in ordered:
        if project_name is not None:
            item_project_name = str(item.get("project_name", "")).strip()
            if item_project_name != project_name:
                continue
        source = str(item.get("suite", "")).strip()
        if not source:
            continue
        parsed = item.get("parsed")
        raw_failed_tests = (
            [
                str(failed_test).strip()
                for failed_test in list(getattr(parsed, "failed_tests", []) or [])
                if str(failed_test).strip()
            ]
            if parsed is not None
            else []
        )
        failed_tests, invalid_failed_tests = sanitize_failed_test_identifiers(
            source=source,
            failed_tests=raw_failed_tests,
        )
        failed_files = (
            frontend_failed_files_from_failed_tests(failed_tests)
            if source in {"frontend_package_test", "package_test"}
            else []
        )
        if not failed_tests and not failed_files:
            continue
        entries.append(
            {
                "suite": suite_display_name(source, failed_only=bool(item.get("failed_only", False))),
                "source": source,
                "failed_tests": list(failed_tests),
                "failed_files": failed_files,
                "invalid_failed_tests": invalid_failed_tests,
            }
        )
    return entries


def collect_generic_suite_failures(
    outcomes: Sequence[Mapping[str, object]],
    *,
    project_name: str | None = None,
) -> list[tuple[str, str]]:
    collected: list[tuple[str, str]] = []
    ordered = sorted(outcomes, key=lambda value: _outcome_int(value, "index"))
    for item in ordered:
        if project_name is not None:
            item_project_name = str(item.get("project_name", "")).strip()
            if item_project_name != project_name:
                continue
        if _outcome_int(item, "returncode") == 0:
            continue
        parsed = item.get("parsed")
        failed_tests = list(getattr(parsed, "failed_tests", []) or []) if parsed is not None else []
        if failed_tests:
            continue
        summary = str(item.get("failure_details", "") or item.get("failure_summary", "") or "").strip()
        if not summary:
            summary = "Test command failed before envctl could extract failed tests."
        suite_name = suite_display_name(
            str(item.get("suite", "suite")),
            failed_only=bool(item.get("failed_only", False)),
        )
        collected.append((suite_name, summary))
    return collected


def collect_suite_failure_contexts(
    outcomes: Sequence[Mapping[str, object]],
    *,
    project_name: str | None = None,
) -> list[tuple[str, str]]:
    collected: list[tuple[str, str]] = []
    ordered = sorted(outcomes, key=lambda value: _outcome_int(value, "index"))
    for item in ordered:
        if project_name is not None:
            item_project_name = str(item.get("project_name", "")).strip()
            if item_project_name != project_name:
                continue
        if _outcome_int(item, "returncode") == 0:
            continue
        parsed = item.get("parsed")
        failed_tests = list(getattr(parsed, "failed_tests", []) or []) if parsed is not None else []
        if not failed_tests:
            continue
        context_text = str(item.get("failure_details", "") or "").strip()
        if not context_text:
            continue
        suite_name = suite_display_name(
            str(item.get("suite", "suite")),
            failed_only=bool(item.get("failed_only", False)),
        )
        collected.append((suite_name, context_text))
    return collected


def resolve_failed_test_error(error_details: Mapping[str, object], test_name: str) -> str:
    direct = error_details.get(test_name)
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    if "::" in test_name:
        file_key = test_name.split("::", 1)[0]
        file_error = error_details.get(file_key)
        if isinstance(file_error, str) and file_error.strip():
            return file_error.strip()
    return ""


def git_state_components(project_root: Path) -> tuple[str, str, int]:
    head = ""
    status = ""
    try:
        head_proc = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if head_proc.returncode == 0:
            head = (head_proc.stdout or "").strip()
        status_proc = subprocess.run(
            ["git", "-C", str(project_root), "status", "--porcelain=1"],
            capture_output=True,
            text=True,
            check=False,
        )
        if status_proc.returncode == 0:
            status = status_proc.stdout or ""
    except Exception:
        head = ""
        status = ""
    status_hash = hashlib.sha1(status.encode("utf-8")).hexdigest()
    status_lines = len([line for line in status.splitlines() if line.strip()])
    return head, status_hash, status_lines


def suite_display_name(source: str, *, failed_only: bool = False) -> str:
    if source == "backend_pytest":
        return "Backend (pytest, failed only)" if failed_only else "Backend (pytest)"
    if source == "root_pytest":
        return "Repository tests (pytest, failed only)" if failed_only else "Repository tests (pytest)"
    if source == "configured_backend":
        return "Backend (failed only)" if failed_only else "Backend"
    if source == "frontend_package_test":
        return "Frontend (package test, failed only)" if failed_only else "Frontend (package test)"
    if source == "configured_frontend":
        return "Frontend (failed only)" if failed_only else "Frontend"
    if source == "root_unittest":
        return "Repository tests (unittest, failed only)" if failed_only else "Repository tests (unittest)"
    if source == "package_test":
        return "Repository package test (failed only)" if failed_only else "Repository package test"
    if source == "configured":
        return "Test command (failed only)" if failed_only else "Test command"
    return source.replace("_", " ")


def short_failed_summary_path(*, run_dir: Path, project_name: str) -> Path:
    digest = hashlib.sha1(project_name.encode("utf-8")).hexdigest()[:10]
    run_root = run_dir.parent.parent
    return run_root / f"ft_{digest}.txt"


def new_test_results_run_dir(
    state_repository: Any,
    run_id: str,
    *,
    now: Callable[[], str] | None = None,
) -> Path:
    results_root = state_repository.test_results_dir_path(run_id)
    results_root.mkdir(parents=True, exist_ok=True)
    stamp = now() if now is not None else datetime.now(tz=UTC).strftime("run_%Y%m%d_%H%M%S")
    candidate = results_root / stamp
    if not candidate.exists():
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    suffix = 1
    while True:
        suffixed = results_root / f"{stamp}_{suffix}"
        if not suffixed.exists():
            suffixed.mkdir(parents=True, exist_ok=True)
            return suffixed
        suffix += 1


def write_failed_tests_summary(
    *,
    run_dir: Path,
    project_name: str,
    project_root: Path,
    outcomes: Sequence[Mapping[str, object]],
    format_summary_error_lines: Callable[[str], Sequence[str]],
    previous_entry: Mapping[str, object] | None = None,
) -> dict[str, object]:
    safe_project = project_name.replace(" ", "_")
    output_dir = run_dir / safe_project
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "failed_tests_summary.txt"
    short_summary_path = short_failed_summary_path(run_dir=run_dir, project_name=project_name)
    state_path = output_dir / "test_state.txt"
    manifest_path = output_dir / "failed_tests_manifest.json"

    failures = collect_failed_tests(outcomes, project_name=project_name)
    generic_suite_failures = collect_generic_suite_failures(outcomes, project_name=project_name)
    suite_failure_contexts = collect_suite_failure_contexts(outcomes, project_name=project_name)
    manifest_entries = collect_failed_test_manifest_entries(outcomes, project_name=project_name)
    failed_only = any(
        bool(item.get("failed_only", False))
        for item in outcomes
        if str(item.get("project_name", "")).strip() == project_name
    )
    generated_at = datetime.now().astimezone()
    lines = [
        "# envctl Failed Test Summary",
        f"# Generated at: {generated_at.strftime('%a %b %d %H:%M:%S %Z %Y')}",
        "",
    ]
    if failures:
        for suite_name, failed_test, error_text in failures:
            clean_suite_name = strip_ansi(str(suite_name)).strip()
            clean_failed_test = strip_ansi(str(failed_test)).strip()
            lines.append(f"[{clean_suite_name}]")
            lines.append(f"- {clean_failed_test}")
            if error_text:
                for detail in format_summary_error_lines(str(error_text)):
                    lines.append(f"    {detail}")
            lines.append("")
        for suite_name, context_text in suite_failure_contexts:
            clean_suite_name = strip_ansi(str(suite_name)).strip()
            lines.append(f"[{clean_suite_name}]")
            lines.append("suite context:")
            for detail in format_summary_error_lines(str(context_text)):
                lines.append(f"    {detail}")
            lines.append("")
    elif generic_suite_failures:
        for suite_name, summary in generic_suite_failures:
            clean_suite_name = strip_ansi(str(suite_name)).strip()
            lines.append(f"[{clean_suite_name}]")
            lines.append("- suite failed before envctl could extract failed tests")
            for detail in format_summary_error_lines(str(summary)):
                lines.append(f"    {detail}")
            lines.append("")
    else:
        lines.append("No failed tests.")
        lines.append("")
    summary_text = "\n".join(lines)
    summary_path.write_text(summary_text, encoding="utf-8")
    short_summary_path.write_text(summary_text, encoding="utf-8")

    head, status_hash, status_lines = git_state_components(project_root)
    state_path.write_text(
        f"state|{project_name}|{project_root}|{head}|{status_hash}|{status_lines}\n",
        encoding="utf-8",
    )
    manifest_payload = {
        "generated_at": generated_at.isoformat(),
        "project_name": project_name,
        "project_root": str(project_root),
        "git_state": {
            "head": head,
            "status_hash": status_hash,
            "status_lines": status_lines,
        },
        "entries": manifest_entries,
    }
    manifest_path.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True), encoding="utf-8")

    preserve_previous = (
        failed_only
        and not failures
        and bool(generic_suite_failures)
        and not manifest_entries
        and previous_entry is not None
    )
    if preserve_previous:
        assert previous_entry is not None
        previous_manifest_path_raw = str(previous_entry.get("manifest_path", "") or "").strip()
        previous_manifest = (
            load_failed_test_manifest(Path(previous_manifest_path_raw)) if previous_manifest_path_raw else None
        )
        if previous_manifest is not None and previous_manifest.entries:
            preserved: dict[str, object] = dict(previous_entry)
            preserved["status"] = "failed"
            preserved["updated_at"] = generated_at.isoformat()
            preserved["preserved_after_failed_only_extraction_failure"] = True
            return preserved

    return {
        "summary_path": str(summary_path),
        "short_summary_path": str(short_summary_path),
        "state_path": str(state_path),
        "manifest_path": str(manifest_path),
        "status": "failed" if failures or generic_suite_failures else "passed",
        "failed_tests": len(failures),
        "failed_manifest_entries": len(manifest_entries),
        "summary_excerpt": extract_failure_summary_excerpt(summary_text, max_lines=3),
        "updated_at": generated_at.isoformat(),
    }


def persist_test_summary_artifacts(
    *,
    runtime: Any,
    route: Any,
    targets: Sequence[object],
    outcomes: Sequence[Mapping[str, object]],
    format_summary_error_lines: Callable[[str], Sequence[str]],
) -> dict[str, dict[str, object]]:
    if not targets:
        return {}

    project_roots: dict[str, Path] = {}
    for target in targets:
        name = str(getattr(target, "name", "")).strip()
        root_raw = str(getattr(target, "root", "")).strip()
        if not name or not root_raw:
            continue
        project_roots[name] = Path(root_raw)
    if not project_roots:
        for outcome in outcomes:
            name = str(outcome.get("project_name", "")).strip()
            root_raw = str(outcome.get("project_root", "")).strip()
            if not name or not root_raw:
                continue
            project_roots[name] = Path(root_raw)
    if not project_roots:
        return {}

    state = runtime.load_existing_state(mode=route.mode)
    if state is None:
        return {}

    run_dir = new_test_results_run_dir(runtime.state_repository, state.run_id)
    existing = state.metadata.get("project_test_summaries")
    metadata = dict(existing) if isinstance(existing, dict) else {}
    summaries: dict[str, dict[str, object]] = {}
    for project_name, project_root in project_roots.items():
        previous_entry = metadata.get(project_name)
        summaries[project_name] = write_failed_tests_summary(
            run_dir=run_dir,
            project_name=project_name,
            project_root=project_root,
            outcomes=outcomes,
            previous_entry=previous_entry if isinstance(previous_entry, dict) else None,
            format_summary_error_lines=format_summary_error_lines,
        )

    metadata.update(summaries)
    state.metadata["project_test_summaries"] = metadata
    state.metadata["project_test_results_root"] = str(run_dir)
    state.metadata["project_test_results_updated_at"] = datetime.now(tz=UTC).isoformat()

    runtime.state_repository.save_resume_state(
        state=state,
        emit=runtime.emit,
        runtime_map_builder=build_runtime_map,
    )
    runtime.emit(
        "test.summary.persisted",
        mode=route.mode,
        projects=sorted(summaries),
        run_dir=str(run_dir),
    )
    return summaries


def _outcome_float(item: Mapping[str, object], key: str, *, default: float = 0.0) -> float:
    value = item.get(key, default)
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _parsed_int(parsed: object, key: str) -> int:
    value = getattr(parsed, key, 0) if parsed is not None else 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def render_test_suite_overview(
    outcomes: Sequence[Mapping[str, object]],
    *,
    colorize: Callable[..., str],
    summary_metadata: Mapping[str, Mapping[str, object]] | None = None,
    render_summary_path: Callable[[str], str] | None = None,
) -> list[str]:
    if not outcomes:
        return []
    lines: list[str] = [
        "",
        colorize("======================================================================", fg="cyan"),
        colorize("Test Suite Summary", fg="cyan", bold=True),
        colorize("======================================================================", fg="cyan"),
    ]
    project_labels = {
        str(item.get("project_name", "")).strip() for item in outcomes if str(item.get("project_name", "")).strip()
    }
    multi_project = len(project_labels) > 1
    total_passed = 0
    total_failed = 0
    total_skipped = 0
    total_known = 0
    total_duration = 0.0
    grouped_outcomes: dict[str, list[Mapping[str, object]]] = {}
    for item in sorted(
        outcomes,
        key=lambda value: (
            str(value.get("project_name", "")).lower(),
            _outcome_int(value, "index"),
        ),
    ):
        project_name = str(item.get("project_name", "")).strip() or "Main"
        grouped_outcomes.setdefault(project_name, []).append(item)

    for project_name, project_items in grouped_outcomes.items():
        if multi_project:
            lines.append(colorize(project_name, fg="blue", bold=True))
        for item in project_items:
            source = str(item.get("suite", "suite"))
            label = suite_display_name(source, failed_only=bool(item.get("failed_only", False)))
            label_rendered = colorize(label, fg="cyan", bold=True)
            if multi_project:
                label_rendered = f"  {label_rendered}"
            returncode = _outcome_int(item, "returncode", default=1)
            parsed = item.get("parsed")
            parsed_total = _parsed_int(parsed, "total")
            counts_detected = bool(getattr(parsed, "counts_detected", False)) if parsed is not None else False
            passed = _parsed_int(parsed, "passed")
            failed = _parsed_int(parsed, "failed")
            skipped = _parsed_int(parsed, "skipped")
            duration_ms = _outcome_float(item, "duration_ms")
            duration_text = format_duration(max(duration_ms / 1000.0, 0.0))

            icon = colorize("✓", fg="green", bold=True) if returncode == 0 else colorize("✗", fg="red", bold=True)
            if counts_detected:
                total_passed += passed
                total_failed += failed
                total_skipped += skipped
                total_known += parsed_total
                total_duration += max(duration_ms / 1000.0, 0.0)
                passed_text = colorize(f"{passed} passed", fg="green")
                failed_text = colorize(f"{failed} failed", fg="red")
                skipped_text = colorize(f"{skipped} skipped", fg="yellow")
                lines.append(
                    f"{icon} {label_rendered}: {passed_text}, {failed_text}, {skipped_text}"
                    f" (total {parsed_total}, duration {duration_text})"
                )
            else:
                total_duration += max(duration_ms / 1000.0, 0.0)
                status_text = (
                    colorize("completed", fg="green", bold=True)
                    if returncode == 0
                    else colorize("failed", fg="red", bold=True)
                )
                lines.append(
                    f"{icon} {label_rendered}: {status_text} (no parsed test counts, duration {duration_text})"
                )
        summary_entry = summary_metadata.get(project_name) if isinstance(summary_metadata, Mapping) else None
        if isinstance(summary_entry, Mapping) and str(summary_entry.get("status", "")).strip().lower() == "failed":
            summary_path = str(
                summary_entry.get("short_summary_path") or summary_entry.get("summary_path") or ""
            ).strip()
            if summary_path:
                prefix = "  " if multi_project else ""
                label = colorize("failure summary:", fg="gray")
                lines.append(f"{prefix}{label}")
                rendered_path = render_summary_path(summary_path) if render_summary_path else summary_path
                lines.append(f"{prefix}{rendered_path}")
        if multi_project:
            lines.append("")

    if total_known > 0:
        overall_prefix = colorize("Overall:", fg="cyan", bold=True)
        overall_passed = colorize(f"{total_passed} passed", fg="green")
        overall_failed = colorize(f"{total_failed} failed", fg="red")
        overall_skipped = colorize(f"{total_skipped} skipped", fg="yellow")
        lines.append(
            f"{overall_prefix} {overall_passed}, {overall_failed}, {overall_skipped}"
            f" (total {total_known}, duration {format_duration(total_duration)})"
        )
    lines.append(colorize("======================================================================", fg="cyan"))
    return lines


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


def rich_progress_available() -> tuple[bool, str]:
    try:
        if importlib.util.find_spec("rich.progress") is not None:
            return True, ""
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"find_spec_error:{type(exc).__name__}"
    try:
        __import__("rich.progress")
        return True, ""
    except Exception as exc:  # pragma: no cover - defensive
        return False, f"import_error:{type(exc).__name__}"


class TestSuiteSpinnerGroup:
    def __init__(
        self,
        *,
        execution_specs: list[TestExecutionSpec],
        enabled: bool,
        policy: Any,
        emit: Any,
        suite_label_resolver: Callable[[str], str],
        multi_project: bool,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._execution_specs = list(execution_specs)
        self._enabled = bool(enabled) and str(getattr(policy, "backend", "")) == "rich"
        self._style = str(getattr(policy, "style", "dots") or "dots")
        self._emit = emit if callable(emit) else None
        self._suite_label_resolver = suite_label_resolver
        self._multi_project = bool(multi_project)
        self._env = dict(env or {})
        self._stream = sys.stderr
        self._lock = threading.Lock()
        self._progress: Any = None
        self._tasks: dict[int, Any] = {}
        self._labels_plain: dict[int, str] = {}
        self._labels_render: dict[int, str] = {}
        self._project_for_index: dict[int, str] = {}
        ordered_projects: list[str] = []
        for item in self._execution_specs:
            name = str(item.project_name).strip()
            if not name or name in ordered_projects:
                continue
            ordered_projects.append(name)
        self._ordered_projects = list(ordered_projects)
        self._project_header_color = "cyan"

    def __enter__(self) -> "TestSuiteSpinnerGroup":
        if not self._enabled:
            return self
        try:
            console_module = __import__("rich.console", fromlist=["Console"])
            progress_module = __import__("rich.progress", fromlist=["Progress", "SpinnerColumn", "TextColumn"])
            console_cls = getattr(console_module, "Console")
            progress_cls = getattr(progress_module, "Progress")
            spinner_column_cls = getattr(progress_module, "SpinnerColumn")
            text_column_cls = getattr(progress_module, "TextColumn")

            class _PerTaskSpinnerColumn(spinner_column_cls):  # type: ignore[misc, valid-type]
                def render(self, task):  # noqa: ANN001
                    if bool(getattr(task, "fields", {}).get("is_header", False)):
                        from rich.text import Text

                        return Text(" ")
                    if bool(getattr(task, "finished", False)):
                        symbol = task.fields.get("finished_symbol") if hasattr(task, "fields") else None
                        if isinstance(symbol, str) and symbol.strip():
                            from rich.text import Text

                            try:
                                return Text.from_markup(symbol)
                            except Exception:
                                return Text(symbol)
                    return super().render(task)

            console = console_cls(
                file=self._stream,
                no_color=not colors_enabled(self._env, stream=self._stream, interactive_tty=True),
                force_terminal=True,
            )
            self._progress = progress_cls(
                _PerTaskSpinnerColumn(spinner_name=self._style, finished_text=" "),
                text_column_cls("{task.description}", markup=True),
                console=console,
                transient=False,
                auto_refresh=True,
            )
            self._progress.start()
            grouped_specs: dict[str, list[TestExecutionSpec]] = {}
            for execution in self._execution_specs:
                grouped_specs.setdefault(execution.project_name, []).append(execution)

            for project_name in self._ordered_projects:
                execution_list = grouped_specs.get(project_name, [])
                if self._multi_project:
                    project_color = self._project_header_color
                    escaped_project = self._escape_markup(project_name)
                    header_line = f"[bold {project_color}]{escaped_project}[/]"
                    self._progress.add_task(
                        header_line,
                        total=1,
                        completed=1,
                        finished_symbol=" ",
                        is_header=True,
                    )
                for execution in execution_list:
                    label_plain = self._descriptor(execution, render=False)
                    label_render = self._descriptor(execution, render=True)
                    self._labels_plain[execution.index] = label_plain
                    self._labels_render[execution.index] = label_render
                    self._project_for_index[execution.index] = project_name
                    queued_line = f"  - {label_render}: [yellow]queued[/yellow]"
                    task_id = self._progress.add_task(queued_line, total=None)
                    self._tasks[execution.index] = task_id
            self._emit_lifecycle("start", f"Tracking {len(self._execution_specs)} test suites")
        except Exception:
            self._enabled = False
            self._progress = None
            self._tasks.clear()
            self._labels_plain.clear()
            self._labels_render.clear()
            self._project_for_index.clear()
        return self

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        _ = exc_type, exc, tb
        with self._lock:
            if self._progress is not None:
                try:
                    self._progress.stop()
                except Exception:
                    pass
                self._progress = None
            self._emit_lifecycle("stop")
        return False

    def _emit_lifecycle(self, state: str, message: str | None = None, *, suite_index: int | None = None) -> None:
        if not callable(self._emit):
            return
        payload: dict[str, object] = {
            "component": "action.test.parallel",
            "op_id": "action.test.parallel",
            "state": state,
        }
        if message:
            payload["message"] = message
        if suite_index is not None:
            payload["suite_index"] = suite_index
        self._emit("ui.spinner.lifecycle", **payload)

    @staticmethod
    def _escape_markup(text: str) -> str:
        return str(text).replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")

    def _suite_color(self, source: str) -> str:
        normalized = str(source).strip().lower()
        if normalized in {"backend_pytest", "root_pytest", "root_unittest"}:
            return "cyan"
        if normalized == "frontend_package_test":
            return "magenta"
        if normalized == "package_test":
            return "blue"
        return "yellow"

    def _descriptor(self, execution: TestExecutionSpec, *, render: bool) -> str:
        suite_label = self._suite_label_resolver(execution.spec.source)
        if not render:
            return suite_label
        suite_color = self._suite_color(execution.spec.source)
        escaped_suite = self._escape_markup(suite_label)
        return f"[{suite_color}]{escaped_suite}[/]"

    def mark_running(self, execution: TestExecutionSpec) -> None:
        index = execution.index
        label_plain = self._labels_plain.get(index, self._descriptor(execution, render=False))
        label_render = self._labels_render.get(index, self._descriptor(execution, render=True))
        project_name = self._project_for_index.get(index, str(execution.project_name))
        plain_line = f"{project_name} / {label_plain}: running"
        render_line = f"  - {label_render}: [blue]running[/blue]"
        self._update_line(index, plain_line=plain_line, render_line=render_line, state="update")

    def mark_progress(self, execution: TestExecutionSpec, *, status_text: str) -> None:
        index = execution.index
        label_plain = self._labels_plain.get(index, self._descriptor(execution, render=False))
        label_render = self._labels_render.get(index, self._descriptor(execution, render=True))
        project_name = self._project_for_index.get(index, str(execution.project_name))
        escaped_status = self._escape_markup(status_text)
        plain_line = f"{project_name} / {label_plain}: {status_text}"
        render_line = f"  - {label_render}: [blue]{escaped_status}[/blue]"
        self._update_line(index, plain_line=plain_line, render_line=render_line, state="update")

    def mark_finished(
        self,
        execution: TestExecutionSpec,
        *,
        success: bool,
        duration_text: str,
        parsed: object | None,
    ) -> None:
        passed = int(getattr(parsed, "passed", 0) or 0) if parsed is not None else 0
        failed = int(getattr(parsed, "failed", 0) or 0) if parsed is not None else 0
        skipped = int(getattr(parsed, "skipped", 0) or 0) if parsed is not None else 0
        total = int(getattr(parsed, "total", 0) or 0) if parsed is not None else 0
        status = "passed" if success else "failed"
        label_plain = self._labels_plain.get(execution.index, self._descriptor(execution, render=False))
        label_render = self._labels_render.get(execution.index, self._descriptor(execution, render=True))
        project_name = self._project_for_index.get(execution.index, str(execution.project_name))
        metrics = f" [dim]• {passed}p/{failed}f/{skipped}s[/dim]" if total > 0 else ""
        status_text = "[green]passed[/green]" if success else "[red]failed[/red]"
        plain_line = f"{project_name} / {label_plain}: {status} ({duration_text})"
        render_line = f"  - {label_render}: {status_text} ({duration_text}){metrics}"
        self._update_line(
            execution.index,
            plain_line=plain_line,
            render_line=render_line,
            state="success" if success else "fail",
            stop_task=True,
            finished_symbol=("[green]✓[/green]" if success else "[red]✗[/red]"),
        )

    def _update_line(
        self,
        index: int,
        *,
        plain_line: str,
        render_line: str,
        state: str,
        stop_task: bool = False,
        finished_symbol: str = "",
    ) -> None:
        self._emit_lifecycle(state, plain_line, suite_index=index)
        with self._lock:
            if self._progress is None:
                return
            task_id = self._tasks.get(index)
            if task_id is None:
                return
            try:
                if stop_task:
                    self._progress.update(
                        task_id,
                        description=render_line,
                        total=1,
                        completed=1,
                        finished_symbol=finished_symbol,
                    )
                else:
                    self._progress.update(task_id, description=render_line)
                if stop_task:
                    self._progress.stop_task(task_id)
            except Exception:
                return


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
