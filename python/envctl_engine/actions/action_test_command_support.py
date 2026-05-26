from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class ConfiguredTestCommandCwdResolver:
    include_frontend: bool

    def __call__(self, project_root: Path) -> Path:
        return configured_test_command_cwd(project_root, include_frontend=self.include_frontend)


@dataclass(frozen=True, slots=True)
class ConfiguredTestSpecResolver:
    repo_root: Path
    frontend_test_path: str | None
    split_command: Callable[[str, Mapping[str, str]], list[str]]
    replacements_for_target: Callable[[object | None], Mapping[str, str]]
    normalize_backend_command: Callable[[Sequence[str], Path], list[str]]
    default_test_commands: Callable[..., list[TestCommandSpec]]

    def resolve(
        self,
        *,
        raw_command: str | None,
        target: TestTargetContext,
        include_backend: bool,
        include_frontend: bool,
        configured_test_command_cwd_fn: Callable[[Path], Path] | None = None,
    ) -> TestCommandSpec | None:
        if raw_command is not None:
            return self._configured_spec(
                raw_command=raw_command,
                target=target,
                include_backend=include_backend,
                include_frontend=include_frontend,
                configured_test_command_cwd_fn=configured_test_command_cwd_fn,
            )
        return self._default_spec(target=target, include_backend=include_backend, include_frontend=include_frontend)

    def _configured_spec(
        self,
        *,
        raw_command: str,
        target: TestTargetContext,
        include_backend: bool,
        include_frontend: bool,
        configured_test_command_cwd_fn: Callable[[Path], Path] | None,
    ) -> TestCommandSpec:
        command = self.split_command(raw_command, self.replacements_for_target(target.target_obj))
        source = "configured_frontend" if include_frontend else "configured_backend"
        if include_backend:
            if is_pytest_command(command):
                source = "backend_pytest"
            elif is_unittest_command(command):
                source = "root_unittest"
            command = self.normalize_backend_command(command, target.project_root)
        if include_frontend and is_package_test_command(command):
            command = append_frontend_test_path(
                command,
                self.frontend_test_path,
                project_root=target.project_root,
                command_cwd=configured_test_command_cwd(target.project_root, include_frontend=True),
            )
            source = "frontend_package_test"
        cwd_resolver = configured_test_command_cwd_fn or ConfiguredTestCommandCwdResolver(include_frontend)
        return TestCommandSpec(
            command=command,
            cwd=cwd_resolver(target.project_root),
            source=source,
        )

    def _default_spec(
        self,
        *,
        target: TestTargetContext,
        include_backend: bool,
        include_frontend: bool,
    ) -> TestCommandSpec | None:
        target_specs = self.default_test_commands(
            target.project_root,
            include_backend=include_backend,
            include_frontend=include_frontend,
            frontend_test_path=self.frontend_test_path,
        )
        if not target_specs and target.project_root != self.repo_root:
            target_specs = self.default_test_commands(
                self.repo_root,
                include_backend=include_backend,
                include_frontend=include_frontend,
                frontend_test_path=self.frontend_test_path,
            )
        if not target_specs:
            return None
        return target_specs[0]


@dataclass(frozen=True, slots=True)
class ActionTestCommandSources:
    shared_raw_command: str | None
    backend_raw_command: str | None
    frontend_raw_command: str | None


@dataclass(frozen=True, slots=True)
class ActionTestCommandTargetScope:
    target_contexts: Sequence[TestTargetContext]
    repo_root: Path


@dataclass(frozen=True, slots=True)
class ActionTestCommandPlanningScope:
    include_backend: bool
    include_frontend: bool
    frontend_test_path: str | None
    run_all: bool
    untested: bool


@dataclass(frozen=True, slots=True)
class ActionTestCommandDependencies:
    split_command: Callable[[str, Mapping[str, str]], list[str]]
    replacements_for_target: Callable[[object | None], Mapping[str, str]]
    is_legacy_tree_test_script: Callable[[list[str]], bool]
    configured_or_default_spec: Callable[..., TestCommandSpec | None]


