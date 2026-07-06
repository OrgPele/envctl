from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class TestCommandAttempt:
    command: list[str]
    completed: Any


def run_tests_with_parallel_137_retry(
    *,
    runner: Any,
    command: list[str],
    fallback_command: list[str],
    run_kwargs: dict[str, object],
    emit_status: Callable[[str], None],
) -> TestCommandAttempt:
    completed = runner.run_tests(command, **run_kwargs)
    if int(getattr(completed, "returncode", 0) or 0) != 137 or command == fallback_command:
        return TestCommandAttempt(command=command, completed=completed)
    emit_status("Parallel pytest command exited 137; retrying without pytest-xdist...")
    return TestCommandAttempt(command=fallback_command, completed=runner.run_tests(fallback_command, **run_kwargs))
