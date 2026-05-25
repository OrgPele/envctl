from __future__ import annotations

import time

from envctl_engine.requirements.container_lifecycle_docker import ContainerLifecycleDockerClient
from envctl_engine.requirements.container_lifecycle_state import (
    ContainerLifecycleRecorder,
    ContainerLifecycleState,
)

from .adapter_lifecycle_models import ContainerLifecycleRun, ContainerLifecycleTemplate
from .container_lifecycle_probe_phase import ContainerLifecycleProbePhase
from ..shared.reason_codes import (
    PortFailureReason,
    RequirementFailureReason,
    RequirementLifecycleReason,
    reason_code_to_string,
)
from .adapter_policy import sleep_between_probes, timeout_error
from .adapter_port_cleanup import format_bind_conflict_guidance, wait_for_port_ready
from .common import (
    is_bind_conflict,
    is_missing_port_mapping_error,
    run_result_error,
)


class ContainerLifecycleExecutor:
    def __init__(self, template: ContainerLifecycleTemplate) -> None:
        self.template = template
        self._docker = ContainerLifecycleDockerClient(template)
        self._recorder = ContainerLifecycleRecorder(template)
        self._state = self._recorder.state

    def _new_state(self) -> ContainerLifecycleState:
        return self._recorder.reset()

    def _emit(self, stage: str, reason: str | None = None, detail: str | None = None) -> None:
        self._recorder.emit(stage, reason=reason, detail=detail)

    def _add_stage_duration(self, name: str, stage_started_at: float) -> float:
        return self._recorder.add_stage_duration(name, stage_started_at)

    def _run_result(self, *, result) -> ContainerLifecycleRun:  # noqa: ANN001
        return self._recorder.run_result(result=result)

    def _success(self) -> ContainerLifecycleRun:
        return self._recorder.success()

    def _reset_to_requested_port(self) -> None:
        self._recorder.reset_to_requested_port()

    def _failure(
        self,
        error: str,
        *,
        reason_code: str,
        failure_class: str = "hard_start_failure",
        stage: str,
    ) -> ContainerLifecycleRun:
        return self._recorder.failure(
            error,
            reason_code=reason_code,
            failure_class=failure_class,
            stage=stage,
        )

    def _recover_timeout_created_container(self, *, recreate: bool = False) -> bool:
        template = self.template
        state = self._state
        for _ in range(3):
            recovered_exists, recovered_error = self._docker.exists()
            if recovered_error:
                return False
            if recovered_exists:
                mapped_port, port_error = self._docker.host_port()
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

    def _probe_phase(self) -> ContainerLifecycleProbePhase:
        return ContainerLifecycleProbePhase(
            template=self.template,
            state=self._state,
            docker=self._docker,
            emit=lambda stage, reason=None, detail=None: self._emit(stage, reason=reason, detail=detail),
            add_stage_duration=self._add_stage_duration,
            success=self._success,
            failure=self._failure,
            reset_to_requested_port=self._reset_to_requested_port,
            recover_timeout_created_container=self._recover_timeout_created_container,
            wait_for_port_ready_fn=wait_for_port_ready,
        )

    def _attempt_local_settle(
        self,
        *,
        listener_ready: bool,
        probe_error_text: str | None,
        stage: str,
        success_stage: str,
        timeout_suffix: str,
    ) -> tuple[bool, str]:
        return self._probe_phase().attempt_local_settle(
            listener_ready=listener_ready,
            probe_error_text=probe_error_text,
            stage=stage,
            success_stage=success_stage,
            timeout_suffix=timeout_suffix,
        )

    def _discover_existing_container(self) -> tuple[bool, ContainerLifecycleRun | None]:
        template = self.template
        discover_started = time.monotonic()
        self._emit("discover")
        exists, exists_error = self._docker.exists()
        if exists_error:
            self._add_stage_duration("discover", discover_started)
            return False, self._failure(
                exists_error,
                reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                stage="discover.failed",
            )

        if exists:
            mapped_port, port_error = self._docker.host_port()
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
                cleanup_error = self._docker.stop_and_remove()
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
                    cleanup_error = self._docker.stop_and_remove()
                    if cleanup_error:
                        self._add_stage_duration("discover", discover_started)
                        return False, self._failure(
                            cleanup_error,
                            reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                            stage="discover.recreate.failed",
                        )
                    exists = False
                    self._reset_to_requested_port()
            status, status_error = self._docker.status()
            if status_error:
                self._add_stage_duration("discover", discover_started)
                return False, self._failure(
                    status_error,
                    reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                    stage="discover.status.failed",
                )
            if status == "created":
                state_error_text, state_error_read_error = self._docker.state_error()
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
                    cleanup_error = self._docker.stop_and_remove()
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
            status, status_error = self._docker.status()
            if status_error:
                self._add_stage_duration("start", start_or_create_started)
                return self._failure(
                    status_error,
                    reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                    stage="start.inspect.failed",
                )
            if status != "running":
                failure = self._start_existing_container(started_at=start_or_create_started)
                if failure is not None:
                    return failure
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

    def _start_existing_container(self, *, started_at: float) -> ContainerLifecycleRun | None:
        template = self.template
        start_result, start_error = self._docker.start()
        fallback = f"failed starting {template.service_name} container"
        if start_result is None:
            error_text = start_error or fallback
            return self._start_existing_failure(error_text, started_at=started_at)
        if getattr(start_result, "returncode", 1) != 0:
            error_text = run_result_error(start_result, fallback)
            return self._start_existing_failure(error_text, started_at=started_at)
        return None

    def _start_existing_failure(self, error_text: str, *, started_at: float) -> ContainerLifecycleRun:
        template = self.template
        state_error_text, _ = self._docker.state_error()
        self._add_stage_duration("start", started_at)
        if is_bind_conflict(state_error_text) or is_bind_conflict(error_text):
            cleanup_error = self._docker.stop_and_remove()
            if cleanup_error:
                error_text = f"{error_text}; cleanup failed: {cleanup_error}"
            return self._failure(
                format_bind_conflict_guidance(template.service_name, template.port, state_error_text or error_text),
                reason_code=reason_code_to_string(PortFailureReason.PORT_IN_USE),
                failure_class=reason_code_to_string(RequirementLifecycleReason.BIND_CONFLICT_RETRYABLE),
                stage="start.bind_conflict.unresolved",
            )
        return self._failure(
            error_text,
            reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
            stage="start.failed",
        )

    def _restart_after_probe_failure(
        self, *, probe_error_text: str | None
    ) -> tuple[str | None, ContainerLifecycleRun | None]:
        return self._probe_phase().restart_after_probe_failure(probe_error_text=probe_error_text)

    def _recreate_after_restart_failure(
        self, *, probe_error_text: str | None
    ) -> tuple[str | None, ContainerLifecycleRun | None]:
        return self._probe_phase().recreate_after_restart_failure(probe_error_text=probe_error_text)

    def _run_readiness_probe_phase(self) -> ContainerLifecycleRun:
        return self._probe_phase().run()

    def run(self) -> ContainerLifecycleRun:
        self._state = self._new_state()
        exists, failure = self._discover_existing_container()
        if failure is not None:
            return failure

        failure = self._start_or_create_container(exists=exists)
        if failure is not None:
            return failure

        return self._run_readiness_probe_phase()


def run_container_lifecycle(template: ContainerLifecycleTemplate) -> ContainerLifecycleRun:
    return ContainerLifecycleExecutor(template).run()


__all__ = [
    "ContainerLifecycleDockerClient",
    "ContainerLifecycleExecutor",
    "ContainerLifecycleProbePhase",
    "ContainerLifecycleRecorder",
    "ContainerLifecycleRun",
    "ContainerLifecycleState",
    "ContainerLifecycleTemplate",
    "run_container_lifecycle",
]
