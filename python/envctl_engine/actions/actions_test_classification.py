from __future__ import annotations

from typing import Sequence


def is_package_test_command(command: Sequence[str]) -> bool:
    rendered = [str(part).strip() for part in command if str(part).strip()]
    if not rendered:
        return False
    first = rendered[0]
    if first in {"npm", "pnpm", "bun"}:
        return len(rendered) >= 3 and rendered[1] == "run" and rendered[2] == "test"
    if first == "yarn":
        return (len(rendered) >= 2 and rendered[1] == "test") or (
            len(rendered) >= 3 and rendered[1] == "run" and rendered[2] == "test"
        )
    return False


def is_pytest_command(command: Sequence[str]) -> bool:
    rendered = [str(part).strip() for part in command if str(part).strip()]
    if len(rendered) < 3:
        return False
    return rendered[1] == "-m" and rendered[2] == "pytest"


def is_unittest_command(command: Sequence[str]) -> bool:
    rendered = [str(part).strip() for part in command if str(part).strip()]
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
