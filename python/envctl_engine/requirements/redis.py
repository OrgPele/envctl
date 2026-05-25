from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from pathlib import Path

from envctl_engine.shared.protocols import ProcessRuntime

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
from .adapter_lifecycle_models import project_container_lifecycle_result
from .common_contracts import (
    ContainerStartResult,
    RetryResult,
    build_container_name,
    run_with_retry,
)
from .container_state_support import container_exists, container_status
from .docker_image_support import ensure_docker_image_present
from .docker_runtime import (
    docker_port_publish_lock,
    run_docker,
    run_result_error,
)


def start_redis_with_retry(
    start,
    reserve_next,
    port: int,
    max_retries: int = 3,  # noqa: ANN001
) -> RetryResult:
    return run_with_retry(initial_port=port, start=start, reserve_next=reserve_next, max_retries=max_retries)


def start_redis_container(
    *,
    process_runner: ProcessRuntime,
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

    bind_cleanup: Callable[[int], tuple[bool, str | None]] | None = None
    if bind_safe_cleanup_enabled(env, service_name="redis"):

        def _bind_cleanup(bound_port: int) -> tuple[bool, str | None]:
            return cleanup_envctl_owned_port_containers(
                process_runner=process_runner,
                project_root=project_root,
                env=env,
                port=bound_port,
                allowed_prefixes=("envctl-redis-",),
            )

        bind_cleanup = _bind_cleanup

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
    return project_container_lifecycle_result(lifecycle_run)


def _probe_redis_readiness(
    *,
    process_runner: ProcessRuntime,
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
    process_runner: ProcessRuntime,
    project_root: Path,
    container_name: str,
    port: int,
    env: Mapping[str, str] | None,
    image: str,
) -> str | None:
    image_error = ensure_docker_image_present(
        process_runner,
        image=image,
        cwd=project_root,
        env=env,
        pull_policy_key="ENVCTL_REDIS_PULL_POLICY",
        legacy_bool_key="ENVCTL_REDIS_PULL_IMAGE",
        inspect_timeout=env_float(env, "ENVCTL_REDIS_IMAGE_INSPECT_TIMEOUT_SECONDS", 10.0, minimum=1.0),
        pull_timeout=env_float(env, "ENVCTL_REDIS_PULL_TIMEOUT_SECONDS", 300.0, minimum=30.0),
    )
    if image_error is not None:
        return image_error
    return _create_redis_container_locked(
        process_runner=process_runner,
        project_root=project_root,
        container_name=container_name,
        port=port,
        env=env,
        image=image,
    )


def _create_redis_container_locked(
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
        "ENVCTL_REDIS_CREATE_TIMEOUT_SECONDS",
        20.0,
        minimum=5.0,
    )
    with docker_port_publish_lock(env):
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
            container_name=container_name,
            project_root=project_root,
            env=env,
            port=port,
            timeout_seconds=env_float(env, "ENVCTL_REDIS_START_RECOVERY_TIMEOUT_SECONDS", 18.0, minimum=1.0),
        ):
            return None
        return (
            f"probe timeout waiting for readiness on port {port} after docker start timeout"
            + (f": {start_error}" if start_error else "")
        )
    if start_result is None:
        if _recover_redis_start_timeout(
            process_runner=process_runner,
            container_name=container_name,
            project_root=project_root,
            env=env,
            port=port,
            timeout_seconds=env_float(env, "ENVCTL_REDIS_START_RECOVERY_TIMEOUT_SECONDS", 18.0, minimum=1.0),
        ):
            return None
        return (
            f"probe timeout waiting for readiness on port {port} after docker start failure"
            + (f": {start_error}" if start_error else "")
        )
    if getattr(start_result, "returncode", 1) != 0:
        if _recover_redis_start_timeout(
            process_runner=process_runner,
            container_name=container_name,
            project_root=project_root,
            env=env,
            port=port,
            timeout_seconds=env_float(env, "ENVCTL_REDIS_START_RECOVERY_TIMEOUT_SECONDS", 18.0, minimum=1.0),
        ):
            return None
        detail = run_result_error(start_result, "failed starting redis container")
        return f"probe timeout waiting for readiness on port {port} after docker start failure: {detail}"
    if create_timed_out and not _recover_redis_start_timeout(
        process_runner=process_runner,
        container_name=container_name,
        project_root=project_root,
        env=env,
        port=port,
        timeout_seconds=env_float(env, "ENVCTL_REDIS_START_RECOVERY_TIMEOUT_SECONDS", 18.0, minimum=1.0),
    ):
        return "probe timeout waiting for readiness on port {port} after timeout recovery".format(port=port)
    return None


def _recover_redis_start_timeout(
    *,
    process_runner,
    container_name: str,
    project_root: Path,
    env: Mapping[str, str] | None,
    port: int,
    timeout_seconds: float,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if bool(process_runner.wait_for_port(port, timeout=1.0)):
            return True
        status, _status_error = container_status(
            process_runner,
            container_name=container_name,
            cwd=project_root,
            env=env,
        )
        if status == "running" and bool(process_runner.wait_for_port(port, timeout=1.0)):
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
