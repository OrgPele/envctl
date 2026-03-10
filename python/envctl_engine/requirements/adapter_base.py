from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from ..shared.env_access import float_from_env, int_from_env, str_from_env
from ..shared.parsing import parse_bool
from ..shared.reason_codes import (
    PortFailureReason,
    RequirementFailureReason,
    RequirementLifecycleReason,
    reason_code_to_string,
)
from .common import (
    ContainerStartResult,
    container_exists,
    container_host_port,
    container_state_error,
    container_status,
    is_bind_conflict,
    is_missing_port_mapping_error,
    run_docker,
    run_result_error,
    stop_and_remove_container,
)


def timeout_error(error: str | None) -> bool:
    normalized = (error or "").lower()
    return "command timed out" in normalized


def sleep_between_probes(process_runner: object, seconds: float) -> None:
    if seconds <= 0:
        return
    sleeper = getattr(process_runner, "sleep", None)
    if callable(sleeper):
        _ = sleeper(seconds)
        return
    time.sleep(seconds)


def env_bool(env: Mapping[str, str] | None, key: str, default: bool) -> bool:
    return parse_bool(str_from_env(env, key), default)


def env_int(env: Mapping[str, str] | None, key: str, default: int, *, minimum: int | None = None) -> int:
    value = int_from_env(env, key, default)
    if minimum is not None:
        return max(minimum, value)
    return value


def env_float(env: Mapping[str, str] | None, key: str, default: float, *, minimum: float | None = None) -> float:
    value = float_from_env(env, key, default)
    if minimum is not None:
        return max(minimum, value)
    return value


def port_mismatch_policy(env: Mapping[str, str] | None) -> str:
    raw = (str_from_env(env, "ENVCTL_REQUIREMENTS_PORT_MISMATCH_POLICY") or "").strip().lower()
    if raw == "recreate":
        return "recreate"
    return "adopt_existing"


def retryable_probe_error(error: str | None, tokens: tuple[str, ...]) -> bool:
    normalized = (error or "").lower()
    return any(token in normalized for token in tokens)


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
    process_runner: object
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


