from __future__ import annotations

from collections.abc import Mapping
import json
import time
from pathlib import Path

from ..adapter_base import env_float, port_mismatch_policy, timeout_error
from ..common import (
    ContainerStartResult,
    container_exists,
    container_host_port,
    container_status,
    ensure_docker_image_present,
    is_bind_conflict,
    run_docker,
    run_result_error,
)
from .config import _db_probe_timeout_seconds
from envctl_engine.shared.dependency_compose_assets import (
    DEFAULT_SUPABASE_JWT_SECRET,
    default_supabase_anon_key,
    default_supabase_service_role_key,
)


def _start_supabase_db_native(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    project_root: Path,
    db_port: int,
    env: Mapping[str, str] | None,
) -> ContainerStartResult:
    container_name = f"{compose_project_name}-supabase-db-1"
    create_timeout_seconds = env_float(
        env,
        "ENVCTL_SUPABASE_DB_CREATE_TIMEOUT_SECONDS",
        25.0,
        minimum=5.0,
    )
    start_timeout_seconds = _native_db_start_timeout_seconds(env)
    listener_wait_timeout = _db_probe_timeout_seconds(env)
    volume_name = f"{compose_project_name}_supabase_db_data"
    image = (env or {}).get("SUPABASE_DB_IMAGE") or "supabase/postgres:15.1.0.147"

    existing, existing_error = container_exists(
        process_runner,
        container_name=container_name,
        cwd=project_root,
        env=env,
    )
    if existing_error:
        return ContainerStartResult(success=False, container_name=container_name, error=existing_error)

    if existing:
        mapped_port, port_error = container_host_port(
            process_runner,
            container_name=container_name,
            container_port=5432,
            cwd=project_root,
            env=env,
        )
        if port_error:
            return ContainerStartResult(success=False, container_name=container_name, error=port_error)
        status, status_error = container_status(
            process_runner,
            container_name=container_name,
            cwd=project_root,
            env=env,
        )
        if status_error:
            return ContainerStartResult(success=False, container_name=container_name, error=status_error)
        if mapped_port is None:
            if existing:
                remove_error = _force_remove_native_db_container(
                    process_runner=process_runner,
                    container_name=container_name,
                    cwd=project_root,
                    env=env,
                )
                if remove_error is not None:
                    return ContainerStartResult(success=False, container_name=container_name, error=remove_error)
                existing = False
        if mapped_port is not None and mapped_port != db_port:
            if port_mismatch_policy(env) == "adopt_existing":
                if status != "running":
                    start_result, start_error = run_docker(
                        process_runner,
                        ["start", container_name],
                        cwd=project_root,
                        env=env,
                        timeout=start_timeout_seconds,
                    )
                    recovered = False
                    recovery_error = None
                    start_timed_out = (start_result is None and timeout_error(start_error)) or (
                        start_result is not None and getattr(start_result, "returncode", 1) == 124
                    )
                    if start_timed_out:
                        recovered, recovery_error = _recover_native_db_start_timeout(
                            process_runner=process_runner,
                            container_name=container_name,
                            port=mapped_port,
                            cwd=project_root,
                            env=env,
                            listener_wait_timeout=listener_wait_timeout,
                        )
                    if (start_result is None or start_timed_out) and not recovered:
                        return ContainerStartResult(
                            success=False,
                            container_name=container_name,
                            error=_native_db_timeout_error_for_retry(
                                port=mapped_port,
                                start_error=start_error
                                or (
                                    run_result_error(start_result, "failed starting supabase db container")
                                    if start_result is not None
                                    else None
                                ),
                                recovery_error=recovery_error,
                            ),
                        )
                    if start_result is not None and getattr(start_result, "returncode", 1) != 0:
                        return ContainerStartResult(
                            success=False,
                            container_name=container_name,
                            error=run_result_error(start_result, "failed starting supabase db container"),
                        )
                if bool(process_runner.wait_for_port(mapped_port, timeout=listener_wait_timeout)):
                    return ContainerStartResult(
                        success=True,
                        container_name=container_name,
                        effective_port=mapped_port,
                        port_adopted=True,
                        container_reused=True,
                    )
                remove_error = _force_remove_native_db_container(
                    process_runner=process_runner,
                    container_name=container_name,
                    cwd=project_root,
                    env=env,
                )
                if remove_error is not None:
                    return ContainerStartResult(
                        success=False,
                        container_name=container_name,
                        error=f"probe timeout waiting for readiness on port {mapped_port}; {remove_error}",
                    )
                existing = False
            remove_error = _force_remove_native_db_container(
                process_runner=process_runner,
                container_name=container_name,
                cwd=project_root,
                env=env,
            )
            if remove_error is not None:
                return ContainerStartResult(success=False, container_name=container_name, error=remove_error)
            existing = False
        elif existing:
            if status != "running":
                start_result, start_error = run_docker(
                    process_runner,
                    ["start", container_name],
                    cwd=project_root,
                    env=env,
                    timeout=start_timeout_seconds,
                )
                recovered = False
                recovery_error = None
                start_timed_out = (start_result is None and timeout_error(start_error)) or (
                    start_result is not None and getattr(start_result, "returncode", 1) == 124
                )
                if start_timed_out:
                    recovered, recovery_error = _recover_native_db_start_timeout(
                        process_runner=process_runner,
                        container_name=container_name,
                        port=db_port,
                        cwd=project_root,
                        env=env,
                        listener_wait_timeout=listener_wait_timeout,
                    )
                if (start_result is None or start_timed_out) and not recovered:
                    return ContainerStartResult(
                        success=False,
                        container_name=container_name,
                        error=_native_db_timeout_error_for_retry(
                            port=db_port,
                            start_error=start_error
                            or (
                                run_result_error(start_result, "failed starting supabase db container")
                                if start_result is not None
                                else None
                            ),
                            recovery_error=recovery_error,
                        ),
                    )
                if start_result is not None and getattr(start_result, "returncode", 1) != 0:
                    return ContainerStartResult(
                        success=False,
                        container_name=container_name,
                        error=run_result_error(start_result, "failed starting supabase db container"),
                    )
            if bool(process_runner.wait_for_port(db_port, timeout=listener_wait_timeout)):
                return ContainerStartResult(
                    success=True,
                    container_name=container_name,
                    effective_port=db_port,
                    container_reused=True,
                )
            remove_error = _force_remove_native_db_container(
                process_runner=process_runner,
                container_name=container_name,
                cwd=project_root,
                env=env,
            )
            if remove_error is not None:
                return ContainerStartResult(
                    success=False,
                    container_name=container_name,
                    error=f"probe timeout waiting for readiness on port {db_port}; {remove_error}",
                )

    image_error = ensure_docker_image_present(
        process_runner,
        image=image,
        cwd=project_root,
        env=env,
        pull_policy_key="ENVCTL_SUPABASE_DB_PULL_POLICY",
        legacy_bool_key="ENVCTL_SUPABASE_DB_PULL_IMAGE",
        inspect_timeout=env_float(env, "ENVCTL_SUPABASE_DB_IMAGE_INSPECT_TIMEOUT_SECONDS", 10.0, minimum=1.0),
        pull_timeout=env_float(env, "ENVCTL_SUPABASE_DB_PULL_TIMEOUT_SECONDS", 300.0, minimum=30.0),
    )
    if image_error is not None:
        return ContainerStartResult(success=False, container_name=container_name, error=image_error)

    env_values = env or {}
    jwt_secret = env_values.get("SUPABASE_JWT_SECRET") or DEFAULT_SUPABASE_JWT_SECRET
    anon_key = env_values.get("SUPABASE_ANON_KEY") or default_supabase_anon_key(secret=jwt_secret)
    service_role_key = env_values.get("SUPABASE_SERVICE_ROLE_KEY") or default_supabase_service_role_key(
        secret=jwt_secret
    )
    create_command = [
        "create",
        "--name",
        container_name,
        "-e",
        f"POSTGRES_PASSWORD={env_values.get('SUPABASE_DB_PASSWORD', 'supabase-db-password')}",
        "-e",
        "POSTGRES_DB=postgres",
        "-e",
        "POSTGRES_USER=postgres",
        "-e",
        f"JWT_SECRET={jwt_secret}",
        "-e",
        f"ANON_KEY={anon_key}",
        "-e",
        f"SERVICE_ROLE_KEY={service_role_key}",
        "-p",
        f"{db_port}:5432",
        "-v",
        f"{volume_name}:/var/lib/postgresql/data",
        "-v",
        f"{compose_root / 'init' / '01-create-n8n-db.sql'}:/docker-entrypoint-initdb.d/01-create-n8n-db.sql:ro",
        "-v",
        (
            f"{compose_root / 'init' / '02-bootstrap-gotrue-auth.sql'}:"
            "/docker-entrypoint-initdb.d/02-bootstrap-gotrue-auth.sql:ro"
        ),
        image,
    ]
    create_result, create_error = run_docker(
        process_runner,
        create_command,
        cwd=project_root,
        env=env,
        timeout=create_timeout_seconds,
    )
    if create_result is None:
        recovered = timeout_error(create_error) and _recover_native_db_create_timeout(
            process_runner=process_runner,
            container_name=container_name,
            cwd=project_root,
            env=env,
        )
        if not recovered:
            return ContainerStartResult(success=False, container_name=container_name, error=create_error)
    elif getattr(create_result, "returncode", 1) != 0:
        return ContainerStartResult(
            success=False,
            container_name=container_name,
            error=run_result_error(create_result, "failed creating supabase db container"),
        )

    start_result, start_error = run_docker(
        process_runner,
        ["start", container_name],
        cwd=project_root,
        env=env,
        timeout=start_timeout_seconds,
    )
    recovered = False
    recovery_error = None
    start_timed_out = (start_result is None and timeout_error(start_error)) or (
        start_result is not None and getattr(start_result, "returncode", 1) == 124
    )
    if start_timed_out:
        recovered, recovery_error = _recover_native_db_start_timeout(
            process_runner=process_runner,
            container_name=container_name,
            port=db_port,
            cwd=project_root,
            env=env,
            listener_wait_timeout=listener_wait_timeout,
        )
    if (start_result is None or start_timed_out) and not recovered:
        return ContainerStartResult(
            success=False,
            container_name=container_name,
            error=_native_db_timeout_error_for_retry(
                port=db_port,
                start_error=start_error
                or (
                    run_result_error(start_result, "failed starting supabase db container")
                    if start_result is not None
                    else None
                ),
                recovery_error=recovery_error,
            ),
        )
    if start_result is not None and getattr(start_result, "returncode", 1) != 0:
        return ContainerStartResult(
            success=False,
            container_name=container_name,
            error=run_result_error(start_result, "failed starting supabase db container"),
        )
    if not bool(process_runner.wait_for_port(db_port, timeout=listener_wait_timeout)):
        return ContainerStartResult(
            success=False,
            container_name=container_name,
            error=f"probe timeout waiting for readiness on port {db_port}",
        )
    return ContainerStartResult(
        success=True,
        container_name=container_name,
        effective_port=db_port,
    )


