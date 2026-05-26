from __future__ import annotations

from collections.abc import Mapping
import inspect
from typing import Callable

SUCCESSFUL_CHECK_PHASE_STATUSES = {"checks_passed"}


def callable_accepts_keyword(callback: Callable[..., object], keyword: str) -> bool:
    try:
        parameters = inspect.signature(callback).parameters
    except (TypeError, ValueError):
        return False
    return keyword in parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()
    )


def ship_status_is_success(status: str) -> bool:
    return status in SUCCESSFUL_CHECK_PHASE_STATUSES


def check_phase_status(checks: Mapping[str, object]) -> str:
    return str(checks.get("state") or "checks_unresolved")


__all__ = ["callable_accepts_keyword", "check_phase_status", "ship_status_is_success"]
