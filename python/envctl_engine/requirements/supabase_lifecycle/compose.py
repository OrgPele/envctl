from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from envctl_engine.debug.debug_utils import file_lock

from ..common import docker_port_publish_lock, run_docker
from ..adapter_base import env_bool, env_float, timeout_error
from ..common import run_result_error
from .config import _supabase_startup_budget_seconds
from .formatting import _supabase_compose_failure_detail
from .inspect import _inspect_auth_gateway_services, _inspect_auth_gateway_service
from .network_recovery import (
    _is_docker_address_pool_exhaustion,
    _is_docker_network_missing,
    _recover_missing_supabase_network_for_project,
    _remove_empty_envctl_supabase_networks,
)
from .probe import _compose_service_state_failed
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
        process = cast(
            subprocess.Popen[str],
            process_factory(
                command,
                cwd=str(compose_root),
                env=dict(env) if env is not None else None,
            ),
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
    monotonic = getattr(process_runner, "monotonic", time.monotonic)
    deadline = monotonic() + timeout_seconds
    stall_deadline = monotonic() + _compose_port_publish_stall_seconds(env)
    sleeper = getattr(process_runner, "sleep", time.sleep)
    while True:
        returncode = process.poll()
        if returncode is not None:
            stdout, stderr = process.communicate()
            result = subprocess.CompletedProcess(command, returncode, stdout or "", stderr or "")
            if returncode == 0:
                return None
            raw_error = _normalize_compose_error(
                run_result_error(result, f"docker compose {' '.join(args)} failed"),
                compose_project_name=compose_project_name,
            )
            stalled_detail = _compose_stalled_port_detail(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
                service_names=service_names,
                probe_port=probe_port,
            )
            if stalled_detail:
                return f"{raw_error}; {stalled_detail}"
            return raw_error

        if service_names and _compose_handoff_ready(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            service_names=service_names,
            probe_port=probe_port,
        ):
            _terminate_compose_process(process)
            return None

        if monotonic() >= stall_deadline:
            stalled_detail = _compose_stalled_port_detail(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
                service_names=service_names,
                probe_port=probe_port,
            )
            if stalled_detail is not None:
                stdout, stderr = _terminate_compose_process(process)
                raw_error = stderr or stdout or f"docker compose {' '.join(args)} stalled"
                return _supabase_compose_failure_detail(
                    phase="compose_graph" if len(service_names) > 1 else "compose_up",
                    error=f"{raw_error}; {stalled_detail}",
                    services=service_names,
                    service_states=[],
                    compose_timeout_seconds=timeout_seconds,
                    public_port=None,
                    health_url=None,
                )
            stall_deadline = monotonic() + _compose_port_publish_stall_seconds(env)

        if monotonic() >= deadline:
            stdout, stderr = _terminate_compose_process(process)
            timed_out_error = f"Command timed out after {timeout_seconds:.1f}s: docker compose {' '.join(args)}"
            if (
                service_names
                and _compose_handoff_ready(
                    process_runner=process_runner,
                    compose_root=compose_root,
                    compose_project_name=compose_project_name,
                    compose_path=compose_path,
                    env=env,
                    service_names=service_names,
                    probe_port=probe_port,
                )
            ):
                return None
            result = subprocess.CompletedProcess(command, 124, stdout, stderr or timed_out_error)
            raw_error = _normalize_compose_error(
                run_result_error(result, f"docker compose {' '.join(args)} failed"),
                compose_project_name=compose_project_name,
            )
            stalled_detail = _compose_stalled_port_detail(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
                service_names=service_names,
                probe_port=probe_port,
            )
            if stalled_detail:
                raw_error = f"{raw_error}; {stalled_detail}"
            states = _inspect_auth_gateway_services(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
                service_names=service_names,
            )
            return _supabase_compose_failure_detail(
                phase="compose_graph" if len(service_names) > 1 else "compose_up",
                error=raw_error,
                services=service_names,
                service_states=states,
                compose_timeout_seconds=timeout_seconds,
                public_port=None,
                health_url=None,
            )

        sleeper(0.25)


def _compose_port_publish_stall_seconds(env: Mapping[str, str] | None) -> float:
    return env_float(env, "ENVCTL_SUPABASE_COMPOSE_PORT_PUBLISH_STALL_SECONDS", 45.0, minimum=5.0)


def _compose_unpublished_port_detail(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_names: list[str],
) -> str | None:
    states = _inspect_auth_gateway_services(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        service_names=service_names,
    )
    if not states or any(_compose_service_state_failed(state) for state in states):
        return None
    for service_state in states:
        service_name = str(service_state.get("service") or "").strip()
        container_port = _published_container_port_for_service(service_name)
        if container_port is None:
            continue
        status = str(service_state.get("status") or "").strip().lower()
        health = str(service_state.get("health") or "").strip().lower()
        container = str(service_state.get("container") or "").strip()
        if not container or status != "running" or health not in {"", "healthy"}:
            continue
        expected_port = _expected_host_port_for_service(service_name, compose_root=compose_root)
        if expected_port is None:
            continue
        if bool(process_runner.wait_for_port(expected_port, timeout=0.5)):
            continue
        host_port_label = "API" if _is_gateway_service_name(service_name) else "DB"
        return (
            f"Docker Compose stalled before publishing Supabase {host_port_label} host port {expected_port}: "
            f"Docker reported {service_name} running/healthy, but the host socket is not reachable."
        )
    return None


def _compose_stalled_port_detail(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_names: list[str],
    probe_port: int | None,
) -> str | None:
    if probe_port is not None and not bool(process_runner.wait_for_port(probe_port, timeout=0.2)):
        return f"Docker Compose stalled before publishing Supabase DB host port {probe_port}."
    public_port = _compose_public_port(compose_root=compose_root)
    if public_port is not None and any(_is_gateway_service_name(service_name) for service_name in service_names):
        if not bool(process_runner.wait_for_port(public_port, timeout=0.2)):
            return f"Docker Compose stalled before publishing Supabase API host port {public_port}."
    return _compose_unpublished_port_detail(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        service_names=service_names,
    )


def _published_container_port_for_service(service_name: str) -> int | None:
    normalized = str(service_name or "").strip().lower()
    if normalized in {"supabase-db", "db"}:
        return 5432
    if normalized in {"supabase-kong", "kong", "gateway"}:
        return 8000
    return None


def _expected_host_port_for_service(service_name: str, *, compose_root: Path) -> int | None:
    normalized = str(service_name or "").strip().lower()
    if normalized in {"supabase-db", "db"}:
        return _compose_db_port(compose_root=compose_root)
    if _is_gateway_service_name(normalized):
        return _compose_public_port(compose_root=compose_root)
    return None


def _is_gateway_service_name(service_name: str) -> bool:
    return str(service_name or "").strip().lower() in {"supabase-kong", "kong", "gateway"}


def _is_compose_port_publish_stall(error: str | None) -> bool:
    normalized = " ".join(str(error or "").lower().split())
    return "docker compose stalled before publishing supabase" in normalized


def _compose_services_started(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_names: list[str],
) -> bool:
    states = _inspect_auth_gateway_services(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        service_names=service_names,
    )
    return bool(states) and all(_compose_service_state_ready(state) for state in states)


def _compose_handoff_ready(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_names: list[str],
    probe_port: int | None,
) -> bool:
    if probe_port is not None and not bool(process_runner.wait_for_port(probe_port, timeout=0.5)):
        return False
    public_port = _compose_public_port(compose_root=compose_root)
    if public_port is not None and any(_is_gateway_service_name(service_name) for service_name in service_names):
        if not bool(process_runner.wait_for_port(public_port, timeout=0.5)):
            return False
    states = _inspect_auth_gateway_services(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        service_names=service_names,
    )
    if not states:
        return False
    if any(_compose_service_state_failed(state) for state in states):
        return False
    services_ready = all(_compose_service_state_ready(state) for state in states)
    if not services_ready:
        return False
    return True


def _compose_service_state_ready(service_state: Mapping[str, object]) -> bool:
    status = str(service_state.get("status") or "").strip().lower()
    health = str(service_state.get("health") or "").strip().lower()
    if status != "running":
        return False
    return health in {"", "healthy"}


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


def _compose_public_port(*, compose_root: Path) -> int | None:
    env_path = compose_root / ".env"
    if not env_path.is_file():
        return None
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"^SUPABASE_PUBLIC_PORT=(\d+)$", text, re.MULTILINE)
    if not match:
        match = re.search(r"^SUPABASE_API_PORT=(\d+)$", text, re.MULTILINE)
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
        service_state = _inspect_auth_gateway_service(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            service_name=service_name,
        )
        if probe_port and probe_port > 0 and bool(process_runner.wait_for_port(probe_port, timeout=5.0)):
            return True
        if _compose_service_state_ready(service_state):
            return True
    return False

