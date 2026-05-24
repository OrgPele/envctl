from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from envctl_engine.debug.debug_utils import file_lock

from ..common import docker_port_publish_lock, run_docker
from ..adapter_base import env_bool, env_float
from ..common import run_result_error
from .config import _supabase_startup_budget_seconds
from .compose_handoff import (
    compose_db_port as _compose_db_port,
    compose_handoff_ready as _compose_handoff_ready,
    compose_port_publish_stall_seconds as _compose_port_publish_stall_seconds,
    compose_public_port as _compose_public_port,
    compose_service_state_ready as _compose_service_state_ready,
    compose_services_started as _compose_services_started,
    compose_stalled_port_detail as _compose_stalled_port_detail,
    compose_timeout_recovered as _compose_timeout_recovered,
    compose_unpublished_port_detail as _compose_unpublished_port_detail,
    compose_up_handoff as _compose_up_handoff,
    expected_host_port_for_service as _expected_host_port_for_service,
    is_compose_port_publish_stall as _is_compose_port_publish_stall,
    is_gateway_service_name as _is_gateway_service_name,
    published_container_port_for_service as _published_container_port_for_service,
    terminate_compose_process as _terminate_compose_process,
)
from .network_recovery import (
    _is_docker_address_pool_exhaustion,
    _is_docker_network_missing,
    _recover_missing_supabase_network_for_project,
    _remove_empty_envctl_supabase_networks,
)
from .workspace import _normalize_compose_error

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
    lock_timeout = _compose_lock_timeout_seconds(env)
    lock_path = _compose_project_lock_path(compose_root=compose_root, compose_project_name=compose_project_name)
    try:
        with file_lock(lock_path, timeout=lock_timeout):
            if _compose_args_mutate_port_bindings(args):
                with docker_port_publish_lock(env):
                    return _compose_run_locked(
                        process_runner=process_runner,
                        compose_root=compose_root,
                        compose_project_name=compose_project_name,
                        compose_path=compose_path,
                        env=env,
                        args=args,
                    )
            return _compose_run_locked(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
                args=args,
            )
    except TimeoutError as exc:
        return f"timed out acquiring Supabase compose lock after {lock_timeout:.1f}s: {exc}"


def _compose_args_mutate_port_bindings(args: list[str]) -> bool:
    return bool(args) and args[0] in {"up", "start", "restart", "create", "rm", "down"}


def _compose_run_locked(
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
        service_names = [value for value in args[2:] if value]
        timeout_seconds = _compose_up_timeout_seconds(env, service_names=service_names)
        probe_port = None
        if len(service_names) == 1 and service_names[0] in {"supabase-db", "db"}:
            probe_port = _compose_db_port(compose_root=compose_root)
        elif any(service_name in {"supabase-db", "db"} for service_name in service_names):
            probe_port = _compose_db_port(compose_root=compose_root)
        up_error = _compose_up_handoff(
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
        if up_error is not None and _is_docker_address_pool_exhaustion(up_error):
            cleaned_count, cleanup_error = _remove_empty_envctl_supabase_networks(
                process_runner=process_runner,
                compose_root=compose_root,
                env=env,
            )
            if cleaned_count > 0:
                retry_error = _compose_up_handoff(
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
                if retry_error is None:
                    return None
                if cleanup_error:
                    return (
                        f"{retry_error}; after removing {cleaned_count} empty envctl Supabase network(s): "
                        f"{cleanup_error}"
                    )
                return retry_error
            if cleanup_error:
                return f"{up_error}; could not recover Docker address-pool exhaustion: {cleanup_error}"
            return f"{up_error}; no empty envctl Supabase networks were available for scoped cleanup"
        if up_error is not None and _is_compose_port_publish_stall(up_error):
            if not env_bool(env, "ENVCTL_SUPABASE_PORT_PUBLISH_STALL_RECOVERY", False):
                return up_error
            recovered, recovery_detail = _recover_missing_supabase_network_for_project(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
            )
            if recovered:
                retry_error = _compose_up_handoff(
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
                if retry_error is None:
                    return None
                return (
                    f"{retry_error}; after Supabase port-publish recovery: "
                    f"{recovery_detail or 'compose_down_remove_orphans'}"
                )
            return f"{up_error}; Supabase port-publish recovery failed: {recovery_detail or 'compose down failed'}"
        if up_error is not None and _is_docker_network_missing(up_error):
            recovered, recovery_detail = _recover_missing_supabase_network_for_project(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
            )
            retry_error = _compose_up_handoff(
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
            if retry_error is None:
                return f"network_recovery={recovery_detail or 'retry_only'}"
            action_detail = recovery_detail or "scoped Supabase network recovery"
            if recovered:
                return (
                    f"docker compose {' '.join(args)} failed after scoped Supabase network recovery for "
                    f"{compose_project_name}: {retry_error}; recovery_actions={action_detail}"
                )
            return (
                f"docker compose {' '.join(args)} failed after attempted scoped Supabase network recovery for "
                f"{compose_project_name}: {retry_error}; recovery_error={action_detail}"
            )
        return up_error
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


def _compose_project_lock_path(*, compose_root: Path, compose_project_name: str) -> Path:
    safe_project = re.sub(r"[^A-Za-z0-9_.-]+", "_", compose_project_name).strip("._-") or "supabase"
    return compose_root / f".envctl-{safe_project}.compose.lock"


def _compose_lock_timeout_seconds(env: Mapping[str, str] | None) -> float:
    return env_float(env, "ENVCTL_SUPABASE_COMPOSE_LOCK_TIMEOUT_SECONDS", 180.0, minimum=1.0)


def _compose_up_timeout_seconds(env: Mapping[str, str] | None, *, service_names: list[str]) -> float:
    default_timeout = 120.0
    if len(service_names) > 1 and "ENVCTL_SUPABASE_COMPOSE_UP_TIMEOUT_SECONDS" not in (env or {}):
        default_timeout = _supabase_startup_budget_seconds(env)
    parsed = env_float(
        env,
        "ENVCTL_SUPABASE_COMPOSE_UP_TIMEOUT_SECONDS",
        default_timeout,
        minimum=5.0,
    )
    if len(service_names) > 1:
        return min(parsed if parsed > 0 else default_timeout, _supabase_startup_budget_seconds(env))
    return parsed if parsed > 0 else default_timeout


__all__ = [
    "_compose_args_mutate_port_bindings",
    "_compose_db_port",
    "_compose_handoff_ready",
    "_compose_lock_timeout_seconds",
    "_compose_port_publish_stall_seconds",
    "_compose_project_lock_path",
    "_compose_public_port",
    "_compose_run",
    "_compose_run_locked",
    "_compose_service_list",
    "_compose_service_state_ready",
    "_compose_services_started",
    "_compose_stalled_port_detail",
    "_compose_timeout_recovered",
    "_compose_unpublished_port_detail",
    "_compose_up_handoff",
    "_compose_up_timeout_seconds",
    "_expected_host_port_for_service",
    "_is_compose_port_publish_stall",
    "_is_gateway_service_name",
    "_published_container_port_for_service",
    "_resolve_service_name",
    "_terminate_compose_process",
]