def run_container_lifecycle(template: ContainerLifecycleTemplate) -> ContainerLifecycleRun:
    events: list[AdapterLifecycleEvent] = []
    stage_durations_ms: dict[str, float] = {}
    listener_wait_ms = 0.0
    container_reused = False
    container_recreated = False
    effective_port = int(template.port)
    port_adopted = False
    mismatch_requested_port: int | None = None
    mismatch_existing_port: int | None = None
    mismatch_action: str | None = None
    mismatch_policy = port_mismatch_policy(template.env)
    timeout_recovered_create = False
    started_at = time.monotonic()

    def _emit(stage: str, reason: str | None = None, detail: str | None = None) -> None:
        elapsed_ms = round((time.monotonic() - started_at) * 1000.0, 2)
        payload = AdapterLifecycleEvent(stage=stage, reason=reason, detail=detail, elapsed_ms=elapsed_ms)
        events.append(payload)
        if callable(template.trace_stage):
            template.trace_stage(payload.to_payload())

    def _add_stage_duration(name: str, stage_started_at: float) -> float:
        duration_ms = round((time.monotonic() - stage_started_at) * 1000.0, 2)
        stage_durations_ms[name] = round(stage_durations_ms.get(name, 0.0) + duration_ms, 2)
        return duration_ms

    def _run_result(
        *,
        result: ContainerStartResult,
    ) -> ContainerLifecycleRun:
        if result.effective_port is None:
            result.effective_port = int(effective_port)
        result.port_adopted = bool(result.port_adopted or port_adopted)
        if result.port_mismatch_requested_port is None:
            result.port_mismatch_requested_port = mismatch_requested_port
        if result.port_mismatch_existing_port is None:
            result.port_mismatch_existing_port = mismatch_existing_port
        if result.port_mismatch_action is None:
            result.port_mismatch_action = mismatch_action
        return ContainerLifecycleRun(
            result=result,
            events=events,
            stage_durations_ms=stage_durations_ms,
            listener_wait_ms=round(listener_wait_ms, 2),
            container_reused=container_reused,
            container_recreated=container_recreated,
        )

    def _failure(
        error: str,
        *,
        reason_code: str,
        failure_class: str = "hard_start_failure",
        stage: str,
    ) -> ContainerLifecycleRun:
        _emit(stage, reason=reason_code, detail=error)
        return _run_result(
            result=ContainerStartResult(
                success=False,
                container_name=template.container_name,
                error=error,
                reason_code=reason_code,
                failure_class=failure_class,
                effective_port=int(effective_port),
                port_adopted=bool(port_adopted),
                port_mismatch_requested_port=mismatch_requested_port,
                port_mismatch_existing_port=mismatch_existing_port,
                port_mismatch_action=mismatch_action,
            )
        )

    def _recover_timeout_created_container(*, recreate: bool = False) -> bool:
        nonlocal \
            effective_port, \
            port_adopted, \
            mismatch_requested_port, \
            mismatch_existing_port, \
            mismatch_action, \
            timeout_recovered_create
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
                    mismatch_requested_port = int(template.port)
                    mismatch_existing_port = int(mapped_port)
                    mismatch_action = "adopt_existing_after_timeout"
                    effective_port = int(mapped_port)
                    port_adopted = True
                else:
                    effective_port = int(template.port)
                    port_adopted = False
                _emit(
                    "probe.retry.recreate.timeout_recovered" if recreate else "start.create.timeout_recovered",
                    reason=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                    detail=f"container_name={template.container_name}",
                )
                if not recreate:
                    timeout_recovered_create = True
                return True
            sleep_between_probes(template.process_runner, 1.0)
        return False

    def _attempt_local_settle(
        *,
        listener_ready: bool,
        probe_error_text: str,
        stage: str,
        success_stage: str,
        timeout_suffix: str,
    ) -> tuple[bool, str]:
        nonlocal listener_wait_ms
        _emit(
            stage,
            reason=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
            detail=probe_error_text,
        )
        settle_listener_ready = listener_ready
        if not settle_listener_ready:
            settle_listener_started = time.monotonic()
            settle_listener_ready = wait_for_port_ready(
                template.process_runner,
                effective_port,
                timeout=min(template.listener_wait_timeout, 3.0),
            )
            listener_wait_ms += _add_stage_duration("listener_wait", settle_listener_started)
        if not settle_listener_ready:
            return False, f"probe timeout waiting for readiness on port {effective_port} {timeout_suffix}"
        settle_probe_started = time.monotonic()
        settle_attempts = max(
            template.probe_attempts,
            template.restart_probe_attempts,
            template.recreate_probe_attempts,
        )
        ready, settle_probe_error_text = template.probe_readiness(settle_attempts)
        _add_stage_duration("probe", settle_probe_started)
        if ready:
            _emit(success_stage)
            return True, ""
        return False, settle_probe_error_text or probe_error_text

    discover_started = time.monotonic()
    _emit("discover")
    exists, exists_error = container_exists(
        template.process_runner,
        container_name=template.container_name,
        cwd=template.project_root,
        env=template.env,
    )
    if exists_error:
        _add_stage_duration("discover", discover_started)
        return _failure(
            exists_error,
            reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
            stage="discover.failed",
        )

    if exists:
        state_error_text: str | None = None
        mapped_port, port_error = container_host_port(
            template.process_runner,
            container_name=template.container_name,
            container_port=template.container_port,
            cwd=template.project_root,
            env=template.env,
        )
        if port_error:
            if not is_missing_port_mapping_error(port_error):
                _add_stage_duration("discover", discover_started)
                return _failure(
                    port_error,
                    reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                    stage="discover.failed",
                )
            mapped_port = None
        if mapped_port is None:
            _emit("discover.recreate", reason=reason_code_to_string(PortFailureReason.PORT_IN_USE))
            container_recreated = True
            cleanup_error = stop_and_remove_container(
                template.process_runner,
                container_name=template.container_name,
                cwd=template.project_root,
                env=template.env,
            )
            if cleanup_error:
                _add_stage_duration("discover", discover_started)
                return _failure(
                    cleanup_error,
                    reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                    stage="discover.recreate.failed",
                )
            exists = False
            effective_port = int(template.port)
            port_adopted = False
        elif mapped_port != template.port:
            mismatch_requested_port = int(template.port)
            mismatch_existing_port = int(mapped_port)
            if mismatch_policy == "adopt_existing":
                mismatch_action = "adopt_existing"
                effective_port = int(mapped_port)
                port_adopted = True
                _emit(
                    "discover.port_mismatch.adopt_existing",
                    reason=reason_code_to_string(PortFailureReason.PORT_IN_USE),
                    detail=f"requested_port={template.port} existing_port={mapped_port}",
                )
            else:
                mismatch_action = "recreate"
                _emit(
                    "discover.port_mismatch.recreate",
                    reason=reason_code_to_string(PortFailureReason.PORT_IN_USE),
                    detail=f"requested_port={template.port} existing_port={mapped_port}",
                )
                container_recreated = True
                cleanup_error = stop_and_remove_container(
                    template.process_runner,
                    container_name=template.container_name,
                    cwd=template.project_root,
                    env=template.env,
                )
                if cleanup_error:
                    _add_stage_duration("discover", discover_started)
                    return _failure(
                        cleanup_error,
                        reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                        stage="discover.recreate.failed",
                    )
                exists = False
                effective_port = int(template.port)
                port_adopted = False
        status, status_error = container_status(
            template.process_runner,
            container_name=template.container_name,
            cwd=template.project_root,
            env=template.env,
        )
        if status_error:
            _add_stage_duration("discover", discover_started)
            return _failure(
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
                _add_stage_duration("discover", discover_started)
                return _failure(
                    state_error_read_error,
                    reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                    stage="discover.state_error.failed",
                )
            if is_bind_conflict(state_error_text):
                _emit(
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
                    _add_stage_duration("discover", discover_started)
                    return _failure(
                        cleanup_error,
                        reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                        stage="discover.created_bind_conflict.cleanup_failed",
                    )
                exists = False
                effective_port = int(template.port)
                port_adopted = False
    _add_stage_duration("discover", discover_started)

    start_or_create_started = time.monotonic()
    if exists:
        container_reused = True
        status, status_error = container_status(
            template.process_runner,
            container_name=template.container_name,
            cwd=template.project_root,
            env=template.env,
        )
        if status_error:
            _add_stage_duration("start", start_or_create_started)
            return _failure(
                status_error,
                reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                stage="start.inspect.failed",
            )
        if status != "running":
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
                _add_stage_duration("start", start_or_create_started)
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
                    return _failure(
                        format_bind_conflict_guidance(
                            template.service_name, template.port, state_error_text or error_text
                        ),
                        reason_code=reason_code_to_string(PortFailureReason.PORT_IN_USE),
                        failure_class=reason_code_to_string(RequirementLifecycleReason.BIND_CONFLICT_RETRYABLE),
                        stage="start.bind_conflict.unresolved",
                    )
                return _failure(
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
                _add_stage_duration("start", start_or_create_started)
                if is_bind_conflict(state_error_text) or is_bind_conflict(error_text):
                    cleanup_error = stop_and_remove_container(
                        template.process_runner,
                        container_name=template.container_name,
                        cwd=template.project_root,
                        env=template.env,
                    )
                    if cleanup_error:
                        error_text = f"{error_text}; cleanup failed: {cleanup_error}"
                    return _failure(
                        format_bind_conflict_guidance(
                            template.service_name, template.port, state_error_text or error_text
                        ),
                        reason_code=reason_code_to_string(PortFailureReason.PORT_IN_USE),
                        failure_class=reason_code_to_string(RequirementLifecycleReason.BIND_CONFLICT_RETRYABLE),
                        stage="start.bind_conflict.unresolved",
                    )
                return _failure(
                    error_text,
                    reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                    stage="start.failed",
                )
        _add_stage_duration("start", start_or_create_started)
    else:
        effective_port = int(template.port)
        port_adopted = False
        create_error = template.create_container()
        if create_error and is_bind_conflict(create_error):
            _emit(
                "start.bind_conflict", reason=reason_code_to_string(PortFailureReason.PORT_IN_USE), detail=create_error
            )
            if template.bind_cleanup is not None:
                cleaned, cleanup_error = template.bind_cleanup(template.port)
                if cleanup_error:
                    _add_stage_duration("create", start_or_create_started)
                    return _failure(
                        f"{create_error}; safe cleanup failed: {cleanup_error}",
                        reason_code=reason_code_to_string(
                            RequirementLifecycleReason.ENVCTL_OWNED_STALE_RESOURCE_CLEANUP_FAILED
                        ),
                        stage="start.bind_conflict.cleanup_failed",
                    )
                if cleaned:
                    _emit(
                        "start.bind_conflict.cleaned",
                        reason=reason_code_to_string(RequirementLifecycleReason.ENVCTL_OWNED_STALE_RESOURCE_CLEANED),
                    )
                    create_error = template.create_container()
        if create_error:
            if timeout_error(create_error) and _recover_timeout_created_container():
                _add_stage_duration("create", start_or_create_started)
            else:
                _add_stage_duration("create", start_or_create_started)
                if is_bind_conflict(create_error):
                    return _failure(
                        format_bind_conflict_guidance(template.service_name, template.port, create_error),
                        reason_code=reason_code_to_string(RequirementLifecycleReason.BIND_CONFLICT_UNRESOLVED),
                        failure_class=reason_code_to_string(RequirementLifecycleReason.BIND_CONFLICT_RETRYABLE),
                        stage="start.bind_conflict.unresolved",
                    )
                return _failure(
                    create_error,
                    reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                    stage="start.create.failed",
                )
        else:
            _add_stage_duration("create", start_or_create_started)

    listener_started = time.monotonic()
    listener_ready = wait_for_port_ready(
        template.process_runner,
        effective_port,
        timeout=template.listener_wait_timeout,
    )
    listener_wait_ms += _add_stage_duration("listener_wait", listener_started)
    listener_error = f"probe timeout waiting for readiness on port {effective_port}"
    if not listener_ready:
        if timeout_recovered_create or port_adopted:
            settled, settled_error = _attempt_local_settle(
                listener_ready=False,
                probe_error_text=listener_error,
                stage="probe.retry.timeout_recovered_settle"
                if timeout_recovered_create
                else "probe.retry.adopted_existing_settle",
                success_stage="probe.healthy.after_timeout_recovery"
                if timeout_recovered_create
                else "probe.healthy.after_adopted_existing",
                timeout_suffix="after timeout recovery"
                if timeout_recovered_create
                else "after adopted-existing settle",
            )
            if settled:
                return _run_result(
                    result=ContainerStartResult(
                        success=True,
                        container_name=template.container_name,
                        effective_port=int(effective_port),
                        port_adopted=bool(port_adopted),
                        port_mismatch_requested_port=mismatch_requested_port,
                        port_mismatch_existing_port=mismatch_existing_port,
                        port_mismatch_action=mismatch_action,
                    )
                )
            return _failure(
                settled_error,
                reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
                failure_class=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
                stage="probe.timeout_recovered_create.failed",
            )
        if not template.restart_on_listener_timeout:
            return _failure(
                listener_error,
                reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
                failure_class=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
                stage="probe.listener_timeout",
            )

    probe_error_text = listener_error
    if listener_ready:
        probe_started = time.monotonic()
        ready, probe_error_text = template.probe_readiness(template.probe_attempts)
        _add_stage_duration("probe", probe_started)
        if ready:
            _emit("probe.healthy")
            return _run_result(
                result=ContainerStartResult(
                    success=True,
                    container_name=template.container_name,
                    effective_port=int(effective_port),
                    port_adopted=bool(port_adopted),
                    port_mismatch_requested_port=mismatch_requested_port,
                    port_mismatch_existing_port=mismatch_existing_port,
                    port_mismatch_action=mismatch_action,
                )
            )

    retryable = template.retryable_probe_error(probe_error_text)
    if (timeout_recovered_create or port_adopted) and retryable:
        settled, settled_error = _attempt_local_settle(
            listener_ready=True,
            probe_error_text=probe_error_text,
            stage="probe.retry.timeout_recovered_settle"
            if timeout_recovered_create
            else "probe.retry.adopted_existing_settle",
            success_stage="probe.healthy.after_timeout_recovery"
            if timeout_recovered_create
            else "probe.healthy.after_adopted_existing",
            timeout_suffix="after timeout recovery" if timeout_recovered_create else "after adopted-existing settle",
        )
        if settled:
            return _run_result(
                result=ContainerStartResult(
                    success=True,
                    container_name=template.container_name,
                    effective_port=int(effective_port),
                    port_adopted=bool(port_adopted),
                    port_mismatch_requested_port=mismatch_requested_port,
                    port_mismatch_existing_port=mismatch_existing_port,
                    port_mismatch_action=mismatch_action,
                )
            )
        return _failure(
            settled_error,
            reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
            failure_class=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
            stage="probe.timeout_recovered_create.failed",
        )
    if template.restart_on_probe_failure and retryable:
        _emit(
            "probe.retry.restart",
            reason=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
        )
        restart_started = time.monotonic()
        restart_result, restart_error = run_docker(
            template.process_runner,
            ["restart", template.container_name],
            cwd=template.project_root,
            env=template.env,
            timeout=120.0,
        )
        if restart_result is None:
            _add_stage_duration("restart", restart_started)
            detail = (restart_error or "").strip()
            message = f"failed restarting {template.service_name} container"
            if detail:
                message = f"{message}: {detail}"
            return _failure(
                message,
                reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                stage="probe.retry.restart.failed",
            )
        if getattr(restart_result, "returncode", 1) != 0:
            _add_stage_duration("restart", restart_started)
            detail = run_result_error(restart_result, f"failed restarting {template.service_name} container")
            message = detail
            fallback = f"failed restarting {template.service_name} container"
            if detail != fallback:
                message = f"{fallback}: {detail}"
            return _failure(
                message,
                reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                stage="probe.retry.restart.failed",
            )
        _add_stage_duration("restart", restart_started)
        restart_listener_started = time.monotonic()
        restart_listener_ready = wait_for_port_ready(
            template.process_runner,
            effective_port,
            timeout=template.listener_wait_timeout,
        )
        listener_wait_ms += _add_stage_duration("listener_wait", restart_listener_started)
        if not restart_listener_ready:
            restart_timeout_error = f"probe timeout waiting for readiness on port {effective_port} after restart"
            if not template.recreate_on_restart_listener_timeout:
                return _failure(
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
            _add_stage_duration("probe", restart_probe_started)
            if ready:
                _emit("probe.healthy.after_restart")
                return _run_result(
                    result=ContainerStartResult(
                        success=True,
                        container_name=template.container_name,
                        effective_port=int(effective_port),
                        port_adopted=bool(port_adopted),
                        port_mismatch_requested_port=mismatch_requested_port,
                        port_mismatch_existing_port=mismatch_existing_port,
                        port_mismatch_action=mismatch_action,
                    )
                )
            retryable = template.retryable_probe_error(probe_error_text)

        if template.recreate_on_probe_failure and retryable:
            _emit(
                "probe.retry.recreate",
                reason=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
            )
            container_recreated = True
            recreate_started = time.monotonic()
            cleanup_error = stop_and_remove_container(
                template.process_runner,
                container_name=template.container_name,
                cwd=template.project_root,
                env=template.env,
            )
            if cleanup_error:
                _add_stage_duration("recreate", recreate_started)
                return _failure(
                    f"failed recreating {template.service_name} container: {cleanup_error}",
                    reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                    stage="probe.retry.recreate.cleanup_failed",
                )
            recreate_error = template.create_container()
            if recreate_error:
                if not (timeout_error(recreate_error) and _recover_timeout_created_container(recreate=True)):
                    _add_stage_duration("recreate", recreate_started)
                    return _failure(
                        f"failed recreating {template.service_name} container: {recreate_error}",
                        reason_code=reason_code_to_string(RequirementLifecycleReason.HARD_START_FAILURE),
                        stage="probe.retry.recreate.failed",
                    )
            elif not port_adopted:
                effective_port = int(template.port)
                port_adopted = False
            recreate_listener_started = time.monotonic()
            recreate_listener_ready = wait_for_port_ready(
                template.process_runner,
                effective_port,
                timeout=template.listener_wait_timeout,
            )
            listener_wait_ms += _add_stage_duration("listener_wait", recreate_listener_started)
            if not recreate_listener_ready:
                _add_stage_duration("recreate", recreate_started)
                return _failure(
                    f"probe timeout waiting for readiness on port {effective_port} after recreate",
                    reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
                    failure_class=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
                    stage="probe.retry.recreate.listener_timeout",
                )
            recreate_probe_started = time.monotonic()
            ready, probe_error_text = template.probe_readiness(template.recreate_probe_attempts)
            _add_stage_duration("probe", recreate_probe_started)
            _add_stage_duration("recreate", recreate_started)
            if ready:
                _emit("probe.healthy.after_recreate")
                return _run_result(
                    result=ContainerStartResult(
                        success=True,
                        container_name=template.container_name,
                        effective_port=int(effective_port),
                        port_adopted=bool(port_adopted),
                        port_mismatch_requested_port=mismatch_requested_port,
                        port_mismatch_existing_port=mismatch_existing_port,
                        port_mismatch_action=mismatch_action,
                    )
                )

    return _failure(
        probe_error_text or template.probe_failure_fallback,
        reason_code=reason_code_to_string(RequirementFailureReason.NETWORK_UNREACHABLE),
        failure_class=reason_code_to_string(RequirementLifecycleReason.TRANSIENT_PROBE_TIMEOUT_RETRYABLE),
        stage="probe.failed",
    )


def bind_safe_cleanup_enabled(env: Mapping[str, str] | None, *, service_name: str) -> bool:
    global_default = env_bool(env, "ENVCTL_REQUIREMENT_BIND_SAFE_CLEANUP", False)
    service_key = f"ENVCTL_REQUIREMENT_{service_name.upper()}_BIND_SAFE_CLEANUP"
    return env_bool(env, service_key, global_default)


def cleanup_envctl_owned_port_containers(
    *,
    process_runner: object,
    project_root: Path,
    env: Mapping[str, str] | None,
    port: int,
    allowed_prefixes: tuple[str, ...],
) -> tuple[bool, str | None]:
    result, error = run_docker(
        process_runner,
        ["ps", "-a", "--filter", f"publish={port}", "--format", "{{.Names}}"],
        cwd=project_root,
        env=env,
    )
    if result is None:
        return False, error
    if getattr(result, "returncode", 1) != 0:
        return False, run_result_error(result, "failed listing bind-conflict containers")
    raw = str(getattr(result, "stdout", "") or "")
    candidates = [line.strip() for line in raw.splitlines() if line.strip()]
    removable = sorted({name for name in candidates if any(name.startswith(prefix) for prefix in allowed_prefixes)})
    if not removable:
        return False, None
    for container_name in removable:
        cleanup_error = stop_and_remove_container(
            process_runner,
            container_name=container_name,
            cwd=project_root,
            env=env,
        )
        if cleanup_error:
            return False, cleanup_error
    return True, None


def format_bind_conflict_guidance(service_name: str, port: int, error: str | None) -> str:
    detail = (error or "bind conflict").strip() or "bind conflict"
    return (
        f"{detail}. Unable to acquire port {port} for {service_name}. "
        "Resolve the conflict manually or run with ENVCTL_REQUIREMENT_BIND_SAFE_CLEANUP=true "
        "to allow safe cleanup of envctl-owned stale containers, then retry."
    )


def wait_for_port_ready(process_runner: object, port: int, *, timeout: float) -> bool:
    waiter = getattr(process_runner, "wait_for_port", None)
    if not callable(waiter):
        return False
    try:
        return bool(waiter(port, timeout=timeout))
    except TypeError:
        return bool(waiter(port))