def _recover_native_db_start_timeout(
    *,
    process_runner,
    container_name: str,
    port: int,
    cwd: Path,
    env: Mapping[str, str] | None,
    listener_wait_timeout: float,
) -> tuple[bool, str | None]:
    recovery_deadline = time.monotonic() + _native_db_start_recovery_timeout_seconds(env)
    published_port: int | None = None
    while time.monotonic() < recovery_deadline:
        status, status_error = container_status(
            process_runner,
            container_name=container_name,
            cwd=cwd,
            env=env,
        )
        if status_error is None and status == "running":
            published_port = _native_db_published_port(
                process_runner,
                container_name=container_name,
                cwd=cwd,
                env=env,
            )
            if published_port is not None and bool(
                process_runner.wait_for_port(published_port, timeout=min(listener_wait_timeout, 1.0))
            ):
                return True, None
        state_error = _native_db_state_error(
            process_runner,
            container_name=container_name,
            cwd=cwd,
            env=env,
        )
        if is_bind_conflict(state_error):
            return False, state_error
        sleeper = getattr(process_runner, "sleep", None)
        if callable(sleeper):
            sleeper(1.0)
        else:
            time.sleep(1.0)
    status, status_error = container_status(
        process_runner,
        container_name=container_name,
        cwd=cwd,
        env=env,
    )
    if status_error is None and status == "running":
        published_port = _native_db_published_port(
            process_runner,
            container_name=container_name,
            cwd=cwd,
            env=env,
        )
        if published_port is None:
            return False, f"published host port missing for port {port}"
        if bool(process_runner.wait_for_port(published_port, timeout=min(listener_wait_timeout, 1.0))):
            return True, None
        return False, f"probe timeout waiting for readiness on port {published_port}"
    state_error = _native_db_state_error(
        process_runner,
        container_name=container_name,
        cwd=cwd,
        env=env,
    )
    if is_bind_conflict(state_error):
        return False, state_error
    return False, None


