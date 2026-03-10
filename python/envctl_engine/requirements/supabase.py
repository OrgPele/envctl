from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from collections.abc import Mapping

from envctl_engine.shared.protocols import ProcessRuntime

from .adapter_base import env_bool, env_float, env_int, port_mismatch_policy, timeout_error
from .common import (
    ContainerStartResult,
    RetryResult,
    build_container_name,
    container_exists,
    container_host_port,
    container_status,
    is_bind_conflict,
    run_docker,
    run_result_error,
    run_with_retry,
)
from ..shared.dependency_compose_assets import (
    dependency_compose_asset_dir,
    materialize_dependency_compose,
    supabase_managed_env,
)


def start_supabase_with_retry(
    start,
    reserve_next,
    port: int,
    max_retries: int = 3,  # noqa: ANN001
) -> RetryResult:
    return run_with_retry(initial_port=port, start=start, reserve_next=reserve_next, max_retries=max_retries)


def start_supabase_stack(
    *,
    process_runner: ProcessRuntime,
    project_root: Path,
    project_name: str,
    db_port: int,
    runtime_root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> ContainerStartResult:
    compose_project_name = build_supabase_project_name(
        project_root=project_root,
        project_name=project_name,
    )
    compose_root, compose_path = _resolve_supabase_compose_workspace(
        project_root=project_root,
        project_name=project_name,
        db_port=db_port,
        runtime_root=runtime_root,
        env=env,
    )
    if _native_db_start_enabled(env):
        return _start_supabase_db_native(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            project_root=project_root,
            db_port=db_port,
            env=env,
        )
    if not compose_path.is_file():
        return ContainerStartResult(
            success=False,
            container_name=compose_project_name,
            error=f"missing supabase compose file: {compose_path}",
        )

    available_services = _compose_service_list(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
    )
    db_service = _resolve_service_name(available_services, ("supabase-db", "db")) or "supabase-db"
    auth_service = _resolve_service_name(available_services, ("supabase-auth", "auth", "gotrue"))
    gateway_service = _resolve_service_name(available_services, ("supabase-kong", "kong", "gateway"))

    db_handoff_recovered = False
    up_db = _compose_run(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=["up", "-d", db_service],
    )
    if up_db is not None:
        db_handoff_recovered = _compose_timeout_recovered(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            service_name=db_service,
            probe_port=db_port,
            error=up_db,
        )
        if not db_handoff_recovered:
            return ContainerStartResult(success=False, container_name=compose_project_name, error=up_db)

    if db_port > 0:
        db_probe_attempts = _db_probe_attempts(env)
        db_probe_timeout = _db_probe_timeout_seconds(env)
        db_ready = False
        for attempt in range(db_probe_attempts):
            if bool(process_runner.wait_for_port(db_port, timeout=db_probe_timeout)):
                db_ready = True
                break
            if attempt < db_probe_attempts - 1 and not db_handoff_recovered:
                retry_up_db = _compose_run(
                    process_runner=process_runner,
                    compose_root=compose_root,
                    compose_project_name=compose_project_name,
                    compose_path=compose_path,
                    env=env,
                    args=["up", "-d", db_service],
                )
                if retry_up_db is not None:
                    db_handoff_recovered = _compose_timeout_recovered(
                        process_runner=process_runner,
                        compose_root=compose_root,
                        compose_project_name=compose_project_name,
                        compose_path=compose_path,
                        env=env,
                        service_name=db_service,
                        probe_port=db_port,
                        error=retry_up_db,
                    )
                    if not db_handoff_recovered:
                        return ContainerStartResult(
                            success=False,
                            container_name=compose_project_name,
                            error=f"{retry_up_db} (retry db bring-up failed)",
                        )

        if not db_ready and _db_restart_on_probe_failure_enabled(env):
            restart_error = _compose_run(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
                args=["restart", db_service],
            )
            if restart_error is not None:
                return ContainerStartResult(
                    success=False,
                    container_name=compose_project_name,
                    error=(
                        f"failed restarting supabase db service: {restart_error}"
                        if restart_error.strip()
                        else "failed restarting supabase db service"
                    ),
                )
            restart_probe_attempts = _db_restart_probe_attempts(env, default=db_probe_attempts)
            db_ready = _probe_db_listener(
                process_runner=process_runner,
                db_port=db_port,
                timeout_seconds=db_probe_timeout,
                attempts=restart_probe_attempts,
            )

            if not db_ready and _db_recreate_on_probe_failure_enabled(env):
                recreate_error = _recreate_db_service(
                    process_runner=process_runner,
                    compose_root=compose_root,
                    compose_project_name=compose_project_name,
                    compose_path=compose_path,
                    env=env,
                    db_service=db_service,
                )
                if recreate_error is not None:
                    return ContainerStartResult(
                        success=False,
                        container_name=compose_project_name,
                        error=(
                            f"failed recreating supabase db service: {recreate_error}"
                            if recreate_error.strip()
                            else "failed recreating supabase db service"
                        ),
                    )
                recreate_probe_attempts = _db_recreate_probe_attempts(env, default=restart_probe_attempts)
                db_ready = _probe_db_listener(
                    process_runner=process_runner,
                    db_port=db_port,
                    timeout_seconds=db_probe_timeout,
                    attempts=recreate_probe_attempts,
                )
                if not db_ready:
                    return ContainerStartResult(
                        success=False,
                        container_name=compose_project_name,
                        error=f"probe timeout waiting for readiness on port {db_port} after recreate",
                    )

            if not db_ready:
                return ContainerStartResult(
                    success=False,
                    container_name=compose_project_name,
                    error=f"probe timeout waiting for readiness on port {db_port} after restart",
                )

        if not db_ready:
            suffix = " after retry" if db_probe_attempts > 1 else ""
            return ContainerStartResult(
                success=False,
                container_name=compose_project_name,
                error=f"probe timeout waiting for readiness on port {db_port}{suffix}",
            )

    secondary_services = [
        service for service in (auth_service, gateway_service) if isinstance(service, str) and service
    ]
    if secondary_services:
        if _supabase_two_phase_enabled(env):
            _start_secondary_services_background(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
                secondary_services=secondary_services,
            )
        else:
            up_secondary = _compose_run(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
                args=["up", "-d", *secondary_services],
            )
            if up_secondary is not None:
                if not all(
                    _compose_timeout_recovered(
                        process_runner=process_runner,
                        compose_root=compose_root,
                        compose_project_name=compose_project_name,
                        compose_path=compose_path,
                        env=env,
                        service_name=service_name,
                        probe_port=None,
                        error=up_secondary,
                    )
                    for service_name in secondary_services
                ):
                    return ContainerStartResult(success=False, container_name=compose_project_name, error=up_secondary)

    return ContainerStartResult(success=True, container_name=compose_project_name)


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

    create_command = [
        "create",
        "--name",
        container_name,
        "-e",
        f"POSTGRES_PASSWORD={(env or {}).get('SUPABASE_DB_PASSWORD', 'supabase-db-password')}",
        "-e",
        "POSTGRES_DB=postgres",
        "-e",
        "POSTGRES_USER=postgres",
        "-e",
        f"JWT_SECRET={(env or {}).get('SUPABASE_JWT_SECRET', 'supabase-local-jwt-secret')}",
        "-e",
        f"ANON_KEY={(env or {}).get('SUPABASE_ANON_KEY', 'local-anon-key')}",
        "-e",
        f"SERVICE_ROLE_KEY={(env or {}).get('SUPABASE_SERVICE_ROLE_KEY', 'local-service-role-key')}",
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


@dataclass(slots=True)
class SupabaseReliabilityContract:
    ok: bool
    fingerprint: str
    errors: list[str]
    compose_path: Path | None


def evaluate_supabase_reliability_contract(project_root: Path) -> SupabaseReliabilityContract:
    compose_root = project_root / "supabase"
    compose_path = compose_root / "docker-compose.yml"
    if not compose_path.is_file():
        return SupabaseReliabilityContract(
            ok=False,
            fingerprint="missing",
            errors=["missing supabase compose file: supabase/docker-compose.yml"],
            compose_path=compose_path,
        )

    try:
        compose_text = compose_path.read_text(encoding="utf-8")
    except OSError as exc:
        return SupabaseReliabilityContract(
            ok=False,
            fingerprint="unreadable",
            errors=[f"failed reading supabase compose file: {exc}"],
            compose_path=compose_path,
        )

    errors: list[str] = []

    if _has_static_network_name(compose_text):
        errors.append("supabase compose defines static network name; use project-scoped network names instead")

    if not _contains_search_path_contract(compose_text):
        errors.append("missing GOTRUE_DB_DATABASE_URL search_path contract (?search_path=auth,public)")
    if not _contains_auth_namespace_var(compose_text, "GOTRUE_DB_NAMESPACE"):
        errors.append("missing GOTRUE_DB_NAMESPACE=auth")
    if not _contains_auth_namespace_var(compose_text, "DB_NAMESPACE"):
        errors.append("missing DB_NAMESPACE=auth")

    if "02-bootstrap-gotrue-auth.sql" not in compose_text:
        errors.append("missing mount for 02-bootstrap-gotrue-auth.sql")
    if "01-create-n8n-db.sql" not in compose_text:
        errors.append("missing mount for 01-create-n8n-db.sql")
    if "kong.yml" not in compose_text:
        errors.append("missing mount for kong.yml")

    errors.extend(_unsafe_mount_path_errors(compose_text))

    fingerprint = _fingerprint_contract_inputs(compose_root, compose_text=compose_text)
    return SupabaseReliabilityContract(
        ok=not errors,
        fingerprint=fingerprint,
        errors=errors,
        compose_path=compose_path,
    )


def read_fingerprint(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("fingerprint")
    return str(value) if isinstance(value, str) and value.strip() else None


def write_fingerprint(path: Path, *, fingerprint: str, project_root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fingerprint": fingerprint,
        "project_root": str(project_root),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def evaluate_managed_supabase_reliability_contract() -> SupabaseReliabilityContract:
    compose_root = dependency_compose_asset_dir("supabase")
    compose_path = compose_root / "docker-compose.yml"
    if not compose_path.is_file():
        return SupabaseReliabilityContract(
            ok=False,
            fingerprint="missing",
            errors=[f"missing envctl managed supabase compose file: {compose_path}"],
            compose_path=compose_path,
        )
    try:
        compose_text = compose_path.read_text(encoding="utf-8")
    except OSError as exc:
        return SupabaseReliabilityContract(
            ok=False,
            fingerprint="unreadable",
            errors=[f"failed reading envctl managed supabase compose file: {exc}"],
            compose_path=compose_path,
        )
    errors: list[str] = []
    if _has_static_network_name(compose_text):
        errors.append("supabase compose defines static network name; use project-scoped network names instead")
    if not _contains_search_path_contract(compose_text):
        errors.append("missing GOTRUE_DB_DATABASE_URL search_path contract (?search_path=auth,public)")
    if not _contains_auth_namespace_var(compose_text, "GOTRUE_DB_NAMESPACE"):
        errors.append("missing GOTRUE_DB_NAMESPACE=auth")
    if not _contains_auth_namespace_var(compose_text, "DB_NAMESPACE"):
        errors.append("missing DB_NAMESPACE=auth")
    if "02-bootstrap-gotrue-auth.sql" not in compose_text:
        errors.append("missing mount for 02-bootstrap-gotrue-auth.sql")
    if "01-create-n8n-db.sql" not in compose_text:
        errors.append("missing mount for 01-create-n8n-db.sql")
    if "kong.yml" not in compose_text:
        errors.append("missing mount for kong.yml")
    errors.extend(_unsafe_mount_path_errors(compose_text))
    fingerprint = _fingerprint_contract_inputs(compose_root, compose_text=compose_text)
    return SupabaseReliabilityContract(
        ok=not errors,
        fingerprint=fingerprint,
        errors=errors,
        compose_path=compose_path,
    )


def _fingerprint_contract_inputs(compose_root: Path, *, compose_text: str) -> str:
    hasher = hashlib.sha256()
    hasher.update(compose_text.encode("utf-8"))
    for rel in (
        Path("kong.yml"),
        Path("init/01-create-n8n-db.sql"),
        Path("init/02-bootstrap-gotrue-auth.sql"),
    ):
        path = compose_root / rel
        hasher.update(str(rel).encode("utf-8"))
        if path.is_file():
            try:
                hasher.update(path.read_bytes())
            except OSError:
                hasher.update(b"<unreadable>")
        else:
            hasher.update(b"<missing>")
    return hasher.hexdigest()


def _compose_service_list(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
) -> set[str]:
    result, error = run_docker(
        process_runner,
        ["compose", "-p", compose_project_name, "-f", str(compose_path), "config", "--services"],
        cwd=compose_root,
        env=env,
        timeout=60.0,
    )
    if result is None or error is not None:
        return set()
    if getattr(result, "returncode", 1) != 0:
        return set()
    stdout = str(getattr(result, "stdout", "") or "")
    return {line.strip() for line in stdout.splitlines() if line.strip()}


def _resolve_service_name(available: set[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in available:
            return candidate
    return None


def _compose_run(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    args: list[str],
) -> str | None:
    timeout_seconds = 180.0
    if args[:2] == ["up", "-d"]:
        timeout_seconds = env_float(
            env,
            "ENVCTL_SUPABASE_COMPOSE_UP_TIMEOUT_SECONDS",
            45.0,
            minimum=5.0,
        )
        service_names = [value for value in args[2:] if value]
        probe_port = None
        if len(service_names) == 1 and service_names[0] in {"supabase-db", "db"}:
            probe_port = _compose_db_port(compose_root=compose_root)
        return _compose_up_handoff(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            args=args,
            timeout_seconds=timeout_seconds,
            service_names=service_names,
            probe_port=probe_port,
        )
    result, error = run_docker(
        process_runner,
        ["compose", "-p", compose_project_name, "-f", str(compose_path), *args],
        cwd=compose_root,
        env=env,
        timeout=timeout_seconds,
    )
    if result is None:
        return error
    if getattr(result, "returncode", 1) != 0:
        return _normalize_compose_error(
            run_result_error(result, f"docker compose {' '.join(args)} failed"),
            compose_project_name=compose_project_name,
        )
    return None


def _compose_up_handoff(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    args: list[str],
    timeout_seconds: float,
    service_names: list[str],
    probe_port: int | None,
) -> str | None:
    command = ["docker", "compose", "-p", compose_project_name, "-f", str(compose_path), *args]
    process_factory = getattr(process_runner, "compose_up_process", None)
    if callable(process_factory):
        process = process_factory(
            command,
            cwd=str(compose_root),
            env=dict(env) if env is not None else None,
        )
    else:
        process = subprocess.Popen(
            command,
            cwd=str(compose_root),
            env=dict(env) if env is not None else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    deadline = time.monotonic() + timeout_seconds
    sleeper = getattr(process_runner, "sleep", time.sleep)
    while True:
        returncode = process.poll()
        if returncode is not None:
            stdout, stderr = process.communicate()
            result = subprocess.CompletedProcess(command, returncode, stdout or "", stderr or "")
            if returncode == 0:
                return None
            return _normalize_compose_error(
                run_result_error(result, f"docker compose {' '.join(args)} failed"),
                compose_project_name=compose_project_name,
            )

        if service_names and _compose_services_started(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            service_names=service_names,
        ):
            if probe_port is None or bool(process_runner.wait_for_port(probe_port, timeout=0.5)):
                _terminate_compose_process(process)
                return None

        if time.monotonic() >= deadline:
            stdout, stderr = _terminate_compose_process(process)
            timed_out_error = f"Command timed out after {timeout_seconds:.1f}s: docker compose {' '.join(args)}"
            if (
                service_names
                and _compose_services_started(
                    process_runner=process_runner,
                    compose_root=compose_root,
                    compose_project_name=compose_project_name,
                    compose_path=compose_path,
                    env=env,
                    service_names=service_names,
                )
                and (probe_port is None or bool(process_runner.wait_for_port(probe_port, timeout=0.5)))
            ):
                return None
            result = subprocess.CompletedProcess(command, 124, stdout, stderr or timed_out_error)
            return _normalize_compose_error(
                run_result_error(result, f"docker compose {' '.join(args)} failed"),
                compose_project_name=compose_project_name,
            )

        sleeper(0.25)


def _compose_services_started(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_names: list[str],
) -> bool:
    for service_name in service_names:
        result, run_error = run_docker(
            process_runner,
            ["compose", "-p", compose_project_name, "-f", str(compose_path), "ps", "-q", service_name],
            cwd=compose_root,
            env=env,
            timeout=10.0,
        )
        if result is None or run_error is not None or getattr(result, "returncode", 1) != 0:
            return False
        if not str(getattr(result, "stdout", "") or "").strip():
            return False
    return True


def _terminate_compose_process(process: subprocess.Popen[str]) -> tuple[str, str]:
    stdout = ""
    stderr = ""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        pass
    try:
        extra_stdout, extra_stderr = process.communicate(timeout=2.0)
        stdout = extra_stdout or ""
        stderr = extra_stderr or ""
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            extra_stdout, extra_stderr = process.communicate(timeout=2.0)
            stdout = extra_stdout or ""
            stderr = extra_stderr or ""
        except subprocess.TimeoutExpired:
            pass
    return stdout, stderr


def _compose_db_port(*, compose_root: Path) -> int | None:
    # Managed supabase DB startup is considered ready once the host DB port accepts connections.
    # Extract the rendered port from the materialized compose file name/location contract.
    env_path = compose_root / ".env"
    if not env_path.is_file():
        return None
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"^SUPABASE_DB_PORT=(\d+)$", text, re.MULTILINE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _compose_timeout_recovered(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_name: str,
    probe_port: int | None,
    error: str | None,
) -> bool:
    if not timeout_error(error):
        return False
    for _ in range(3):
        result, run_error = run_docker(
            process_runner,
            ["compose", "-p", compose_project_name, "-f", str(compose_path), "ps", "-q", service_name],
            cwd=compose_root,
            env=env,
            timeout=60.0,
        )
        if result is not None and run_error is None and getattr(result, "returncode", 1) == 0:
            if str(getattr(result, "stdout", "") or "").strip():
                return True
        elif probe_port and probe_port > 0 and bool(process_runner.wait_for_port(probe_port, timeout=5.0)):
            return True
    return False


def _probe_db_listener(
    *,
    process_runner,
    db_port: int,
    timeout_seconds: float,
    attempts: int,
) -> bool:
    for _ in range(max(1, attempts)):
        if bool(process_runner.wait_for_port(db_port, timeout=timeout_seconds)):
            return True
    return False


def _recreate_db_service(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    db_service: str,
) -> str | None:
    stop_error = _compose_run(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=["stop", db_service],
    )
    if stop_error is not None:
        return stop_error
    rm_error = _compose_run(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=["rm", "-f", db_service],
    )
    if rm_error is not None:
        return rm_error
    up_error = _compose_run(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=["up", "-d", db_service],
    )
    return up_error


def _normalize_compose_error(error: str, *, compose_project_name: str) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for raw in str(error).splitlines():
        line = raw.strip()
        if not line:
            continue
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)
    normalized = "\n".join(lines).strip()
    if not normalized:
        return normalized
    if _is_container_name_conflict(normalized):
        container_name = _extract_conflicting_container_name(normalized)
        detail = f"conflicting container={container_name}" if container_name else "conflicting container already exists"
        return (
            f"supabase compose namespace conflict for project {compose_project_name}: {detail}. "
            "This usually means the stack is not using a project-scoped compose namespace "
            "or a stale conflicting container still exists."
        )
    return normalized


def _is_container_name_conflict(error: str) -> bool:
    lowered = error.lower()
    return "container name" in lowered and "already in use" in lowered and "conflict" in lowered


def _extract_conflicting_container_name(error: str) -> str | None:
    match = re.search(r'container name\s+"?/?([^"\s]+)"?', error, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip() or None


def _resolve_supabase_compose_workspace(
    *,
    project_root: Path,
    project_name: str,
    db_port: int,
    runtime_root: Path | None,
    env: Mapping[str, str] | None,
) -> tuple[Path, Path]:
    if runtime_root is None:
        compose_root = project_root / "supabase"
        return compose_root, compose_root / "docker-compose.yml"

    materialized = materialize_dependency_compose(
        runtime_root=runtime_root,
        dependency_name="supabase",
        project_name=project_name,
        compose_project_name=build_supabase_project_name(
            project_root=project_root,
            project_name=project_name,
        ),
        env_values=supabase_managed_env(db_port=db_port, env=env),
    )
    return materialized.stack_root, materialized.compose_file


def _contains_search_path_contract(compose_text: str) -> bool:
    pattern = re.compile(r"GOTRUE_DB_DATABASE_URL\s*[:=]\s*['\"]?[^'\"\n]*search_path=auth,public", re.IGNORECASE)
    return bool(pattern.search(compose_text))


def _contains_auth_namespace_var(compose_text: str, key: str) -> bool:
    pattern = re.compile(rf"{re.escape(key)}\s*[:=]\s*['\"]?auth(?:['\"]|\s|$)", re.IGNORECASE)
    return bool(pattern.search(compose_text))


def _has_static_network_name(compose_text: str) -> bool:
    lines = compose_text.splitlines()
    in_networks = False
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not in_networks:
            if stripped == "networks:":
                in_networks = True
            continue
        if line and not line.startswith((" ", "\t")):
            break
        if re.search(r"^\s*name\s*:\s*[^$].+", line):
            return True
    return False


def _unsafe_mount_path_errors(compose_text: str) -> list[str]:
    errors: list[str] = []
    for marker in ("kong.yml", "01-create-n8n-db.sql", "02-bootstrap-gotrue-auth.sql"):
        for line in compose_text.splitlines():
            if marker not in line:
                continue
            mount = _extract_mount_source(line)
            if mount is None:
                continue
            if mount.startswith("/"):
                errors.append(f"unsafe absolute mount for {marker}: {mount}")
    return errors


def _extract_mount_source(line: str) -> str | None:
    # Matches compose short syntax: - ./path/file:/container/path[:mode]
    match = re.search(r"^\s*-\s*([^:\s]+):", line)
    if not match:
        return None
    return match.group(1).strip()


def _db_probe_attempts(env: Mapping[str, str] | None) -> int:
    return env_int(env, "ENVCTL_SUPABASE_DB_PROBE_ATTEMPTS", 2, minimum=1)


def _db_probe_timeout_seconds(env: Mapping[str, str] | None) -> float:
    parsed = env_float(env, "ENVCTL_SUPABASE_DB_PROBE_TIMEOUT_SECONDS", 10.0)
    if parsed <= 0:
        return 30.0
    return parsed


def _db_restart_probe_attempts(env: Mapping[str, str] | None, *, default: int) -> int:
    return env_int(env, "ENVCTL_SUPABASE_DB_RESTART_PROBE_ATTEMPTS", default, minimum=1)


def _db_recreate_probe_attempts(env: Mapping[str, str] | None, *, default: int) -> int:
    return env_int(env, "ENVCTL_SUPABASE_DB_RECREATE_PROBE_ATTEMPTS", default, minimum=1)


def _db_restart_on_probe_failure_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_SUPABASE_DB_RESTART_ON_PROBE_FAILURE", True)


def _db_recreate_on_probe_failure_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_SUPABASE_DB_RECREATE_ON_PROBE_FAILURE", True)


def _native_db_start_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_SUPABASE_DB_START_NATIVE", False)


def _supabase_two_phase_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_SUPABASE_TWO_PHASE_STARTUP", True)


def _start_secondary_services_background(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    secondary_services: list[str],
) -> None:
    def _worker() -> None:
        _compose_run(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            args=["up", "-d", *secondary_services],
        )

    threading.Thread(
        target=_worker,
        name=f"envctl-supabase-secondary-{compose_project_name}",
        daemon=True,
    ).start()


def build_supabase_project_name(*, project_root: Path, project_name: str) -> str:
    return build_container_name(
        prefix="envctl-supabase",
        project_root=project_root,
        project_name=project_name,
    )
