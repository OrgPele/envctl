from __future__ import annotations

import time
from collections.abc import Callable

from envctl_engine.requirements.adapter_lifecycle_models import ContainerLifecycleRun, ContainerLifecycleTemplate
from envctl_engine.requirements.container_lifecycle_docker import ContainerLifecycleDockerClient
from envctl_engine.requirements.container_lifecycle_state import ContainerLifecycleState

from .adapter_policy import timeout_error
from .docker_runtime import run_result_error
from ..shared.reason_codes import (
    RequirementFailureReason,
    RequirementLifecycleReason,
    reason_code_to_string,
)


class ContainerLifecycleProbePhase:
    """Owns readiness probing plus restart/recreate recovery for container adapters."""

    def __init__(
        self,
        *,
        template: ContainerLifecycleTemplate,
        state: ContainerLifecycleState,
        docker: ContainerLifecycleDockerClient,
        emit: Callable[[str, str | None, str | None], None],
        add_stage_duration: Callable[[str, float], float],
        success: Callable[[], ContainerLifecycleRun],
        failure: Callable[..., ContainerLifecycleRun],
        reset_to_requested_port: Callable[[], None],
        recover_timeout_created_container: Callable[..., bool],
        wait_for_port_ready_fn: Callable[..., bool],
    ) -> None:
        self.template = template
        self.state = state
        self.docker = docker
        self.emit = emit
        self.add_stage_duration = add_stage_duration
        self.success = success
        self.failure = failure
        self.reset_to_requested_port = reset_to_requested_port
        self.recover_timeout_created_container = recover_timeout_created_container
        self.wait_for_port_ready = wait_for_port_ready_fn

    def attempt_local_settle(
        self,
        *,
        listener_ready: bool,
        probe_error_text: str | None,
        stage: str,
        success_stage: str,
        timeout_suffix: str,
    ) -> tuple[bool, str]:
        template = self.template
        state = self.state
        self.emit(
            stage,
            reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
            probe_error_text,
        )
        settle_listener_ready = listener_ready
        if not settle_listener_ready:
            settle_listener_started = time.monotonic()
            settle_listener_ready = self.wait_for_port_ready(
                template.process_runner,
                state.effective_port,
                timeout=min(template.listener_wait_timeout, 3.0),
            )
            state.listener_wait_ms += self.add_stage_duration("listener_wait", settle_listener_started)
        if not settle_listener_ready:
            return False, f"probe timeout waiting for readiness on port {state.effective_port} {timeout_suffix}"
        settle_probe_started = time.monotonic()
        settle_attempts = max(
            template.probe_attempts,
            template.restart_probe_attempts,
            template.recreate_probe_attempts,
        )
        ready, settle_probe_error_text = template.probe_readiness(settle_attempts)
        self.add_stage_duration("probe", settle_probe_started)
        if ready:
            self.emit(success_stage, None, None)
            return True, ""
        return False, settle_probe_error_text or probe_error_text or template.probe_failure_fallback

    def restart_after_probe_failure(
        self, *, probe_error_text: str | None
    ) -> tuple[str | None, ContainerLifecycleRun | None]:
        template = self.template
        if not (template.restart_on_probe_failure and template.retryable_probe_error(probe_error_text)):
            return probe_error_text, None

        self.emit(
            "probe.retry.restart",
            reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
            None,
        )
        restart_started = time.monotonic()
        restart_result, restart_error = self.docker.restart()
        if restart_result is None:
            self.add_stage_duration("restart", restart_started)
            detail = (restart_error or "").strip()
            message = f"failed restarting {template.service_name} container"
            if detail:
                message = f"{message}: {detail}"
            return probe_error_text, self.failure(
                message,
                reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                stage="probe.retry.restart.failed",
            )
        if getattr(restart_result, "returncode", 1) != 0:
            self.add_stage_duration("restart", restart_started)
            detail = run_result_error(restart_result, f"failed restarting {template.service_name} container")
            message = detail
            fallback = f"failed restarting {template.service_name} container"
            if detail != fallback:
                message = f"{fallback}: {detail}"
            return probe_error_text, self.failure(
                message,
                reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                stage="probe.retry.restart.failed",
            )
        self.add_stage_duration("restart", restart_started)

        restart_listener_started = time.monotonic()
        restart_listener_ready = self.wait_for_port_ready(
            template.process_runner,
            self.state.effective_port,
            timeout=template.listener_wait_timeout,
        )
        self.state.listener_wait_ms += self.add_stage_duration("listener_wait", restart_listener_started)
        if not restart_listener_ready:
            probe_error_text = f"probe timeout waiting for readiness on port {self.state.effective_port} after restart"
            if not template.recreate_on_restart_listener_timeout:
                return probe_error_text, self.failure(
                    probe_error_text,
                    reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
                    failure_class=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
                    stage="probe.retry.restart.listener_timeout",
                )
        else:
            restart_probe_started = time.monotonic()
            ready, probe_error_text = template.probe_readiness(template.restart_probe_attempts)
            self.add_stage_duration("probe", restart_probe_started)
            if ready:
                self.emit("probe.healthy.after_restart", None, None)
                return probe_error_text, self.success()

        return self.recreate_after_restart_failure(probe_error_text=probe_error_text)

    def recreate_after_restart_failure(
        self, *, probe_error_text: str | None
    ) -> tuple[str | None, ContainerLifecycleRun | None]:
        template = self.template
        if not (template.recreate_on_probe_failure and template.retryable_probe_error(probe_error_text)):
            return probe_error_text, None

        self.emit(
            "probe.retry.recreate",
            reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
            None,
        )
        self.state.container_recreated = True
        recreate_started = time.monotonic()
        cleanup_error = self.docker.stop_and_remove()
        if cleanup_error:
            self.add_stage_duration("recreate", recreate_started)
            return probe_error_text, self.failure(
                f"failed recreating {template.service_name} container: {cleanup_error}",
                reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                stage="probe.retry.recreate.cleanup_failed",
            )
        recreate_error = template.create_container()
        if recreate_error:
            if not (
                timeout_error(recreate_error)
                and self.recover_timeout_created_container(recreate=True)
            ):
                self.add_stage_duration("recreate", recreate_started)
                if template.retryable_probe_error(recreate_error):
                    return probe_error_text, self.failure(
                        f"failed recreating {template.service_name} container: {recreate_error}",
                        reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
                        failure_class=reason_code_to_string(
                            RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE
                        ),
                        stage="probe.retry.recreate.probe_timeout",
                    )
                return probe_error_text, self.failure(
                    f"failed recreating {template.service_name} container: {recreate_error}",
                    reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                    stage="probe.retry.recreate.failed",
                )
        else:
            self.reset_to_requested_port()
            if self.state.mismatch_action == "adopt_existing":
                self.state.mismatch_action = "recreate_after_adopted_existing_unreachable"

        recreate_listener_started = time.monotonic()
        recreate_listener_ready = self.wait_for_port_ready(
            template.process_runner,
            self.state.effective_port,
            timeout=template.listener_wait_timeout,
        )
        self.state.listener_wait_ms += self.add_stage_duration("listener_wait", recreate_listener_started)
        if not recreate_listener_ready:
            self.add_stage_duration("recreate", recreate_started)
            probe_error_text = f"probe timeout waiting for readiness on port {self.state.effective_port} after recreate"
            return probe_error_text, self.failure(
                probe_error_text,
                reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
                failure_class=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
                stage="probe.retry.recreate.listener_timeout",
            )
        recreate_probe_started = time.monotonic()
        ready, probe_error_text = template.probe_readiness(template.recreate_probe_attempts)
        self.add_stage_duration("probe", recreate_probe_started)
        self.add_stage_duration("recreate", recreate_started)
        if ready:
            self.emit("probe.healthy.after_recreate", None, None)
            return probe_error_text, self.success()
        return probe_error_text, None

    def run(self) -> ContainerLifecycleRun:
        template = self.template
        listener_started = time.monotonic()
        listener_ready = self.wait_for_port_ready(
            template.process_runner,
            self.state.effective_port,
            timeout=template.listener_wait_timeout,
        )
        self.state.listener_wait_ms += self.add_stage_duration("listener_wait", listener_started)
        listener_error = f"probe timeout waiting for readiness on port {self.state.effective_port}"
        probe_error_text = listener_error
        local_settle_attempted = False
        if not listener_ready:
            if self.state.timeout_recovered_create or self.state.port_adopted:
                local_settle_attempted = True
                settled, settled_error = self.attempt_local_settle(
                    listener_ready=False,
                    probe_error_text=listener_error,
                    stage="probe.retry.timeout_recovered_settle"
                    if self.state.timeout_recovered_create
                    else "probe.retry.adopted_existing_settle",
                    success_stage="probe.healthy.after_timeout_recovery"
                    if self.state.timeout_recovered_create
                    else "probe.healthy.after_adopted_existing",
                    timeout_suffix="after timeout recovery"
                    if self.state.timeout_recovered_create
                    else "after adopted-existing settle",
                )
                if settled:
                    return self.success()
                probe_error_text = settled_error
                if not template.restart_on_listener_timeout:
                    return self.failure(
                        settled_error,
                        reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
                        failure_class=reason_code_to_string(
                            RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE
                        ),
                        stage="probe.timeout_recovered_create.failed",
                    )
            if not template.restart_on_listener_timeout:
                return self.failure(
                    listener_error,
                    reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
                    failure_class=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
                    stage="probe.listener_timeout",
                )

        if listener_ready:
            probe_started = time.monotonic()
            ready, probe_error_text = template.probe_readiness(template.probe_attempts)
            self.add_stage_duration("probe", probe_started)
            if ready:
                self.emit("probe.healthy", None, None)
                return self.success()

        retryable = template.retryable_probe_error(probe_error_text)
        recovered_or_adopted = self.state.timeout_recovered_create or self.state.port_adopted
        if recovered_or_adopted and retryable and not local_settle_attempted:
            settled, settled_error = self.attempt_local_settle(
                listener_ready=True,
                probe_error_text=probe_error_text,
                stage="probe.retry.timeout_recovered_settle"
                if self.state.timeout_recovered_create
                else "probe.retry.adopted_existing_settle",
                success_stage="probe.healthy.after_timeout_recovery"
                if self.state.timeout_recovered_create
                else "probe.healthy.after_adopted_existing",
                timeout_suffix="after timeout recovery"
                if self.state.timeout_recovered_create
                else "after adopted-existing settle",
            )
            if settled:
                return self.success()
            return self.failure(
                settled_error,
                reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
                failure_class=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
                stage="probe.timeout_recovered_create.failed",
            )
        probe_error_text, recovery = self.restart_after_probe_failure(probe_error_text=probe_error_text)
        if recovery is not None:
            return recovery

        return self.failure(
            probe_error_text or template.probe_failure_fallback,
            reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
            failure_class=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
            stage="probe.failed",
        )


__all__ = [
    "ContainerLifecycleProbePhase",
]
