from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path

from .adapter_base import (
    ContainerLifecycleTemplate,
    bind_safe_cleanup_enabled,
    cleanup_envctl_owned_port_containers,
    env_bool,
    env_float,
    env_int,
    retryable_probe_error,
    run_container_lifecycle,
    sleep_between_probes,
)
from .common import (
    ContainerStartResult,
    RetryResult,
    build_container_name,
    container_exists,
    run_docker,
    run_result_error,
    run_with_retry,
)


def start_redis_with_retry(start, reserve_next, port: int, max_retries: int = 3) -> RetryResult:
    return run_with_retry(initial_port=port, start=start, reserve_next=reserve_next, max_retries=max_retries)


def start_redis_container(
    *,
    process_runner,
    project_root: Path,
    project_name: str,
    port: int,
    env: Mapping[str, str] | None = None,
    image: str = "redis:7-alpine",
) -> ContainerStartResult:
    container_name = build_container_name(
        prefix="envctl-redis",
        project_root=project_root,
        project_name=project_name,
    )
    max_probe_attempts = env_int(env, "ENVCTL_REDIS_PROBE_ATTEMPTS", 20, minimum=1)
    listener_wait_timeout = env_float(
        env,
        "ENVCTL_REDIS_LISTENER_WAIT_TIMEOUT_SECONDS",
        5.0,
        minimum=1.0,
    )
    restart_on_probe_failure = _restart_on_probe_failure_enabled(env)
    recreate_on_probe_failure = _recreate_on_probe_failure_enabled(env)
    restart_probe_attempts = env_int(
        env,
        "ENVCTL_REDIS_RESTART_PROBE_ATTEMPTS",
        max_probe_attempts,
        minimum=1,
    )
    recreate_probe_attempts = env_int(
        env,
        "ENVCTL_REDIS_RECREATE_PROBE_ATTEMPTS",
        max_probe_attempts,
        minimum=1,
    )

    bind_cleanup = None
    if bind_safe_cleanup_enabled(env, service_name="redis"):

        def bind_cleanup(bound_port: int) -> None:
            cleanup_envctl_owned_port_containers(
                process_runner=process_runner,
                project_root=project_root,
                env=env,
                port=bound_port,
                allowed_prefixes=("envctl-redis-",),
            )

    lifecycle = ContainerLifecycleTemplate(
        service_name="redis",
        container_name=container_name,
        process_runner=process_runner,
        project_root=project_root,
        env=env,
        port=port,
        container_port=6379,
        listener_wait_timeout=listener_wait_timeout,
        probe_attempts=max_probe_attempts,
        restart_probe_attempts=restart_probe_attempts,
        recreate_probe_attempts=recreate_probe_attempts,
        restart_on_probe_failure=restart_on_probe_failure,
        recreate_on_probe_failure=recreate_on_probe_failure,
        retryable_probe_error=_is_retryable_probe_error,
        create_container=lambda: _create_redis_container(
            process_runner=process_runner,
            project_root=project_root,
            container_name=container_name,
            port=port,
            env=env,
            image=image,
        ),
        probe_readiness=lambda attempts: _probe_redis_readiness(
            process_runner=process_runner,
            container_name=container_name,
            project_root=project_root,
            env=env,
            max_probe_attempts=attempts,
        ),
        probe_failure_fallback="redis-cli ping failed",
        restart_on_listener_timeout=env_bool(
            env,
            "ENVCTL_REDIS_RESTART_ON_LISTENER_TIMEOUT",
            restart_on_probe_failure,
        ),
        recreate_on_restart_listener_timeout=env_bool(
            env,
            "ENVCTL_REDIS_RECREATE_ON_RESTART_LISTENER_TIMEOUT",
            recreate_on_probe_failure,
        ),
        bind_cleanup=bind_cleanup,
    )
    lifecycle_run = run_container_lifecycle(lifecycle)
    result = lifecycle_run.result
    result.stage_events = [event.to_payload() for event in lifecycle_run.events]
    result.stage_durations_ms = dict(lifecycle_run.stage_durations_ms)
    result.listener_wait_ms = float(lifecycle_run.listener_wait_ms)
    result.container_reused = bool(lifecycle_run.container_reused)
    result.container_recreated = bool(lifecycle_run.container_recreated)
    return result


