from __future__ import annotations

import time
from dataclasses import dataclass, field

from .adapter_lifecycle_models import AdapterLifecycleEvent, ContainerLifecycleRun, ContainerLifecycleTemplate
from ..shared.reason_codes import (
    PortFailureReason,
    RequirementFailureReason,
    RequirementLifecycleReason,
    reason_code_to_string,
)
from .adapter_policy import port_mismatch_policy, sleep_between_probes, timeout_error
from .adapter_port_cleanup import format_bind_conflict_guidance, wait_for_port_ready
from .common import (
    ContainerStartResult,
    container_exists,
    container_host_port,
    container_state_error,
    container_status,
    docker_port_publish_lock,
    is_bind_conflict,
    is_missing_port_mapping_error,
    run_docker,
    run_result_error,
    stop_and_remove_container,
)


@dataclass(slots=True)
class _ContainerLifecycleState:
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


class ContainerLifecycleExecutor:
    def __init__(self, template: ContainerLifecycleTemplate) -> None:
        self.template = template
        self._state = self._new_state()

    def _new_state(self) -> _ContainerLifecycleState:
        return _ContainerLifecycleState(
            effective_port=int(self.template.port),
            mismatch_policy=port_mismatch_policy(self.template.env),
            started_at=time.monotonic(),
        )

    def _emit(self, stage: str, reason: str | None = None, detail: str | None = None) -> None:
        elapsed_ms = round((time.monotonic() - self._state.started_at) * 1000.0, 2)
        payload = AdapterLifecycleEvent(stage=stage, reason=reason, detail=detail, elapsed_ms=elapsed_ms)
        self._state.events.append(payload)
        if callable(self.template.trace_stage):
            self.template.trace_stage(payload.to_payload())

    def _add_stage_duration(self, name: str, stage_started_at: float) -> float:
        duration_ms = round((time.monotonic() - stage_started_at) * 1000.0, 2)
        durations = self._state.stage_durations_ms
        durations[name] = round(durations.get(name, 0.0) + duration_ms, 2)
        return duration_ms

    def _run_result(self, *, result: ContainerStartResult) -> ContainerLifecycleRun:
        state = self._state
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

    def _success(self) -> ContainerLifecycleRun:
        state = self._state
        return self._run_result(
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

    def _reset_to_requested_port(self) -> None:
        self._state.effective_port = int(self.template.port)
        self._state.port_adopted = False

    def _failure(
        self,
        error: str,
        *,
        reason_code: str,
        failure_class: str = "hard_start_failure",
        stage: str,
    ) -> ContainerLifecycleRun:
        state = self._state
        self._emit(stage, reason=reason_code, detail=error)
        return self._run_result(
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

    def _recover_timeout_created_container(self, *, recreate: bool = False) -> bool:
        template = self.template
        state = self._state
        for _ in range(3):
            recovered_exists, recovered_error = container_exists(
                template.process_runner,
                container_name=template.container_name,
                cwd=template.project_root,
                env=template.env,
            )
            if recovered_error:
                return False
            if recovered_exists:
                mapped_port, port_error = container_host_port(
                    template.process_runner,
                    container_name=template.container_name,
                    container_port=template.container_port,
                    cwd=template.project_root,
                    env=template.env,
                )
                if port_error and not is_missing_port_mapping_error(port_error):
                    return False
                if mapped_port is not None and mapped_port != template.port:
                    state.mismatch_requested_port = int(template.port)
                    state.mismatch_existing_port = int(mapped_port)
                    state.mismatch_action = "adopt_existing_after_timeout"
                    state.effective_port = int(mapped_port)
                    state.port_adopted = True
                else:
                    self._reset_to_requested_port()
                self._emit(
                    "probe.retry.recreate.timeout_recovered" if recreate else "start.create.timeout_recovered",
                    reason=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                    detail=f"container_name={template.container_name}",
                )
                if not recreate:
                    state.timeout_recovered_create = True
                return True
            sleep_between_probes(template.process_runner, 1.0)
        return False

    def _attempt_local_settle(
        self,
        *,
        listener_ready: bool,
        probe_error_text: str,
        stage: str,
        success_stage: str,
        timeout_suffix: str,
    ) -> tuple[bool, str]:
        template = self.template
        state = self._state
        self._emit(
            stage,
            reason=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
            detail=probe_error_text,
        )
        settle_listener_ready = listener_ready
        if not settle_listener_ready:
            settle_listener_started = time.monotonic()
            settle_listener_ready = wait_for_port_ready(
                template.process_runner,
                state.effective_port,
                timeout=min(template.listener_wait_timeout, 3.0),
            )
            state.listener_wait_ms += self._add_stage_duration("listener_wait", settle_listener_started)
        if not settle_listener_ready:
            return False, f"probe timeout waiting for readiness on port {state.effective_port} {timeout_suffix}"
        settle_probe_started = time.monotonic()
        settle_attempts = max(
            template.probe_attempts,
            template.restart_probe_attempts,
            template.recreate_probe_attempts,
        )
        ready, settle_probe_error_text = template.probe_readiness(settle_attempts)
        self._add_stage_duration("probe", settle_probe_started)
        if ready:
            self._emit(success_stage)
            return True, ""
        return False, settle_probe_error_text or probe_error_text

    def _discover_existing_container(self) -> tuple[bool, ContainerLifecycleRun | None]:
        template = self.template
        discover_started = time.monotonic()
        self._emit("discover")
        exists, exists_error = container_exists(
            template.process_runner,
            container_name=template.container_name,
            cwd=template.project_root,
            env=template.env,
        )
        if exists_error:
            self._add_stage_duration("discover", discover_started)
            return False, self._failure(
                exists_error,
                reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                stage="discover.failed",
            )

        if exists:
            mapped_port, port_error = container_host_port(
                template.process_runner,
                container_name=template.container_name,
                container_port=template.container_port,
                cwd=template.project_root,
                env=template.env,
            )
            if port_error:
                if not is_missing_port_mapping_error(port_error):
                    self._add_stage_duration("discover", discover_started)
                    return False, self._failure(
                        port_error,
                        reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                        stage="discover.failed",
                    )
                mapped_port = None
            if mapped_port is None:
                self._emit("discover.recreate", reason=reason_code_to_string(PortFailureReason.PORT_IN_USE))
                self._state.container_recreated = True
                cleanup_error = stop_and_remove_container(
                    template.process_runner,
                    container_name=template.container_name,
                    cwd=template.project_root,
                    env=template.env,
                )
                if cleanup_error:
                    self._add_stage_duration("discover", discover_started)
                    return False, self._failure(
                        cleanup_error,
                        reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                        stage="discover.recreate.failed",
                    )
                exists = False
                self._reset_to_requested_port()
            elif mapped_port != template.port:
                self._state.mismatch_requested_port = int(template.port)
                self._state.mismatch_existing_port = int(mapped_port)
                if self._state.mismatch_policy == "adopt_existing":
                    self._state.mismatch_action = "adopt_existing"
                    self._state.effective_port = int(mapped_port)
                    self._state.port_adopted = True
                    self._emit(
                        "discover.port_mismatch.adopt_existing",
                        reason=reason_code_to_string(PortFailureReason.PORT_IN_USE),
                        detail=f"requested_port={template.port} existing_port={mapped_port}",
                    )
                else:
                    self._state.mismatch_action = "recreate"
                    self._emit(
                        "discover.port_mismatch.recreate",
                        reason=reason_code_to_string(PortFailureReason.PORT_IN_USE),
                        detail=f"requested_port={template.port} existing_port={mapped_port}",
                    )
                    self._state.container_recreated = True
                    cleanup_error = stop_and_remove_container(
                        template.process_runner,
                        container_name=template.container_name,
                        cwd=template.project_root,
                        env=template.env,
                    )
                    if cleanup_error:
                        self._add_stage_duration("discover", discover_started)
                        return False, self._failure(
                            cleanup_error,
                            reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                            stage="discover.recreate.failed",
                        )
                    exists = False
                    self._reset_to_requested_port()
            status, status_error = container_status(
                template.process_runner,
                container_name=template.container_name,
                cwd=template.project_root,
                env=template.env,
            )
            if status_error:
                self._add_stage_duration("discover", discover_started)
                return False, self._failure(
                    status_error,
                    reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                    stage="discover.status.failed",
                )
            if status == "created":
                state_error_text, state_error_read_error = container_state_error(
                    template.process_runner,
                    container_name=template.container_name,
                    cwd=template.project_root,
                    env=template.env,
                )
                if state_error_read_error:
                    self._add_stage_duration("discover", discover_started)
                    return False, self._failure(
                        state_error_read_error,
                        reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                        stage="discover.state_error.failed",
                    )
                if is_bind_conflict(state_error_text):
                    self._emit(
                        "discover.created_bind_conflict.cleanup",
                        reason=reason_code_to_string(PortFailureReason.PORT_IN_USE),
                        detail=state_error_text,
                    )
                    cleanup_error = stop_and_remove_container(
                        template.process_runner,
                        container_name=template.container_name,
                        cwd=template.project_root,
                        env=template.env,
                    )
                    if cleanup_error:
                        self._add_stage_duration("discover", discover_started)
                        return False, self._failure(
                            cleanup_error,
                            reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                            stage="discover.created_bind_conflict.cleanup_failed",
                        )
                    exists = False
                    self._reset_to_requested_port()
        self._add_stage_duration("discover", discover_started)
        return exists, None

    def _start_or_create_container(self, *, exists: bool) -> ContainerLifecycleRun | None:
        template = self.template
        start_or_create_started = time.monotonic()
        if exists:
            self._state.container_reused = True
            status, status_error = container_status(
                template.process_runner,
                container_name=template.container_name,
                cwd=template.project_root,
                env=template.env,
            )
            if status_error:
                self._add_stage_duration("start", start_or_create_started)
                return self._failure(
                    status_error,
                    reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                    stage="start.inspect.failed",
                )
            if status != "running":
                with docker_port_publish_lock(template.env):
                    start_result, start_error = run_docker(
                        template.process_runner,
                        ["start", template.container_name],
                        cwd=template.project_root,
                        env=template.env,
                        timeout=120.0,
                    )
                if start_result is None:
                    state_error_text, _ = container_state_error(
                        template.process_runner,
                        container_name=template.container_name,
                        cwd=template.project_root,
                        env=template.env,
                    )
                    self._add_stage_duration("start", start_or_create_started)
                    error_text = start_error or f"failed starting {template.service_name} container"
                    if is_bind_conflict(state_error_text) or is_bind_conflict(error_text):
                        cleanup_error = stop_and_remove_container(
                            template.process_runner,
                            container_name=template.container_name,
                            cwd=template.project_root,
                            env=template.env,
                        )
                        if cleanup_error:
                            error_text = f"{error_text}; cleanup failed: {cleanup_error}"
                        return self._failure(
                            format_bind_conflict_guidance(
                                template.service_name, template.port, state_error_text or error_text
                            ),
                            reason_code=reason_code_to_string(PortFailureReason.PORT_IN_USE),
                            failure_class=reason_code_to_string(RequirementLifecycleReason.BIND_CONFLICT_RETRYABLE),
                            stage="start.bind_conflict.unresolved",
                        )
                    return self._failure(
                        error_text,
                        reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                        stage="start.failed",
                    )
                if getattr(start_result, "returncode", 1) != 0:
                    error_text = run_result_error(start_result, f"failed starting {template.service_name} container")
                    state_error_text, _ = container_state_error(
                        template.process_runner,
                        container_name=template.container_name,
                        cwd=template.project_root,
                        env=template.env,
                    )
                    self._add_stage_duration("start", start_or_create_started)
                    if is_bind_conflict(state_error_text) or is_bind_conflict(error_text):
                        cleanup_error = stop_and_remove_container(
                            template.process_runner,
                            container_name=template.container_name,
                            cwd=template.project_root,
                            env=template.env,
                        )
                        if cleanup_error:
                            error_text = f"{error_text}; cleanup failed: {cleanup_error}"
                        return self._failure(
                            format_bind_conflict_guidance(
                                template.service_name, template.port, state_error_text or error_text
                            ),
                            reason_code=reason_code_to_string(PortFailureReason.PORT_IN_USE),
                            failure_class=reason_code_to_string(RequirementLifecycleReason.BIND_CONFLICT_RETRYABLE),
                            stage="start.bind_conflict.unresolved",
                        )
                    return self._failure(
                        error_text,
                        reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                        stage="start.failed",
                    )
            self._add_stage_duration("start", start_or_create_started)
            return None

        self._reset_to_requested_port()
        create_error = template.create_container()
        if create_error and is_bind_conflict(create_error):
            self._emit(
                "start.bind_conflict",
                reason=reason_code_to_string(PortFailureReason.PORT_IN_USE),
                detail=create_error,
            )
            if template.bind_cleanup is not None:
                cleaned, cleanup_error = template.bind_cleanup(template.port)
                if cleanup_error:
                    self._add_stage_duration("create", start_or_create_started)
                    return self._failure(
                        f"{create_error}; safe cleanup failed: {cleanup_error}",
                        reason_code=reason_code_to_string(
                            RequirementLifecycleReason.ENVCTL_OWNED_STALE_RESOURCE_CLEANUP_FAILED
                        ),
                        stage="start.bind_conflict.cleanup_failed",
                    )
                if cleaned:
                    self._emit(
                        "start.bind_conflict.cleaned",
                        reason=reason_code_to_string(RequirementLifecycleReason.ENVCTL_OWNED_STALE_RESOURCE_CLEANED),
                    )
                    create_error = template.create_container()
        if create_error:
            if timeout_error(create_error) and self._recover_timeout_created_container():
                self._add_stage_duration("create", start_or_create_started)
            else:
                self._add_stage_duration("create", start_or_create_started)
                if is_bind_conflict(create_error):
                    return self._failure(
                        format_bind_conflict_guidance(template.service_name, template.port, create_error),
                        reason_code=reason_code_to_string(RequirementLifecycleReason.BIND_CONFLICT_UNRESOLVED),
                        failure_class=reason_code_to_string(RequirementLifecycleReason.BIND_CONFLICT_RETRYABLE),
                        stage="start.bind_conflict.unresolved",
                    )
                if template.retryable_probe_error(create_error):
                    return self._failure(
                        create_error,
                        reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
                        failure_class=reason_code_to_string(
                            RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE
                        ),
                        stage="start.create.probe_timeout",
                    )
                return self._failure(
                    create_error,
                    reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                    stage="start.create.failed",
                )
        else:
            self._add_stage_duration("create", start_or_create_started)
        return None

    def run(self) -> ContainerLifecycleRun:
        self._state = self._new_state()
        template = self.template
        exists, failure = self._discover_existing_container()
        if failure is not None:
            return failure

        failure = self._start_or_create_container(exists=exists)
        if failure is not None:
            return failure

        listener_started = time.monotonic()
        listener_ready = wait_for_port_ready(
            template.process_runner,
            self._state.effective_port,
            timeout=template.listener_wait_timeout,
        )
        self._state.listener_wait_ms += self._add_stage_duration("listener_wait", listener_started)
        listener_error = f"probe timeout waiting for readiness on port {self._state.effective_port}"
        probe_error_text = listener_error
        local_settle_attempted = False
        if not listener_ready:
            if self._state.timeout_recovered_create or self._state.port_adopted:
                local_settle_attempted = True
                settled, settled_error = self._attempt_local_settle(
                    listener_ready=False,
                    probe_error_text=listener_error,
                    stage="probe.retry.timeout_recovered_settle"
                    if self._state.timeout_recovered_create
                    else "probe.retry.adopted_existing_settle",
                    success_stage="probe.healthy.after_timeout_recovery"
                    if self._state.timeout_recovered_create
                    else "probe.healthy.after_adopted_existing",
                    timeout_suffix="after timeout recovery"
                    if self._state.timeout_recovered_create
                    else "after adopted-existing settle",
                )
                if settled:
                    return self._success()
                probe_error_text = settled_error
                if not template.restart_on_listener_timeout:
                    return self._failure(
                        settled_error,
                        reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
                        failure_class=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
                        stage="probe.timeout_recovered_create.failed",
                    )
            if not template.restart_on_listener_timeout:
                return self._failure(
                    listener_error,
                    reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
                    failure_class=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
                    stage="probe.listener_timeout",
                )
    
        if listener_ready:
            probe_started = time.monotonic()
            ready, probe_error_text = template.probe_readiness(template.probe_attempts)
            self._add_stage_duration("probe", probe_started)
            if ready:
                self._emit("probe.healthy")
                return self._success()
    
        retryable = template.retryable_probe_error(probe_error_text)
        recovered_or_adopted = self._state.timeout_recovered_create or self._state.port_adopted
        if recovered_or_adopted and retryable and not local_settle_attempted:
            settled, settled_error = self._attempt_local_settle(
                listener_ready=True,
                probe_error_text=probe_error_text,
                stage="probe.retry.timeout_recovered_settle"
                if self._state.timeout_recovered_create
                else "probe.retry.adopted_existing_settle",
                success_stage="probe.healthy.after_timeout_recovery"
                if self._state.timeout_recovered_create
                else "probe.healthy.after_adopted_existing",
                timeout_suffix="after timeout recovery"
                if self._state.timeout_recovered_create
                else "after adopted-existing settle",
            )
            if settled:
                return self._success()
            return self._failure(
                settled_error,
                reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
                failure_class=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
                stage="probe.timeout_recovered_create.failed",
            )
        if template.restart_on_probe_failure and retryable:
            self._emit(
                "probe.retry.restart",
                reason=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
            )
            restart_started = time.monotonic()
            with docker_port_publish_lock(template.env):
                restart_result, restart_error = run_docker(
                    template.process_runner,
                    ["restart", template.container_name],
                    cwd=template.project_root,
                    env=template.env,
                    timeout=120.0,
                )
            if restart_result is None:
                self._add_stage_duration("restart", restart_started)
                detail = (restart_error or "").strip()
                message = f"failed restarting {template.service_name} container"
                if detail:
                    message = f"{message}: {detail}"
                return self._failure(
                    message,
                    reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                    stage="probe.retry.restart.failed",
                )
            if getattr(restart_result, "returncode", 1) != 0:
                self._add_stage_duration("restart", restart_started)
                detail = run_result_error(restart_result, f"failed restarting {template.service_name} container")
                message = detail
                fallback = f"failed restarting {template.service_name} container"
                if detail != fallback:
                    message = f"{fallback}: {detail}"
                return self._failure(
                    message,
                    reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                    stage="probe.retry.restart.failed",
                )
            self._add_stage_duration("restart", restart_started)
            restart_listener_started = time.monotonic()
            restart_listener_ready = wait_for_port_ready(
                template.process_runner,
                self._state.effective_port,
                timeout=template.listener_wait_timeout,
            )
            self._state.listener_wait_ms += self._add_stage_duration("listener_wait", restart_listener_started)
            if not restart_listener_ready:
                restart_timeout_error = (
                    f"probe timeout waiting for readiness on port {self._state.effective_port} after restart"
                )
                if not template.recreate_on_restart_listener_timeout:
                    return self._failure(
                        restart_timeout_error,
                        reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
                        failure_class=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
                        stage="probe.retry.restart.listener_timeout",
                    )
                probe_error_text = restart_timeout_error
                retryable = template.retryable_probe_error(probe_error_text)
            else:
                restart_probe_started = time.monotonic()
                ready, probe_error_text = template.probe_readiness(template.restart_probe_attempts)
                self._add_stage_duration("probe", restart_probe_started)
                if ready:
                    self._emit("probe.healthy.after_restart")
                    return self._success()
                retryable = template.retryable_probe_error(probe_error_text)
    
            if template.recreate_on_probe_failure and retryable:
                self._emit(
                    "probe.retry.recreate",
                    reason=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
                )
                self._state.container_recreated = True
                recreate_started = time.monotonic()
                cleanup_error = stop_and_remove_container(
                    template.process_runner,
                    container_name=template.container_name,
                    cwd=template.project_root,
                    env=template.env,
                )
                if cleanup_error:
                    self._add_stage_duration("recreate", recreate_started)
                    return self._failure(
                        f"failed recreating {template.service_name} container: {cleanup_error}",
                        reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                        stage="probe.retry.recreate.cleanup_failed",
                    )
                recreate_error = template.create_container()
                if recreate_error:
                    if not (timeout_error(recreate_error) and self._recover_timeout_created_container(recreate=True)):
                        self._add_stage_duration("recreate", recreate_started)
                        if template.retryable_probe_error(recreate_error):
                            return self._failure(
                                f"failed recreating {template.service_name} container: {recreate_error}",
                                reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
                                failure_class=reason_code_to_string(
                                    RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE
                                ),
                                stage="probe.retry.recreate.probe_timeout",
                            )
                        return self._failure(
                            f"failed recreating {template.service_name} container: {recreate_error}",
                            reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                            stage="probe.retry.recreate.failed",
                        )
                else:
                    self._reset_to_requested_port()
                    if self._state.mismatch_action == "adopt_existing":
                        self._state.mismatch_action = "recreate_after_adopted_existing_unreachable"
                recreate_listener_started = time.monotonic()
                recreate_listener_ready = wait_for_port_ready(
                    template.process_runner,
                    self._state.effective_port,
                    timeout=template.listener_wait_timeout,
                )
                self._state.listener_wait_ms += self._add_stage_duration("listener_wait", recreate_listener_started)
                if not recreate_listener_ready:
                    self._add_stage_duration("recreate", recreate_started)
                    return self._failure(
                        f"probe timeout waiting for readiness on port {self._state.effective_port} after recreate",
                        reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
                        failure_class=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
                        stage="probe.retry.recreate.listener_timeout",
                    )
                recreate_probe_started = time.monotonic()
                ready, probe_error_text = template.probe_readiness(template.recreate_probe_attempts)
                self._add_stage_duration("probe", recreate_probe_started)
                self._add_stage_duration("recreate", recreate_started)
                if ready:
                    self._emit("probe.healthy.after_recreate")
                    return self._success()
    
        return self._failure(
            probe_error_text or template.probe_failure_fallback,
            reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
            failure_class=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
            stage="probe.failed",
        )


def run_container_lifecycle(template: ContainerLifecycleTemplate) -> ContainerLifecycleRun:
    return ContainerLifecycleExecutor(template).run()


__all__ = tuple(name for name in globals() if not name.startswith("_"))
