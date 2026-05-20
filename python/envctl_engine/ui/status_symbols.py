from __future__ import annotations

from dataclasses import dataclass

STATUS_SUCCESS = "✓"
STATUS_FAILURE = "✗"
STATUS_STARTING = "•"
STATUS_NEUTRAL = "○"
STATUS_SIMULATED = "~"
STATUS_WARNING = "⚠"


@dataclass(frozen=True, slots=True)
class StatusBadge:
    symbol: str
    severity: str
    label: str


def final_status_symbol(ok: bool) -> str:
    return STATUS_SUCCESS if ok else STATUS_FAILURE


def service_status_badge(status: str) -> StatusBadge:
    lowered = _normalize_status(status)
    if lowered in {"running", "healthy"}:
        return StatusBadge(STATUS_SUCCESS, "success", "Running" if lowered == "running" else "Healthy")
    if lowered == "simulated":
        return StatusBadge(STATUS_SIMULATED, "warning", "Simulated")
    if lowered in {"starting", "unknown"}:
        return StatusBadge(STATUS_STARTING, "warning", "Starting" if lowered == "starting" else "Unknown")
    if lowered == "stale":
        return StatusBadge(STATUS_FAILURE, "failure", "Stale")
    if lowered == "unreachable":
        return StatusBadge(STATUS_FAILURE, "failure", "Unreachable")
    if lowered in {"stopped", "configured", "not-running", "not running"}:
        return StatusBadge(STATUS_NEUTRAL, "neutral", "Not running")
    return StatusBadge(STATUS_FAILURE, "failure", status or "Error")


def dependency_status_badge(
    status: str,
    *,
    success: bool = False,
    simulated: bool = False,
    failure_count: int = 0,
) -> StatusBadge:
    lowered = _normalize_status(status)
    if lowered == "healthy":
        return StatusBadge(STATUS_SUCCESS, "success", "Healthy")
    if lowered == "running":
        return StatusBadge(STATUS_SUCCESS, "success", "Running")
    if lowered == "external" and success:
        return StatusBadge(STATUS_SUCCESS, "success", "External")
    if lowered == "simulated":
        return StatusBadge(STATUS_SIMULATED, "warning", "Simulated")
    if lowered in {"starting", "unknown"}:
        return StatusBadge(STATUS_STARTING, "warning", "Starting" if lowered == "starting" else "Unknown")
    if lowered == "unreachable":
        return StatusBadge(STATUS_FAILURE, "failure", "Unreachable")
    if lowered in {"unhealthy", "failed", "failure"}:
        return StatusBadge(STATUS_FAILURE, "failure", "Unhealthy" if lowered == "unhealthy" else "Failure")
    if not lowered:
        if success:
            if simulated:
                return StatusBadge(STATUS_SIMULATED, "warning", "Simulated")
            return StatusBadge(STATUS_SUCCESS, "success", "Healthy")
        if failure_count > 0:
            return StatusBadge(STATUS_FAILURE, "failure", "Unhealthy")
        return StatusBadge(STATUS_STARTING, "warning", "Starting")
    return StatusBadge(STATUS_FAILURE, "failure", status or "Unhealthy")


def health_status_badge(status: str) -> StatusBadge:
    lowered = _normalize_status(status)
    if lowered in {"running", "healthy"}:
        return StatusBadge(STATUS_SUCCESS, "success", "Running" if lowered == "running" else "Healthy")
    if lowered == "simulated":
        return StatusBadge(STATUS_SIMULATED, "warning", "Simulated")
    if lowered in {"starting", "unknown"}:
        return StatusBadge(STATUS_STARTING, "warning", "Starting" if lowered == "starting" else "Unknown")
    if lowered in {"stopped", "configured", "not-running", "not running"}:
        return StatusBadge(STATUS_NEUTRAL, "neutral", "Not running")
    return StatusBadge(STATUS_FAILURE, "failure", status or "Error")


def health_status_severity(status: str) -> str:
    severity = health_status_badge(status).severity
    if severity == "success":
        return "ok"
    if severity in {"warning", "neutral"}:
        return "warn"
    return "bad"


def health_status_icon(status: str) -> str:
    return health_status_badge(status).symbol


def _normalize_status(status: str) -> str:
    return str(status or "").strip().lower()
