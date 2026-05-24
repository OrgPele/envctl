from __future__ import annotations

from pathlib import Path
import shutil
from typing import Callable, Mapping, Sequence

from envctl_engine.actions.actions_test import (
    TestCommandSpec,
    append_frontend_test_path,
    build_test_args,
    classify_test_command_source,
    default_test_commands,
    is_package_test_command,
    is_pytest_command,
    is_unittest_command,
)
from envctl_engine.actions.action_target_support import action_target_identities
from envctl_engine.actions.action_test_support_models import TestExecutionSpec, TestTargetContext
from envctl_engine.shared.node_tooling import detect_python_bin


def build_test_target_contexts(targets: Sequence[object], *, repo_root: Path) -> list[TestTargetContext]:
    contexts = [
        TestTargetContext(
            project_name=identity.name,
            project_root=identity.root,
            target_obj=identity.target_obj,
        )
        for identity in action_target_identities(targets, fallback_name_from_root=True)
    ]
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
    configured_or_default_spec_fn: Callable[..., TestCommandSpec | None] | None = None,
) -> list[TestExecutionSpec]:
    source = "detected"
    execution_specs: list[TestExecutionSpec] = []
    configured_or_default = configured_or_default_spec_fn or configured_or_default_test_spec
    if shared_raw_command is not None:
        source = "configured"
        parsed_command: list[str] | None = None
        for target in target_contexts:
            command = split_command(shared_raw_command, replacements_for_target(target.target_obj))
            cwd = target.project_root
            if include_frontend and not include_backend and is_package_test_command(command):
                cwd = configured_test_command_cwd(target.project_root, include_frontend=True)
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
                backend_spec = configured_or_default(
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
                frontend_spec = configured_or_default(
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
    return _renumber_execution_specs(execution_specs)


def configured_or_default_test_spec(
    *,
    raw_command: str | None,
    target: TestTargetContext,
    repo_root: Path,
    include_backend: bool,
    include_frontend: bool,
    frontend_test_path: str | None,
    split_command: Callable[[str, Mapping[str, str]], list[str]],
    replacements_for_target: Callable[[object | None], Mapping[str, str]],
    normalize_backend_command_fn: Callable[[Sequence[str], Path], list[str]] | None = None,
    configured_test_command_cwd_fn: Callable[[Path], Path] | None = None,
    default_test_commands_fn: Callable[..., list[TestCommandSpec]] = default_test_commands,
) -> TestCommandSpec | None:
    if raw_command is not None:
        command = split_command(raw_command, replacements_for_target(target.target_obj))
        source = "configured_frontend" if include_frontend else "configured_backend"
        if include_backend:
            if is_pytest_command(command):
                source = "backend_pytest"
            elif is_unittest_command(command):
                source = "root_unittest"
            normalize_backend_command = normalize_backend_command_fn or normalize_backend_python_test_command
            command = normalize_backend_command(command, target.project_root)
        if include_frontend and is_package_test_command(command):
            command = append_frontend_test_path(
                command,
                frontend_test_path,
                project_root=target.project_root,
                command_cwd=configured_test_command_cwd(target.project_root, include_frontend=True),
            )
            source = "frontend_package_test"
        cwd_resolver = configured_test_command_cwd_fn or (
            lambda project_root: configured_test_command_cwd(project_root, include_frontend=include_frontend)
        )
        return TestCommandSpec(
            command=command,
            cwd=cwd_resolver(target.project_root),
            source=source,
        )
    target_specs = default_test_commands_fn(
        target.project_root,
        include_backend=include_backend,
        include_frontend=include_frontend,
        frontend_test_path=frontend_test_path,
    )
    if not target_specs and target.project_root != repo_root:
        target_specs = default_test_commands_fn(
            repo_root,
            include_backend=include_backend,
            include_frontend=include_frontend,
            frontend_test_path=frontend_test_path,
        )
    if not target_specs:
        return None
    return target_specs[0]


def configured_test_command_cwd(project_root: Path, *, include_frontend: bool) -> Path:
    if include_frontend and (project_root / "frontend" / "package.json").is_file():
        return project_root / "frontend"
    return project_root


def normalize_backend_python_test_command(
    command: Sequence[str],
    project_root: Path,
    *,
    pyproject_uses_poetry_fn: Callable[[Path], bool] | None = None,
    which_fn: Callable[[str], str | None] = shutil.which,
    detect_python_bin_fn: Callable[..., str | None] = detect_python_bin,
) -> list[str]:
    rendered = [str(part) for part in command]
    if not rendered or rendered[0] not in {"python", "python3", "python3.12"}:
        return rendered

    backend_root = project_root / "backend"
    pyproject = backend_root / "pyproject.toml"
    uses_poetry = pyproject_uses_poetry_fn or pyproject_uses_poetry
    if pyproject.is_file() and uses_poetry(pyproject) and which_fn("poetry"):
        return ["poetry", "--project", str(backend_root), "run", "python", *rendered[1:]]

    python_exe = detect_python_bin_fn(backend_root, project_root)
    if python_exe and "/" in python_exe:
        return [python_exe, *rendered[1:]]
    return rendered


def pyproject_uses_poetry(pyproject: Path) -> bool:
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return "[tool.poetry]" in text or "[tool.pdm]" in text


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
