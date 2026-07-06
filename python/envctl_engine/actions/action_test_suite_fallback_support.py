from __future__ import annotations

from collections.abc import Callable
from typing import Any

_FALLBACK_STATUS = "Parallel test execution failed; retrying the same suites sequentially..."


def run_test_suites_with_parallel_fallback(
    *,
    parallel: bool,
    parallel_workers: int,
    suite_count: int,
    outcomes: Any,
    emit_status: Callable[[str], None],
    emit_event: Callable[..., None],
    run_loop: Callable[..., list[str]],
) -> list[str]:
    fallback_enabled = parallel and parallel_workers > 1
    attempt_outcome_start = len(outcomes.outcomes)
    fallback_reason = ""
    try:
        failures = run_loop(parallel=parallel, parallel_workers=parallel_workers)
    except Exception as exc:  # noqa: BLE001 - parallel infrastructure failures retry sequentially.
        if not fallback_enabled:
            raise
        failures = [f"parallel execution error: {exc}"]
        fallback_reason = type(exc).__name__
    if not (fallback_enabled and failures):
        return failures

    del outcomes.outcomes[attempt_outcome_start:]
    emit_status(_FALLBACK_STATUS)
    emit_event(
        "test.parallel.fallback",
        failures=len(failures),
        suites=suite_count,
        reason=fallback_reason or "test_failure",
    )
    return run_loop(parallel=False, parallel_workers=1, stop_on_sequential_failure=False)
