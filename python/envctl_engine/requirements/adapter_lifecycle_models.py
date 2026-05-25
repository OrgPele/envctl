from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from envctl_engine.shared.protocols import ProcessRuntime

from .common_contracts import ContainerStartResult


@dataclass(slots=True)
class AdapterLifecycleEvent:
    stage: str
    reason: str | None = None
    detail: str | None = None
    elapsed_ms: float = 0.0

    def to_payload(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "reason": self.reason,
            "detail": self.detail,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(slots=True)
class ContainerLifecycleTemplate:
    service_name: str
    container_name: str
    process_runner: ProcessRuntime
    project_root: Path
    env: Mapping[str, str] | None
    port: int
    container_port: int
    listener_wait_timeout: float
    probe_attempts: int
    restart_probe_attempts: int
    recreate_probe_attempts: int
    restart_on_probe_failure: bool
    recreate_on_probe_failure: bool
    retryable_probe_error: Callable[[str | None], bool]
    create_container: Callable[[], str | None]
    probe_readiness: Callable[[int], tuple[bool, str | None]]
    probe_failure_fallback: str
    restart_on_listener_timeout: bool = False
    recreate_on_restart_listener_timeout: bool = False
    bind_cleanup: Callable[[int], tuple[bool, str | None]] | None = None
    trace_stage: Callable[[dict[str, object]], None] | None = None


@dataclass(slots=True)
class ContainerLifecycleRun:
    result: ContainerStartResult
    events: list[AdapterLifecycleEvent]
    stage_durations_ms: dict[str, float]
    listener_wait_ms: float
    container_reused: bool
    container_recreated: bool

    def to_result(self) -> ContainerStartResult:
        self.result.stage_events = [event.to_payload() for event in self.events]
        self.result.stage_durations_ms = dict(self.stage_durations_ms)
        self.result.listener_wait_ms = float(self.listener_wait_ms)
        self.result.container_reused = bool(self.container_reused)
        self.result.container_recreated = bool(self.container_recreated)
        return self.result


def project_container_lifecycle_result(lifecycle_run: ContainerLifecycleRun) -> ContainerStartResult:
    return lifecycle_run.to_result()


__all__ = tuple(name for name in globals() if not name.startswith("_"))
