from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Sequence

from envctl_engine.actions.action_target_support import action_target_names
from envctl_engine.actions.action_test_command_support import is_legacy_tree_test_script
from envctl_engine.actions.actions_test_classification import is_package_test_command, package_test_positionals


@dataclass(frozen=True, slots=True)
class TestStatusRenderer:
    __test__: ClassVar[bool] = False

    def command_start_status(self, command_name: str, targets: list[object]) -> str:
        target_names = action_target_names(targets)
        if not target_names:
            return f"Running {command_name}..."
        if len(target_names) == 1:
            return f"Running {command_name} for {target_names[0]}..."
        return f"Running {command_name} for {len(target_names)} targets..."

    def scope_status(self, project_names: list[str], *, run_all: bool, untested: bool, failed: bool) -> str:
        if run_all:
            return "Running tests for all discovered projects..."
        if failed:
            if len(project_names) == 1:
                return f"Rerunning failed tests for {project_names[0]}..."
            if project_names:
                return f"Rerunning failed tests for {len(project_names)} selected projects..."
            return "Rerunning failed tests..."
        if untested and not project_names:
            return "Running tests for untested projects..."
        if len(project_names) == 1:
            return f"Running tests for {project_names[0]}..."
        if project_names:
            return f"Running tests for {len(project_names)} selected projects..."
        return "Running tests..."

    def execution_status(self, command: Sequence[str], *, args: Sequence[str], source: str, cwd: Path) -> str:
        if is_legacy_tree_test_script(command):
            return _legacy_tree_execution_status(args)

        if source == "configured":
            snippet = " ".join(command[:3]).strip()
            if snippet:
                return f"Executing configured test command: {snippet}..."
            return "Executing configured test command..."

        if len(command) >= 3 and command[1] == "-m" and command[2] == "pytest":
            return _pytest_execution_status(command[3:])
        if len(command) >= 4 and command[1] == "-m" and command[2] == "unittest" and command[3] == "discover":
            return "Running unittest discovery (test_*.py)..."
        if len(command) >= 4 and command[1] == "-m" and command[2] == "unittest":
            return f"Rerunning failed unittest cases ({len(command) - 3})..."
        if is_package_test_command(command):
            return _package_test_execution_status(command, cwd=cwd)
        return "Executing detected test command..."


def command_start_status(command_name: str, targets: list[object]) -> str:
    return TestStatusRenderer().command_start_status(command_name, targets)


def render_test_scope_status(project_names: list[str], *, run_all: bool, untested: bool, failed: bool) -> str:
    return TestStatusRenderer().scope_status(project_names, run_all=run_all, untested=untested, failed=failed)


def render_test_execution_status(command: Sequence[str], *, args: Sequence[str], source: str, cwd: Path) -> str:
    return TestStatusRenderer().execution_status(command, args=args, source=source, cwd=cwd)


def _pytest_execution_status(arguments: Sequence[str]) -> str:
    positionals = _pytest_positionals(arguments)
    if positionals and all("::" in positional for positional in positionals):
        return f"Rerunning failed pytest cases ({len(positionals)})..."
    target = positionals[0] if positionals else "tests"
    return f"Running pytest suite at {target}..."


def _legacy_tree_execution_status(args: Sequence[str]) -> str:
    projects_arg = next((value for value in args if value.startswith("projects=")), "")
    if projects_arg:
        selected = projects_arg.split("=", 1)[1]
        count = len([name for name in selected.split(",") if name])
        return f"Running tree test matrix for {count} selected project(s)..."
    if "untested=true" in args:
        return "Running tree test matrix for untested projects..."
    return "Running tree test matrix for all projects..."


def _package_test_execution_status(command: Sequence[str], *, cwd: Path) -> str:
    manager = str(command[0])
    selected_targets = package_test_positionals(command)
    if selected_targets:
        return f"Running {manager} test script with {len(selected_targets)} selected target(s) in {cwd}..."
    return f"Running {manager} test script in {cwd}..."


def _pytest_positionals(arguments: Sequence[str]) -> list[str]:
    positionals: list[str] = []
    skip_next = False
    for argument in arguments:
        if skip_next:
            skip_next = False
            continue
        if argument == "--":
            continue
        if argument.startswith("--"):
            option_name, has_value = _long_option_name_and_value_state(argument)
            if not has_value and option_name in _PYTEST_OPTIONS_REQUIRING_VALUE:
                skip_next = True
            continue
        if argument.startswith("-"):
            if argument in _PYTEST_OPTIONS_REQUIRING_VALUE:
                skip_next = True
            continue
        positionals.append(argument)
    return positionals


def _long_option_name_and_value_state(argument: str) -> tuple[str, bool]:
    if "=" not in argument:
        return argument, False
    name, _value = argument.split("=", 1)
    return name, True


_PYTEST_OPTIONS_REQUIRING_VALUE = {
    "--basetemp",
    "--color",
    "--confcutdir",
    "--cov-report",
    "--durations",
    "--import-mode",
    "--junit-prefix",
    "--junit-xml",
    "--junitxml",
    "--log-cli-level",
    "--log-file",
    "--log-file-level",
    "--maxfail",
    "--rootdir",
    "--tb",
    "-k",
    "-m",
    "-o",
    "-p",
    "-W",
}


__all__ = [
    "TestStatusRenderer",
    "command_start_status",
    "render_test_execution_status",
    "render_test_scope_status",
]
