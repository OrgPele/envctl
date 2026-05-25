from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping, Sequence

from envctl_engine.actions.actions_test import TestCommandSpec, normalize_frontend_test_path
from envctl_engine.actions.action_test_command_support import normalize_backend_python_test_command
from envctl_engine.actions.action_test_manifest_support import FailedTestManifest, FailedTestManifestEntry
from envctl_engine.actions.action_test_manifest_support import resolve_unittest_test_identifier_for_project
from envctl_engine.actions.action_test_support_models import TestExecutionSpec, TestTargetContext
from envctl_engine.shared.node_tooling import detect_package_manager, detect_python_bin


def build_failed_test_execution_specs(
    *,
    target_contexts: Sequence[TestTargetContext],
    repo_root: Path,
    manifests_by_project: Mapping[str, FailedTestManifest],
    shared_raw_command: str | None,
    backend_raw_command: str | None,
    frontend_raw_command: str | None,
    failed_rerun_spec_for_entry_fn: Callable[..., TestExecutionSpec | str | None] | None = None,
) -> list[TestExecutionSpec]:
    del shared_raw_command, backend_raw_command, frontend_raw_command
    execution_specs: list[TestExecutionSpec] = []
    unsupported: list[str] = []
    spec_for_entry = failed_rerun_spec_for_entry_fn or failed_rerun_spec_for_entry
    for target in target_contexts:
        manifest = manifests_by_project.get(target.project_name)
        if manifest is None:
            continue
        for entry in manifest.entries:
            spec = spec_for_entry(
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
    return _renumber_execution_specs(execution_specs)


def failed_rerun_spec_for_entry(
    entry: FailedTestManifestEntry,
    *,
    project_name: str,
    project_root: Path,
    repo_root: Path,
    target_obj: object | None,
    detect_python_bin_fn: Callable[..., str | None] = detect_python_bin,
    detect_package_manager_fn: Callable[[Path], str | None] = detect_package_manager,
    normalize_backend_command_fn: Callable[[Sequence[str], Path], list[str]] = normalize_backend_python_test_command,
) -> TestExecutionSpec | str | None:
    source = entry.source
    if source in {"backend_pytest", "root_pytest"}:
        return _python_failed_rerun_spec(
            entry,
            project_name=project_name,
            project_root=project_root,
            repo_root=repo_root,
            target_obj=target_obj,
            detect_python_bin_fn=detect_python_bin_fn,
            normalize_backend_command_fn=normalize_backend_command_fn,
        )
    if source == "root_unittest":
        return _unittest_failed_rerun_spec(
            entry,
            project_name=project_name,
            project_root=project_root,
            repo_root=repo_root,
            target_obj=target_obj,
            detect_python_bin_fn=detect_python_bin_fn,
        )
    if source in {"frontend_package_test", "package_test"}:
        return _frontend_failed_rerun_spec(
            entry,
            project_name=project_name,
            project_root=project_root,
            target_obj=target_obj,
            detect_package_manager_fn=detect_package_manager_fn,
        )
    if source == "configured":
        return (
            f"Failed-only reruns are not supported for {project_name} "
            "because the previous test run used a custom configured command."
        )
    return f"Failed-only reruns are not supported for {project_name} ({source}). Run the full suite first."


def _python_failed_rerun_spec(
    entry: FailedTestManifestEntry,
    *,
    project_name: str,
    project_root: Path,
    repo_root: Path,
    target_obj: object | None,
    detect_python_bin_fn: Callable[..., str | None],
    normalize_backend_command_fn: Callable[[Sequence[str], Path], list[str]],
) -> TestExecutionSpec | str | None:
    if not entry.failed_tests:
        return None
    source = entry.source
    python_roots = (project_root / "backend", project_root, repo_root) if source == "backend_pytest" else (
        project_root,
        repo_root,
    )
    python_exe = detect_python_bin_fn(*python_roots)
    if not python_exe:
        suite_name = "backend pytest" if source == "backend_pytest" else "root pytest"
        return (
            f"Failed-only reruns are unavailable for {project_name} {suite_name} "
            "because no Python interpreter was found."
        )
    command = [python_exe, "-m", "pytest", *entry.failed_tests]
    if source == "backend_pytest":
        command = normalize_backend_command_fn(command, project_root)
    return _execution_spec(
        command=command,
        cwd=project_root,
        source=source,
        project_name=project_name,
        project_root=project_root,
        target_obj=target_obj,
    )


def _unittest_failed_rerun_spec(
    entry: FailedTestManifestEntry,
    *,
    project_name: str,
    project_root: Path,
    repo_root: Path,
    target_obj: object | None,
    detect_python_bin_fn: Callable[..., str | None],
) -> TestExecutionSpec | str | None:
    failed_tests = [
        normalized
        for value in entry.failed_tests
        if (normalized := resolve_unittest_test_identifier_for_project(value, project_root))
    ]
    if not failed_tests:
        return None
    python_exe = detect_python_bin_fn(project_root, repo_root)
    if not python_exe:
        return (
            f"Failed-only reruns are unavailable for {project_name} unittest "
            "because no Python interpreter was found."
        )
    return _execution_spec(
        command=[python_exe, "-m", "unittest", *failed_tests],
        cwd=project_root,
        source=entry.source,
        project_name=project_name,
        project_root=project_root,
        target_obj=target_obj,
    )


def _frontend_failed_rerun_spec(
    entry: FailedTestManifestEntry,
    *,
    project_name: str,
    project_root: Path,
    target_obj: object | None,
    detect_package_manager_fn: Callable[[Path], str | None],
) -> TestExecutionSpec | str | None:
    package_root = project_root / "frontend" if entry.source == "frontend_package_test" else project_root
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
    manager = detect_package_manager_fn(package_root)
    if not manager:
        return (
            f"Failed-only reruns are unavailable for {project_name} {entry.suite or entry.source} "
            "because no supported package manager was detected."
        )
    return _execution_spec(
        command=[manager, "run", "test", "--", *failed_files],
        cwd=package_root,
        source=entry.source,
        project_name=project_name,
        project_root=project_root,
        target_obj=target_obj,
    )


def _execution_spec(
    *,
    command: list[str],
    cwd: Path,
    source: str,
    project_name: str,
    project_root: Path,
    target_obj: object | None,
) -> TestExecutionSpec:
    return TestExecutionSpec(
        index=0,
        spec=TestCommandSpec(
            command=command,
            cwd=cwd,
            source=source,
        ),
        args=[],
        resolved_source=source,
        project_name=project_name,
        project_root=project_root,
        target_obj=target_obj,
    )


def _renumber_execution_specs(execution_specs: list[TestExecutionSpec]) -> list[TestExecutionSpec]:
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