@dataclass(frozen=True, slots=True)
class SharedTestCommandPlanner:
    raw_command: str
    target_scope: ActionTestCommandTargetScope
    planning_scope: ActionTestCommandPlanningScope
    dependencies: ActionTestCommandDependencies

    def build(self) -> list[TestExecutionSpec]:
        execution_specs: list[TestExecutionSpec] = []
        parsed_command: list[str] | None = None
        for target in self.target_scope.target_contexts:
            command, cwd = self._command_for_target(target)
            if parsed_command is None:
                parsed_command = command
            if self.dependencies.is_legacy_tree_test_script(command):
                parsed_command = command
                break
            execution_specs.append(self._target_execution_spec(target=target, command=command, cwd=cwd))

        parsed_command = parsed_command or self._command_without_target()
        if not self.dependencies.is_legacy_tree_test_script(parsed_command):
            return execution_specs
        return [self._legacy_all_targets_spec(parsed_command)]

    def _command_for_target(self, target: TestTargetContext) -> tuple[list[str], Path]:
        command = self.dependencies.split_command(
            self.raw_command,
            self.dependencies.replacements_for_target(target.target_obj),
        )
        cwd = target.project_root
        if self._frontend_package_command(command):
            cwd = configured_test_command_cwd(target.project_root, include_frontend=True)
            command = self._append_frontend_path(command, project_root=target.project_root, command_cwd=cwd)
        return command, cwd

    def _command_without_target(self) -> list[str]:
        command = self.dependencies.split_command(
            self.raw_command,
            self.dependencies.replacements_for_target(None),
        )
        if self._frontend_package_command(command):
            command = self._append_frontend_path(
                command,
                project_root=self.target_scope.repo_root,
                command_cwd=self.target_scope.repo_root,
            )
        return command

    def _frontend_package_command(self, command: list[str]) -> bool:
        return (
            self.planning_scope.include_frontend
            and not self.planning_scope.include_backend
            and is_package_test_command(command)
        )

    def _append_frontend_path(self, command: list[str], *, project_root: Path, command_cwd: Path) -> list[str]:
        return append_frontend_test_path(
            command,
            self.planning_scope.frontend_test_path,
            project_root=project_root,
            command_cwd=command_cwd,
        )

    def _target_execution_spec(
        self,
        *,
        target: TestTargetContext,
        command: list[str],
        cwd: Path,
    ) -> TestExecutionSpec:
        source = classify_test_command_source(
            command,
            include_backend=self.planning_scope.include_backend,
            include_frontend=self.planning_scope.include_frontend,
        )
        return TestExecutionSpec(
            index=0,
            spec=TestCommandSpec(command=command, cwd=cwd, source=source),
            args=[],
            resolved_source=source,
            project_name=target.project_name,
            project_root=target.project_root,
            target_obj=target.target_obj,
        )

    def _legacy_all_targets_spec(self, command: list[str]) -> TestExecutionSpec:
        project_names = [target.project_name for target in self.target_scope.target_contexts]
        return TestExecutionSpec(
            index=0,
            spec=TestCommandSpec(command=command, cwd=self.target_scope.repo_root, source="configured"),
            args=build_test_args(
                project_names,
                run_all=self.planning_scope.run_all,
                untested=self.planning_scope.untested,
            ),
            resolved_source="configured",
            project_name="all-targets",
            project_root=self.target_scope.repo_root,
            target_obj=None,
        )


@dataclass(frozen=True, slots=True)
class ActionTestExecutionSpecBuilder:
    commands: ActionTestCommandSources
    target_scope: ActionTestCommandTargetScope
    planning_scope: ActionTestCommandPlanningScope
    dependencies: ActionTestCommandDependencies

    def build(self) -> list[TestExecutionSpec]:
        if self.commands.shared_raw_command is not None:
            return _renumber_execution_specs(self._shared_command_planner().build())
        return _renumber_execution_specs(self._per_target_command_specs())

    def _shared_command_planner(self) -> SharedTestCommandPlanner:
        assert self.commands.shared_raw_command is not None
        return SharedTestCommandPlanner(
            raw_command=self.commands.shared_raw_command,
            target_scope=self.target_scope,
            planning_scope=self.planning_scope,
            dependencies=self.dependencies,
        )

    def _per_target_command_specs(self) -> list[TestExecutionSpec]:
        execution_specs: list[TestExecutionSpec] = []
        for target in self.target_scope.target_contexts:
            for spec in self._specs_for_target(target):
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
        return execution_specs

    def _specs_for_target(self, target: TestTargetContext) -> list[TestCommandSpec]:
        target_specs: list[TestCommandSpec] = []
        if self.planning_scope.include_backend:
            backend_spec = self.dependencies.configured_or_default_spec(
                raw_command=self.commands.backend_raw_command,
                target=target,
                repo_root=self.target_scope.repo_root,
                include_backend=True,
                include_frontend=False,
                frontend_test_path=None,
                split_command=self.dependencies.split_command,
                replacements_for_target=self.dependencies.replacements_for_target,
            )
            if backend_spec is not None:
                target_specs.append(backend_spec)
        if self.planning_scope.include_frontend:
            frontend_spec = self.dependencies.configured_or_default_spec(
                raw_command=self.commands.frontend_raw_command,
                target=target,
                repo_root=self.target_scope.repo_root,
                include_backend=False,
                include_frontend=True,
                frontend_test_path=self.planning_scope.frontend_test_path,
                split_command=self.dependencies.split_command,
                replacements_for_target=self.dependencies.replacements_for_target,
            )
            if frontend_spec is not None:
                target_specs.append(frontend_spec)
        return target_specs


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
    configured_or_default = configured_or_default_spec_fn or configured_or_default_test_spec
    return ActionTestExecutionSpecBuilder(
        commands=ActionTestCommandSources(
            shared_raw_command=shared_raw_command,
            backend_raw_command=backend_raw_command,
            frontend_raw_command=frontend_raw_command,
        ),
        target_scope=ActionTestCommandTargetScope(target_contexts=target_contexts, repo_root=repo_root),
        planning_scope=ActionTestCommandPlanningScope(
            include_backend=include_backend,
            include_frontend=include_frontend,
            frontend_test_path=frontend_test_path,
            run_all=run_all,
            untested=untested,
        ),
        dependencies=ActionTestCommandDependencies(
            split_command=split_command,
            replacements_for_target=replacements_for_target,
            is_legacy_tree_test_script=is_legacy_tree_test_script,
            configured_or_default_spec=configured_or_default,
        ),
    ).build()


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
    normalize_backend_command = normalize_backend_command_fn or normalize_backend_python_test_command
    return ConfiguredTestSpecResolver(
        repo_root=repo_root,
        frontend_test_path=frontend_test_path,
        split_command=split_command,
        replacements_for_target=replacements_for_target,
        normalize_backend_command=normalize_backend_command,
        default_test_commands=default_test_commands_fn,
    ).resolve(
        raw_command=raw_command,
        target=target,
        include_backend=include_backend,
        include_frontend=include_frontend,
        configured_test_command_cwd_fn=configured_test_command_cwd_fn,
    )


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
