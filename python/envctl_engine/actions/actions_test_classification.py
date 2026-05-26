from __future__ import annotations

from typing import Sequence


def is_package_test_command(command: Sequence[str]) -> bool:
    rendered = _rendered_command(command)
    if not rendered:
        return False
    return rendered[0] in _PACKAGE_TEST_MANAGERS and (
        _is_direct_package_test(rendered) or _is_run_package_test(rendered)
    )


def package_test_positionals(command: Sequence[str]) -> list[str]:
    rendered = _rendered_command(command)
    try:
        separator_index = rendered.index("--")
    except ValueError:
        return []

    positionals: list[str] = []
    skip_next = False
    for argument in rendered[separator_index + 1 :]:
        if skip_next:
            skip_next = False
            continue
        if argument.startswith("--"):
            option_name, has_inline_value = _long_option_name_and_value_state(argument)
            if not has_inline_value and option_name in _PACKAGE_TEST_OPTIONS_REQUIRING_VALUE:
                skip_next = True
            continue
        if argument.startswith("-"):
            if argument in _PACKAGE_TEST_OPTIONS_REQUIRING_VALUE:
                skip_next = True
            continue
        positionals.append(argument)
    return positionals


def is_pytest_command(command: Sequence[str]) -> bool:
    rendered = _rendered_command(command)
    if len(rendered) < 3:
        return False
    return rendered[1] == "-m" and rendered[2] == "pytest"


def is_unittest_command(command: Sequence[str]) -> bool:
    rendered = _rendered_command(command)
    if len(rendered) < 3:
        return False
    return rendered[1] == "-m" and rendered[2] == "unittest"


def classify_test_command_source(
    command: Sequence[str],
    *,
    include_backend: bool,
    include_frontend: bool,
) -> str:
    if include_backend and is_pytest_command(command):
        return "backend_pytest"
    if include_backend and is_unittest_command(command):
        return "root_unittest"
    if include_frontend and is_package_test_command(command):
        return "frontend_package_test" if not include_backend else "package_test"
    return "configured"


def build_test_args(project_names: Sequence[str], *, run_all: bool, untested: bool) -> list[str]:
    args: list[str] = []
    if not run_all and project_names:
        projects_arg = ",".join(project_names)
        args.append(f"projects={projects_arg}")
    if untested:
        args.append("untested=true")
    return args


def _rendered_command(command: Sequence[str]) -> list[str]:
    return [str(part).strip() for part in command if str(part).strip()]


def _is_direct_package_test(rendered: Sequence[str]) -> bool:
    return len(rendered) >= 2 and rendered[1] == "test"


def _is_run_package_test(rendered: Sequence[str]) -> bool:
    return len(rendered) >= 3 and rendered[1] == "run" and rendered[2] == "test"


def _long_option_name_and_value_state(argument: str) -> tuple[str, bool]:
    if "=" not in argument:
        return argument, False
    option_name, _value = argument.split("=", 1)
    return option_name, True


_PACKAGE_TEST_MANAGERS = {"bun", "npm", "pnpm", "yarn"}

_PACKAGE_TEST_OPTIONS_REQUIRING_VALUE = {
    "--config",
    "--coverageDirectory",
    "--env",
    "--grep",
    "--include",
    "--name",
    "--project",
    "--reporter",
    "--testNamePattern",
    "--testPathPattern",
    "--testRegex",
    "--testTimeout",
    "-c",
    "-g",
    "-t",
}
