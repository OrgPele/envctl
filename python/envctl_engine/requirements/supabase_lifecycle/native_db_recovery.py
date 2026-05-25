from __future__ import annotations

from collections.abc import Mapping
import json
import time
from pathlib import Path

from envctl_engine.requirements.adapter_base import env_float, timeout_error
from envctl_engine.requirements.common import (
    container_exists,
    container_status,
    is_bind_conflict,
    run_docker,
    run_result_error,
)


def recover_native_db_start_timeout(
    *,
    process_runner,
    container_name: str,
    port: int,
    cwd: Path,
    env: Mapping[str, str] | None,
    listener_wait_timeout: float,
) -> tuple[bool, str | None]:
    recovery_deadline = time.monotonic() + native_db_start_recovery_timeout_seconds(env)
    while time.monotonic() < recovery_deadline:
        recovered, recovery_error = _probe_started_container(
            process_runner=process_runner,
            container_name=container_name,
            cwd=cwd,
            env=env,
            listener_wait_timeout=listener_wait_timeout,
        )
        if recovered or recovery_error is not None:
            return recovered, recovery_error
        _sleep(process_runner, 1.0)

    status, status_error = container_status(process_runner, container_name=container_name, cwd=cwd, env=env)
    if status_error is None and status == "running":
        published_port = native_db_published_port(process_runner, container_name=container_name, cwd=cwd, env=env)
        if published_port is None:
            return False, f"published host port missing for port {port}"
        if bool(process_runner.wait_for_port(published_port, timeout=min(listener_wait_timeout, 1.0))):
            return True, None
        return False, f"probe timeout waiting for readiness on port {published_port}"

    state_error = native_db_state_error(process_runner, container_name=container_name, cwd=cwd, env=env)
    if is_bind_conflict(state_error):
        return False, state_error
    return False, None


def recover_native_db_create_timeout(
    *,
    process_runner,
    container_name: str,
    cwd: Path,
    env: Mapping[str, str] | None,
) -> bool:
    for _ in range(5):
        exists, exists_error = container_exists(
            process_runner,
            container_name=container_name,
            cwd=cwd,
            env=env,
        )
        if exists_error is None and exists:
            return True
        _sleep(process_runner, 1.0)
    return False


def native_db_start_timeout_seconds(env: Mapping[str, str] | None) -> float:
    parsed = env_float(env, "ENVCTL_SUPABASE_DB_START_TIMEOUT_SECONDS", 8.0, minimum=1.0)
    if parsed <= 0:
        return 8.0
    return parsed


def native_db_timeout_error_for_retry(
    *,
    port: int,
    start_error: str | None,
    recovery_error: str | None,
) -> str:
    if recovery_error:
        return recovery_error
    if timeout_error(start_error):
        return f"host port binding incomplete for port {port} after docker start timeout"
    return start_error or "failed starting supabase db container"


def force_remove_native_db_container(
    *,
    process_runner,
    container_name: str,
    cwd: Path,
    env: Mapping[str, str] | None,
) -> str | None:
    rm_result, rm_error = run_docker(
        process_runner,
        ["rm", "-f", container_name],
        cwd=cwd,
        env=env,
        timeout=10.0,
    )
    if rm_result is None:
        return rm_error
    if getattr(rm_result, "returncode", 1) != 0:
        return run_result_error(rm_result, "failed removing supabase db container")
    return None


def _probe_started_container(
    *,
    process_runner,
    container_name: str,
    cwd: Path,
    env: Mapping[str, str] | None,
    listener_wait_timeout: float,
) -> tuple[bool, str | None]:
    status, status_error = container_status(process_runner, container_name=container_name, cwd=cwd, env=env)
    if status_error is None and status == "running":
        published_port = native_db_published_port(process_runner, container_name=container_name, cwd=cwd, env=env)
        if published_port is not None and bool(
            process_runner.wait_for_port(published_port, timeout=min(listener_wait_timeout, 1.0))
        ):
            return True, None
    state_error = native_db_state_error(process_runner, container_name=container_name, cwd=cwd, env=env)
    if is_bind_conflict(state_error):
        return False, state_error
    return False, None


def native_db_start_recovery_timeout_seconds(env: Mapping[str, str] | None) -> float:
    parsed = env_float(env, "ENVCTL_SUPABASE_DB_START_RECOVERY_TIMEOUT_SECONDS", 18.0, minimum=1.0)
    if parsed <= 0:
        return 18.0
    return parsed


def native_db_state_error(
    process_runner,
    *,
    container_name: str,
    cwd: Path,
    env: Mapping[str, str] | None,
) -> str | None:
    result, error = run_docker(
        process_runner,
        ["inspect", "-f", "{{.State.Error}}", container_name],
        cwd=cwd,
        env=env,
        timeout=10.0,
    )
    if result is None or getattr(result, "returncode", 1) != 0:
        return error
    value = str(getattr(result, "stdout", "") or "").strip()
    return value or None


def native_db_published_port(
    process_runner,
    *,
    container_name: str,
    cwd: Path,
    env: Mapping[str, str] | None,
) -> int | None:
    result, _error = run_docker(
        process_runner,
        ["inspect", "-f", "{{json .NetworkSettings.Ports}}", container_name],
        cwd=cwd,
        env=env,
        timeout=10.0,
    )
    if result is None or getattr(result, "returncode", 1) != 0:
        return None
    return _host_port_from_network_settings(str(getattr(result, "stdout", "") or "").strip())


def _host_port_from_network_settings(payload: str) -> int | None:
    if not payload:
        return None
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    binding = decoded.get("5432/tcp")
    if not isinstance(binding, list) or not binding:
        return None
    first = binding[0]
    if not isinstance(first, dict):
        return None
    raw_port = str(first.get("HostPort", "")).strip()
    if not raw_port:
        return None
    try:
        return int(raw_port)
    except ValueError:
        return None


def _sleep(process_runner, seconds: float) -> None:
    sleeper = getattr(process_runner, "sleep", None)
    if callable(sleeper):
        sleeper(seconds)
    else:
        time.sleep(seconds)
