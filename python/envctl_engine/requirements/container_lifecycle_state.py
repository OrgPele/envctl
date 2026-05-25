from __future__ import annotations

import time
from dataclasses import dataclass, field

from .adapter_lifecycle_models import AdapterLifecycleEvent, ContainerLifecycleRun, ContainerLifecycleTemplate
from .common_contracts import ContainerStartResult
from ..shared.reason_codes import reason_code_to_string
from ..shared.reason_codes import RequirementLifecycleReason
from .adapter_policy import port_mismatch_policy


@dataclass(slots=True)
class ContainerLifecycleState:
    events: list[AdapterLifecycleEvent] = field(default_factory=list)
    stage_durations_ms: dict[str, float] = field(default_factory=dict)
    listener_wait_ms: float = 0.0
    container_reused: bool = False
    container_recreated: bool = False
    effective_port: int = 0
    port_adopted: bool = False
    mismatch_requested_port: int | None = None
    mismatch_existing_port: int | None = None
    mismatch_action: str | None = None
    mismatch_policy: str = "recreate"
    timeout_recovered_create: bool = False
    started_at: float = 0.0


class ContainerLifecycleRecorder:
    def __init__(self, template: ContainerLifecycleTemplate) -> None:
        self.template = template
        self.state = self.new_state()

    def new_state(self) -> ContainerLifecycleState:
        return ContainerLifecycleState(
            effective_port=int(self.template.port),
            mismatch_policy=port_mismatch_policy(self.template.env),
            started_at=time.monotonic(),
        )

    def reset(self) -> ContainerLifecycleState:
        self.state = self.new_state()
        return self.state

    def emit(self, stage: str, reason: str | None = None, detail: str | None = None) -> None:
        elapsed_ms = round((time.monotonic() - self.state.started_at) * 1000.0, 2)
        payload = AdapterLifecycleEvent(stage=stage, reason=reason, detail=detail, elapsed_ms=elapsed_ms)
        self.state.events.append(payload)
        if callable(self.template.trace_stage):
            self.template.trace_stage(payload.to_payload())

    def add_stage_duration(self, name: str, stage_started_at: float) -> float:
        duration_ms = round((time.monotonic() - stage_started_at) * 1000.0, 2)
        durations = self.state.stage_durations_ms
        durations[name] = round(durations.get(name, 0.0) + duration_ms, 2)
        return duration_ms

    def run_result(self, *, result: ContainerStartResult) -> ContainerLifecycleRun:
        state = self.state
        if result.effective_port is None:
            result.effective_port = int(state.effective_port)
        result.port_adopted = bool(result.port_adopted or state.port_adopted)
        if result.port_mismatch_requested_port is None:
            result.port_mismatch_requested_port = state.mismatch_requested_port
        if result.port_mismatch_existing_port is None:
            result.port_mismatch_existing_port = state.mismatch_existing_port
        if result.port_mismatch_action is None:
            result.port_mismatch_action = state.mismatch_action
        return ContainerLifecycleRun(
            result=result,
            events=state.events,
            stage_durations_ms=state.stage_durations_ms,
            listener_wait_ms=round(state.listener_wait_ms, 2),
            container_reused=state.container_reused,
            container_recreated=state.container_recreated,
        )

    def success(self) -> ContainerLifecycleRun:
        state = self.state
        return self.run_result(
            result=ContainerStartResult(
                success=True,
                container_name=self.template.container_name,
                effective_port=int(state.effective_port),
                port_adopted=bool(state.port_adopted),
                port_mismatch_requested_port=state.mismatch_requested_port,
                port_mismatch_existing_port=state.mismatch_existing_port,
                port_mismatch_action=state.mismatch_action,
            )
        )

    def reset_to_requested_port(self) -> None:
        self.state.effective_port = int(self.template.port)
        self.state.port_adopted = False

    def failure(
        self,
        error: str,
        *,
        reason_code: str,
        failure_class: str = "hard_start_failure",
        stage: str,
    ) -> ContainerLifecycleRun:
        state = self.state
        self.emit(stage, reason=reason_code, detail=error)
        return self.run_result(
            result=ContainerStartResult(
                success=False,
                container_name=self.template.container_name,
                error=error,
                reason_code=reason_code,
                failure_class=failure_class,
                effective_port=int(state.effective_port),
                port_adopted=bool(state.port_adopted),
                port_mismatch_requested_port=state.mismatch_requested_port,
                port_mismatch_existing_port=state.mismatch_existing_port,
                port_mismatch_action=state.mismatch_action,
            )
        )


__all__ = (
    "ContainerLifecycleRecorder",
    "ContainerLifecycleState",
    "RequirementLifecycleReason",
    "reason_code_to_string",
)
