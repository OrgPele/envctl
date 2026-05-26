from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class RetryResult:
    success: bool
    port: int
    attempts: int
    failure: str | None = None


@dataclass(slots=True)
class ContainerStartResult:
    success: bool
    container_name: str
    error: str | None = None
    reason_code: str | None = None
    failure_class: str | None = None
    stage_events: list[dict[str, object]] | None = None
    stage_durations_ms: dict[str, float] | None = None
    command_timings: list[dict[str, object]] | None = None
    probe_attempts: list[dict[str, object]] | None = None
    docker_command_count: int = 0
    probe_attempt_count: int = 0
    listener_wait_ms: float = 0.0
    container_reused: bool = False
    container_recreated: bool = False
    effective_port: int | None = None
    port_adopted: bool = False
    port_mismatch_requested_port: int | None = None
    port_mismatch_existing_port: int | None = None
    port_mismatch_action: str | None = None


def is_bind_conflict(error: str | None) -> bool:
    if not error:
        return False
    lower = error.lower()
    return (
        "address already in use" in lower
        or "bind" in lower
        or "port is already allocated" in lower
        or "published host port missing" in lower
        or "host port binding incomplete" in lower
    )


def run_with_retry(
    *,
    initial_port: int,
    start: Callable[[int], tuple[bool, str | None]],
    reserve_next: Callable[[int], int],
    max_retries: int = 3,
) -> RetryResult:
    port = initial_port
    attempts = 0
    while attempts < max_retries:
        attempts += 1
        success, error = start(port)
        if success:
            return RetryResult(success=True, port=port, attempts=attempts)
        if not is_bind_conflict(error):
            return RetryResult(success=False, port=port, attempts=attempts, failure=error or "unknown")
        port = reserve_next(port + 1)
    return RetryResult(success=False, port=port, attempts=attempts, failure="retry_limit")


def build_container_name(*, prefix: str, project_root: Path, project_name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", project_name).strip("-").lower() or "project"
    digest = hashlib.sha1(str(project_root).encode("utf-8")).hexdigest()[:8]
    separator = "-"
    suffix = f"{separator}{digest}"
    base_prefix = f"{prefix}{separator}"
    max_len = 63
    available = max_len - len(base_prefix) - len(suffix)
    if available <= 0:
        return f"{prefix[: max_len - len(suffix)].rstrip(separator)}{suffix}".rstrip(separator)
    trimmed = normalized[:available].rstrip(separator) or "project"
    return f"{base_prefix}{trimmed}{suffix}"[:max_len].rstrip(separator)
