from __future__ import annotations

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
    run_docker,
    run_result_error,
    run_with_retry,
)


def start_postgres_with_retry(start, reserve_next, port: int, max_retries: int = 3) -> RetryResult:
    return run_with_retry(initial_port=port, start=start, reserve_next=reserve_next, max_retries=max_retries)


def start_postgres_container(
    *,
    process_runner,
    project_root: Path,
    project_name: str,
    port: int,
    db_user: str,
    db_password: str,
    db_name: str,
    env: Mapping[str, str] | None = None,
    image: str = "postgres:15-alpine",
) -> ContainerStartResult:
    container_name = build_container_name(
        prefix="envctl-postgres",
        project_root=project_root,
        project_name=project_name,
    )
    max_probe_attempts = env_int(env, "ENVCTL_POSTGRES_PROBE_ATTEMPTS", 60, minimum=1)
    listener_wait_timeout = env_float(
        env,
        "ENVCTL_POSTGRES_LISTENER_WAIT_TIMEOUT_SECONDS",
        20.0,
        minimum=1.0,
    )
    restart_on_probe_failure = _restart_on_probe_failure_enabled(env)
    recreate_on_probe_failure = _recreate_on_probe_failure_enabled(env)
    restart_probe_attempts = env_int(
        env,
        "ENVCTL_POSTGRES_RESTART_PROBE_ATTEMPTS",
        min(max(10, max_probe_attempts // 2), max_probe_attempts),
        minimum=1,
    )
    recreate_probe_attempts = env_int(
        env,
        "ENVCTL_POSTGRES_RECREATE_PROBE_ATTEMPTS",
        restart_probe_attempts,
        minimum=1,
    )

    bind_cleanup = None
    if bind_safe_cleanup_enabled(env, service_name="postgres"):

        def bind_cleanup(bound_port: int) -> None:
            cleanup_envctl_owned_port_containers(
                process_runner=process_runner,
                project_root=project_root,
                env=env,
                port=bound_port,
                allowed_prefixes=("envctl-postgres-",),
            )

    lifecycle = ContainerLifecycleTemplate(
        service_name="postgres",
        container_name=container_name,
        process_runner=process_runner,
        project_root=project_root,
        env=env,
        port=port,
        container_port=5432,
        listener_wait_timeout=listener_wait_timeout,
        probe_attempts=max_probe_attempts,
        restart_probe_attempts=restart_probe_attempts,
        recreate_probe_attempts=recreate_probe_attempts,
        restart_on_probe_failure=restart_on_probe_failure,
        recreate_on_probe_failure=recreate_on_probe_failure,
        retryable_probe_error=_is_retryable_probe_error,
        create_container=lambda: _create_postgres_container(
            process_runner=process_runner,
            project_root=project_root,
            container_name=container_name,
            port=port,
            db_user=db_user,
            db_password=db_password,
            db_name=db_name,
            env=env,
            image=image,
        ),
        probe_readiness=lambda attempts: _probe_postgres_readiness(
            process_runner=process_runner,
            container_name=container_name,
            project_root=project_root,
            env=env,
            db_user=db_user,
            db_name=db_name,
            max_probe_attempts=attempts,
        ),
        probe_failure_fallback="postgres readiness probe failed",
        restart_on_listener_timeout=env_bool(
            env,
            "ENVCTL_POSTGRES_RESTART_ON_LISTENER_TIMEOUT",
            restart_on_probe_failure,
        ),
        recreate_on_restart_listener_timeout=env_bool(
            env,
            "ENVCTL_POSTGRES_RECREATE_ON_RESTART_LISTENER_TIMEOUT",
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


def _create_postgres_container(
    *,
    process_runner,
    project_root: Path,
    container_name: str,
    port: int,
    db_user: str,
    db_password: str,
    db_name: str,
    env: Mapping[str, str] | None,
    image: str,
) -> str | None:
    create_timeout_seconds = env_float(
        env,
        "ENVCTL_POSTGRES_CREATE_TIMEOUT_SECONDS",
        25.0,
        minimum=5.0,
    )
    run_result, run_error = run_docker(
        process_runner,
        [
            "run",
            "-d",
            "--name",
            container_name,
            "-e",
            f"POSTGRES_USER={db_user}",
            "-e",
            f"POSTGRES_PASSWORD={db_password}",
            "-e",
            f"POSTGRES_DB={db_name}",
            "-p",
            f"{port}:5432",
            image,
        ],
        cwd=project_root,
        env=env,
        timeout=create_timeout_seconds,
    )
    if run_result is None:
        return run_error
    if getattr(run_result, "returncode", 1) != 0:
        return run_result_error(run_result, "failed creating postgres container")
    return None


def _probe_postgres_readiness(
    *,
    process_runner,
    container_name: str,
    project_root: Path,
    env: Mapping[str, str] | None,
    db_user: str,
    db_name: str,
    max_probe_attempts: int,
) -> tuple[bool, str | None]:
    probe_error_text: str | None = None
    for attempt in range(max_probe_attempts):
        probe_result, probe_error = run_docker(
            process_runner,
            [
                "exec",
                container_name,
                "pg_isready",
                "-h",
                "127.0.0.1",
                "-p",
                "5432",
                "-U",
                db_user,
                "-d",
                db_name,
            ],
            cwd=project_root,
            env=env,
            timeout=30.0,
        )
        if probe_result is None:
            return False, probe_error
        if getattr(probe_result, "returncode", 1) == 0:
            return True, None
        probe_error_text = run_result_error(probe_result, "postgres readiness probe failed")
        if attempt < max_probe_attempts - 1:
            backoff_seconds = min(0.25 * (attempt + 1), 1.5)
            sleep_between_probes(process_runner, backoff_seconds)
    return False, probe_error_text or "postgres readiness probe failed"


def _restart_on_probe_failure_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_POSTGRES_RESTART_ON_PROBE_FAILURE", True)


def _is_retryable_probe_error(error: str | None) -> bool:
    return retryable_probe_error(
        error,
        (
            "no response",
            "timeout",
            "timed out",
            "connection refused",
            "temporarily unavailable",
        ),
    )


def _recreate_on_probe_failure_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_POSTGRES_RECREATE_ON_PROBE_FAILURE", True)
