from __future__ import annotations

from pathlib import Path
import shutil
from typing import Callable, Mapping, Sequence

from envctl_engine.actions.action_failed_test_spec_support import (
    build_failed_test_execution_specs as _build_failed_test_execution_specs,
    failed_rerun_spec_for_entry,
)
from envctl_engine.actions.action_test_command_support import (
    build_test_execution_specs as _build_test_execution_specs,
    build_test_target_contexts,
    configured_or_default_test_spec,
    configured_test_command_cwd,
    normalize_backend_python_test_command as _normalize_backend_python_test_command,
    pyproject_uses_poetry,
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
from envctl_engine.actions.action_test_spinner_support import (
    TestSuiteSpinnerGroup as TestSuiteSpinnerGroup,
    rich_progress_available as rich_progress_available,
)
from envctl_engine.actions.action_test_support_models import TestExecutionSpec, TestTargetContext
from envctl_engine.actions.actions_test import TestCommandSpec
from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.node_tooling import detect_package_manager
from envctl_engine.shared.parsing import parse_bool

__all__ = [
    "FailedTestManifest",
    "FailedTestManifestEntry",
    "TestCommandSpec",
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
    is_legacy_tree_test_script: Callable[[Sequence[str]], bool],
) -> list[TestExecutionSpec]:
    return _build_test_execution_specs(
        shared_raw_command=shared_raw_command,
        backend_raw_command=backend_raw_command,
        frontend_raw_command=frontend_raw_command,
        target_contexts=target_contexts,
        repo_root=repo_root,
        include_backend=include_backend,
        include_frontend=include_frontend,
        frontend_test_path=frontend_test_path,
        run_all=run_all,
        untested=untested,
        split_command=split_command,
        replacements_for_target=replacements_for_target,
        is_legacy_tree_test_script=is_legacy_tree_test_script,
        configured_or_default_spec_fn=_configured_or_default_test_spec,
    )


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
    return configured_or_default_test_spec(
        raw_command=raw_command,
        target=target,
        repo_root=repo_root,
        include_backend=include_backend,
        include_frontend=include_frontend,
        frontend_test_path=frontend_test_path,
        split_command=split_command,
        replacements_for_target=replacements_for_target,
        normalize_backend_command_fn=normalize_backend_python_test_command,
    )


def _configured_test_command_cwd(project_root: Path, *, include_frontend: bool) -> Path:
    return configured_test_command_cwd(project_root, include_frontend=include_frontend)


def normalize_backend_python_test_command(command: Sequence[str], project_root: Path) -> list[str]:
    return _normalize_backend_python_test_command(command, project_root, which_fn=shutil.which)


def _pyproject_uses_poetry(pyproject: Path) -> bool:
    return pyproject_uses_poetry(pyproject)


def build_failed_test_execution_specs(
    *,
    target_contexts: Sequence[TestTargetContext],
    repo_root: Path,
    manifests_by_project: Mapping[str, FailedTestManifest],
    shared_raw_command: str | None,
    backend_raw_command: str | None,
    frontend_raw_command: str | None,
) -> list[TestExecutionSpec]:
    return _build_failed_test_execution_specs(
        target_contexts=target_contexts,
        repo_root=repo_root,
        manifests_by_project=manifests_by_project,
        shared_raw_command=shared_raw_command,
        backend_raw_command=backend_raw_command,
        frontend_raw_command=frontend_raw_command,
        failed_rerun_spec_for_entry_fn=_failed_rerun_spec_for_entry,
    )


def _failed_rerun_spec_for_entry(
    entry: FailedTestManifestEntry,
    *,
    project_name: str,
    project_root: Path,
    repo_root: Path,
    target_obj: object | None,
) -> TestExecutionSpec | str | None:
    return failed_rerun_spec_for_entry(
        entry,
        project_name=project_name,
        project_root=project_root,
        repo_root=repo_root,
        target_obj=target_obj,
        normalize_backend_command_fn=normalize_backend_python_test_command,
        detect_package_manager_fn=detect_package_manager,
    )


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


def route_backend_frontend_selection(route: Route, backend_flag: object, frontend_flag: object) -> tuple[bool, bool]:
    from envctl_engine.actions.action_command_support import service_types_from_route_services

    return is_backend_only_selection(backend_flag, frontend_flag, service_types_from_route_services(route))
