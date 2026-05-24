from __future__ import annotations


def live_failed_count(parsed: object | None) -> int:
    if parsed is None:
        return 0
    failed = int(getattr(parsed, "failed", 0) or 0)
    errors = int(getattr(parsed, "errors", 0) or 0)
    failed_tests = len(getattr(parsed, "failed_tests", ()) or ())
    return max(failed + errors, failed_tests + errors)


def format_live_progress_status(label: str, current: int, total: int) -> str:
    return f"Running {label}... {current}/{total} tests complete"


def format_live_progress_status_without_total(label: str, current: int, *, parsed: object | None) -> str:
    failed = min(max(live_failed_count(parsed), 0), max(current, 0))
    passed = max(0, int(current) - failed)
    return f"Running {label}... {current} tests complete • {passed} passed, {failed} failed"


def format_live_collection_status(label: str, discovered: int) -> str:
    return f"Collecting {label} tests... {discovered} discovered"


def format_live_progress_status_with_counts(label: str, current: int, total: int, *, parsed: object | None) -> str:
    failed = min(max(live_failed_count(parsed), 0), max(current, 0))
    passed = max(0, int(current) - failed)
    return f"{format_live_progress_status(label, current, total)} • {passed} passed, {failed} failed"
