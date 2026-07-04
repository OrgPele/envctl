from __future__ import annotations

import math
import os
from collections.abc import Mapping
from pathlib import Path

from envctl_engine.shared.parsing import parse_bool, parse_int


class PytestParallelPolicy:
    def __init__(
        self,
        *,
        env: Mapping[str, object],
        config_raw: Mapping[str, object],
        route_flags: Mapping[str, object],
        include_focused_env: bool = False,
    ) -> None:
        self.env = env
        self.config_raw = config_raw
        self.route_flags = route_flags
        self.include_focused_env = include_focused_env

    def enabled(self) -> bool:
        forced = self.route_flags.get("test_parallel")
        if isinstance(forced, bool):
            return forced
        focused_values = (
            (
                self.env.get("ENVCTL_TEST_FOCUSED_PYTEST_PARALLEL"),
                self.config_raw.get("ENVCTL_TEST_FOCUSED_PYTEST_PARALLEL"),
            )
            if self.include_focused_env
            else ()
        )
        configured = first_configured_value(
            *focused_values,
            self.env.get("ENVCTL_ACTION_TEST_PYTEST_PARALLEL"),
            self.config_raw.get("ENVCTL_ACTION_TEST_PYTEST_PARALLEL"),
        )
        return parse_bool(configured, True)

    def workers(self) -> int:
        focused_values = (
            (
                self.env.get("ENVCTL_TEST_FOCUSED_PYTEST_WORKERS"),
                self.config_raw.get("ENVCTL_TEST_FOCUSED_PYTEST_WORKERS"),
            )
            if self.include_focused_env
            else ()
        )
        configured = first_configured_value(
            self.route_flags.get("test_parallel_max"),
            *focused_values,
            self.env.get("ENVCTL_ACTION_TEST_PYTEST_WORKERS"),
            self.config_raw.get("ENVCTL_ACTION_TEST_PYTEST_WORKERS"),
        )
        explicit = parse_int(configured, 0)
        cpu_count = max(os.cpu_count() or 1, 1)
        if explicit > 0:
            return max(1, min(explicit, cpu_count))
        return free_cpu_worker_count(cpu_count=cpu_count)


def parallelized_pytest_args(args: list[str], *, cwd: Path, policy: PytestParallelPolicy) -> list[str]:
    if not policy.enabled() or not is_python_pytest_command(args) or pytest_parallel_already_configured(args):
        return args
    workers = policy.workers()
    if workers <= 1 or not pytest_xdist_available(args, cwd=cwd):
        return args
    return [*args[:3], "-n", str(workers), *args[3:]]


def is_python_pytest_command(args: list[str]) -> bool:
    return len(args) >= 3 and args[1:3] == ["-m", "pytest"]


def pytest_parallel_already_configured(args: list[str]) -> bool:
    for index, token in enumerate(args):
        if token in {"-n", "--numprocesses"}:
            return True
        if token.startswith("--numprocesses="):
            return True
        if token == "-p" and index + 1 < len(args) and args[index + 1] == "no:xdist":
            return True
    return False


def pytest_xdist_available(args: list[str], *, cwd: Path) -> bool:
    _ = cwd
    if not args:
        return False
    python = Path(args[0])
    try:
        python = python.resolve()
    except OSError:
        return False
    venv = python.parent.parent if python.parent.name == "bin" else None
    if venv is None or not venv.is_dir():
        return False
    for lib_dir_name in ("lib", "lib64"):
        lib_dir = venv / lib_dir_name
        if not lib_dir.is_dir():
            continue
        for site_packages in lib_dir.glob("python*/site-packages"):
            if (site_packages / "xdist").is_dir():
                return True
    return False


def free_cpu_worker_count(*, cpu_count: int) -> int:
    try:
        load_1m = max(float(os.getloadavg()[0]), 0.0)
    except (AttributeError, OSError):
        load_1m = 0.0
    free_cores = cpu_count - math.ceil(load_1m)
    return max(1, min(cpu_count, free_cores))


def first_configured_value(*values: object) -> object | None:
    for value in values:
        if value is None:
            continue
        if str(value).strip() != "":
            return value
    return None
