from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path

from envctl_engine.shared.protocols import ProcessRuntime

from .adapter_base import (
    ContainerLifecycleTemplate,
    env_bool,
    env_float,
    retryable_probe_error,
    run_container_lifecycle,
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


def start_n8n_with_retry(
    start,
    reserve_next,
    port: int,
    max_retries: int = 3,  # noqa: ANN001
) -> RetryResult:
    return run_with_retry(initial_port=port, start=start, reserve_next=reserve_next, max_retries=max_retries)


def start_n8n_container(
    *,
    process_runner: ProcessRuntime,
    project_root: Path,
    project_name: str,
    port: int,
    env: Mapping[str, str] | None = None,
    image: str = "n8nio/n8n:latest",
) -> ContainerStartResult:
    container_name = build_container_name(
        prefix="envctl-n8n",
        project_root=project_root,
        project_name=project_name,
    )
    probe_timeout_seconds = _n8n_probe_timeout_seconds(env)
    lifecycle = ContainerLifecycleTemplate(
        service_name="n8n",
        container_name=container_name,
        process_runner=process_runner,
        project_root=project_root,
        env=env,
        port=port,
        container_port=5678,
        listener_wait_timeout=probe_timeout_seconds,
        probe_attempts=1,
        restart_probe_attempts=1,
        recreate_probe_attempts=1,
        restart_on_probe_failure=_restart_on_probe_failure_enabled(env),
        recreate_on_probe_failure=_recreate_on_probe_failure_enabled(env),
        retryable_probe_error=_is_retryable_probe_error,
        create_container=lambda: _create_n8n_container(
            process_runner=process_runner,
            project_root=project_root,
            container_name=container_name,
            port=port,
            env=env,
            image=image,
        ),
        probe_readiness=lambda _attempts: (True, None),
        probe_failure_fallback=f"probe timeout waiting for readiness on port {port}",
        restart_on_listener_timeout=True,
        recreate_on_restart_listener_timeout=True,
    )
    lifecycle_run = run_container_lifecycle(lifecycle)
    result = lifecycle_run.result
    result.stage_events = [event.to_payload() for event in lifecycle_run.events]
    result.stage_durations_ms = dict(lifecycle_run.stage_durations_ms)
    result.listener_wait_ms = float(lifecycle_run.listener_wait_ms)
    result.container_reused = bool(lifecycle_run.container_reused)
    result.container_recreated = bool(lifecycle_run.container_recreated)
    return result


def _create_n8n_container(
    *,
    process_runner: ProcessRuntime,
    project_root: Path,
    container_name: str,
    port: int,
    env: Mapping[str, str] | None,
    image: str,
) -> str | None:
    create_timeout_seconds = env_float(
        env,
        "ENVCTL_N8N_CREATE_TIMEOUT_SECONDS",
        30.0,
        minimum=5.0,
    )
    create_result, create_error = run_docker(
        process_runner,
        [
            "create",
            "--name",
            container_name,
            "-e",
            "N8N_HOST=localhost",
            "-e",
            "N8N_PORT=5678",
            "-e",
            "N8N_PROTOCOL=http",
            "-p",
            f"{port}:5678",
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
            return create_error or "failed creating n8n container"
    elif create_result is None:
        return create_error
    elif getattr(create_result, "returncode", 1) != 0:
        return run_result_error(create_result, "failed creating n8n container")

    start_result, start_error = run_docker(
        process_runner,
        ["start", container_name],
        cwd=project_root,
        env=env,
        timeout=env_float(env, "ENVCTL_N8N_START_TIMEOUT_SECONDS", 8.0, minimum=1.0),
    )
    start_timed_out = (start_result is None and "timed out" in (start_error or "").lower()) or (
        start_result is not None and getattr(start_result, "returncode", 1) == 124
    )
    if start_timed_out:
        if _recover_n8n_start_timeout(
            process_runner=process_runner,
            port=port,
            timeout_seconds=env_float(env, "ENVCTL_N8N_START_RECOVERY_TIMEOUT_SECONDS", 18.0, minimum=1.0),
        ):
            return None
        return start_error or "failed starting n8n container"
    if start_result is None:
        return start_error
    if getattr(start_result, "returncode", 1) != 0:
        return run_result_error(start_result, "failed starting n8n container")
    if create_timed_out and not _recover_n8n_start_timeout(
        process_runner=process_runner,
        port=port,
        timeout_seconds=env_float(env, "ENVCTL_N8N_START_RECOVERY_TIMEOUT_SECONDS", 18.0, minimum=1.0),
    ):
        return "probe timeout waiting for readiness on port {port} after timeout recovery".format(port=port)
    return None


def _recover_n8n_start_timeout(
    *,
    process_runner: ProcessRuntime,
    port: int,
    timeout_seconds: float,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if bool(process_runner.wait_for_port(port, timeout=1.0)):
            return True
        time.sleep(1.0)
    return False


def _n8n_probe_timeout_seconds(env: Mapping[str, str] | None) -> float:
    parsed = env_float(env, "ENVCTL_N8N_PROBE_TIMEOUT_SECONDS", 6.0)
    if parsed <= 0:
        return 12.0
    return parsed


def _restart_on_probe_failure_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_N8N_RESTART_ON_PROBE_FAILURE", True)


def _recreate_on_probe_failure_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_N8N_RECREATE_ON_PROBE_FAILURE", True)


def _is_retryable_probe_error(error: str | None) -> bool:
    return retryable_probe_error(
        error,
        (
            "timeout",
            "timed out",
            "no response",
            "connection refused",
            "temporarily unavailable",
        ),
    )
