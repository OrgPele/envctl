from __future__ import annotations

import math
import os
from collections.abc import Mapping
from pathlib import Path

from envctl_engine.shared.parsing import parse_bool, parse_int

_DEFAULT_MAX_PYTEST_WORKERS = 8


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
    insert_index = pytest_parallel_insert_index(args)
    if (
        not policy.enabled()
        or insert_index is None
        or pytest_parallel_already_configured(args)
        or pytest_plugin_autoload_disabled(args, env=policy.env)
    ):
        return args
    workers = policy.workers()
    if workers <= 1 or not pytest_xdist_available(args, cwd=cwd):
        return args
    return [*args[:insert_index], "-n", str(workers), *args[insert_index:]]


def pytest_parallel_insert_index(args: list[str]) -> int | None:
    if len(args) >= 3 and args[1:3] == ["-m", "pytest"]:
        return 3
    if len(args) >= 3 and Path(args[0]).name == "uv" and args[1] == "run":
        for index, token in enumerate(args[2:], start=2):
            if token == "pytest":
                return index + 1
    return None


def pytest_parallel_already_configured(args: list[str]) -> bool:
    for index, token in enumerate(args):
        if token in {"-n", "--numprocesses"}:
            return True
        if token.startswith("--numprocesses="):
            return True
        if token == "-p" and index + 1 < len(args) and args[index + 1] == "no:xdist":
            return True
        if token in {"-pno:xdist", "-p=no:xdist"}:
            return True
    return False


def pytest_plugin_autoload_disabled(args: list[str], *, env: dict[str, str]) -> bool:
    if env.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "").strip().lower() not in {"", "0", "false", "no"}:
        return True
    return "--disable-plugin-autoload" in args


def pytest_xdist_available(args: list[str], *, cwd: Path) -> bool:
    if not args:
        return False
    venv = pytest_command_venv(args, cwd=cwd)
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


def pytest_command_venv(args: list[str], *, cwd: Path) -> Path | None:
    if len(args) >= 3 and args[1:3] == ["-m", "pytest"]:
        python = Path(args[0])
        if not python.is_absolute():
            python = cwd / python
        return python.parent.parent if python.parent.name == "bin" else None
    if len(args) >= 3 and Path(args[0]).name == "uv" and args[1] == "run":
        return cwd / ".venv"
    return None


def free_cpu_worker_count(*, cpu_count: int) -> int:
    try:
        load_1m = max(float(os.getloadavg()[0]), 0.0)
    except (AttributeError, OSError):
        load_1m = 0.0
    free_cores = cpu_count - math.ceil(load_1m)
    return max(1, min(cpu_count, free_cores, _DEFAULT_MAX_PYTEST_WORKERS))


def first_configured_value(*values: object) -> object | None:
    for value in values:
        if value is None:
            continue
        if str(value).strip() != "":
            return value
    return None