def _probe_redis_readiness(
    *,
    process_runner,
    container_name: str,
    project_root: Path,
    env: Mapping[str, str] | None,
    max_probe_attempts: int,
) -> tuple[bool, str | None]:
    probe_error_text: str | None = None
    for attempt in range(max_probe_attempts):
        probe_result, probe_error = run_docker(
            process_runner,
            ["exec", container_name, "redis-cli", "ping"],
            cwd=project_root,
            env=env,
            timeout=30.0,
        )
        if probe_result is None:
            return False, probe_error
        if getattr(probe_result, "returncode", 1) == 0:
            return True, None
        probe_error_text = f"redis-cli ping failed: {run_result_error(probe_result, 'redis probe failed')}"
        if attempt < max_probe_attempts - 1:
            backoff_seconds = min(0.25 * (attempt + 1), 1.0)
            sleep_between_probes(process_runner, backoff_seconds)
    return False, probe_error_text or "redis-cli ping failed"


def _create_redis_container(
    *,
    process_runner,
    project_root: Path,
    container_name: str,
    port: int,
    env: Mapping[str, str] | None,
    image: str,
) -> str | None:
    create_timeout_seconds = env_float(
        env,
        "ENVCTL_REDIS_CREATE_TIMEOUT_SECONDS",
        20.0,
        minimum=5.0,
    )
    create_result, create_error = run_docker(
        process_runner,
        [
            "create",
            "--name",
            container_name,
            "-p",
            f"{port}:6379",
            image,
        ],
        cwd=project_root,
        env=env,
        timeout=create_timeout_seconds,
    )
    create_timed_out = (create_result is None and "timed out" in (create_error or "").lower()) or (
        create_result is not None and getattr(create_result, "returncode", 1) == 124
    )
    if create_timed_out:
        exists, exists_error = container_exists(
            process_runner,
            container_name=container_name,
            cwd=project_root,
            env=env,
        )
        if exists_error or not exists:
            return create_error or "failed creating redis container"
    elif create_result is None:
        return create_error
    elif getattr(create_result, "returncode", 1) != 0:
        return run_result_error(create_result, "failed creating redis container")

    start_result, start_error = run_docker(
        process_runner,
        ["start", container_name],
        cwd=project_root,
        env=env,
        timeout=env_float(env, "ENVCTL_REDIS_START_TIMEOUT_SECONDS", 8.0, minimum=1.0),
    )
    start_timed_out = (start_result is None and "timed out" in (start_error or "").lower()) or (
        start_result is not None and getattr(start_result, "returncode", 1) == 124
    )
    if start_timed_out:
        if _recover_redis_start_timeout(
            process_runner=process_runner,
            port=port,
            timeout_seconds=env_float(env, "ENVCTL_REDIS_START_RECOVERY_TIMEOUT_SECONDS", 18.0, minimum=1.0),
        ):
            return None
        return start_error or "failed starting redis container"
    if start_result is None:
        return start_error
    if getattr(start_result, "returncode", 1) != 0:
        return run_result_error(start_result, "failed starting redis container")
    if create_timed_out and not _recover_redis_start_timeout(
        process_runner=process_runner,
        port=port,
        timeout_seconds=env_float(env, "ENVCTL_REDIS_START_RECOVERY_TIMEOUT_SECONDS", 18.0, minimum=1.0),
    ):
        return "probe timeout waiting for readiness on port {port} after timeout recovery".format(port=port)
    return None


def _recover_redis_start_timeout(
    *,
    process_runner,
    port: int,
    timeout_seconds: float,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if bool(process_runner.wait_for_port(port, timeout=1.0)):
            return True
        sleep_between_probes(process_runner, 1.0)
    return False


def _restart_on_probe_failure_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_REDIS_RESTART_ON_PROBE_FAILURE", True)


def _recreate_on_probe_failure_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_REDIS_RECREATE_ON_PROBE_FAILURE", True)


def _is_retryable_probe_error(error: str | None) -> bool:
    return retryable_probe_error(
        error,
        (
            "loading",
            "no response",
            "timeout",
            "timed out",
            "connection refused",
            "temporarily unavailable",
        ),
    )