def _recover_native_db_create_timeout(
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
        sleeper = getattr(process_runner, "sleep", None)
        if callable(sleeper):
            sleeper(1.0)
        else:
            time.sleep(1.0)
    return False


def _native_db_start_timeout_seconds(env: Mapping[str, str] | None) -> float:
    parsed = env_float(env, "ENVCTL_SUPABASE_DB_START_TIMEOUT_SECONDS", 8.0, minimum=1.0)
    if parsed <= 0:
        return 8.0
    return parsed


def _native_db_start_recovery_timeout_seconds(env: Mapping[str, str] | None) -> float:
    parsed = env_float(env, "ENVCTL_SUPABASE_DB_START_RECOVERY_TIMEOUT_SECONDS", 18.0, minimum=1.0)
    if parsed <= 0:
        return 18.0
    return parsed


def _native_db_state_error(
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


def _native_db_published_port(
    process_runner,
    *,
    container_name: str,
    cwd: Path,
    env: Mapping[str, str] | None,
) -> int | None:
    result, error = run_docker(
        process_runner,
        ["inspect", "-f", "{{json .NetworkSettings.Ports}}", container_name],
        cwd=cwd,
        env=env,
        timeout=10.0,
    )
    if result is None or getattr(result, "returncode", 1) != 0:
        return None
    payload = str(getattr(result, "stdout", "") or "").strip()
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


def _native_db_timeout_error_for_retry(
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


def _force_remove_native_db_container(
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

