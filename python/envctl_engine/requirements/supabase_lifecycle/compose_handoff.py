from __future__ import annotations

import os
import re
import signal
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from ..adapter_base import env_float, timeout_error
from ..common import run_result_error
from .formatting import _supabase_compose_failure_detail
from .inspect import _inspect_auth_gateway_service, _inspect_auth_gateway_services
from .probe import _compose_service_state_failed
from .workspace import _normalize_compose_error


def compose_up_handoff(
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
    stall_deadline = monotonic() + compose_port_publish_stall_seconds(env)
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
            stalled_detail = compose_stalled_port_detail(
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

        if service_names and compose_handoff_ready(
            process_runner=process_runner,
            compose_root=compose_root,
            compose_project_name=compose_project_name,
            compose_path=compose_path,
            env=env,
            service_names=service_names,
            probe_port=probe_port,
        ):
            terminate_compose_process(process)
            return None

        if monotonic() >= stall_deadline:
            stalled_detail = compose_stalled_port_detail(
                process_runner=process_runner,
                compose_root=compose_root,
                compose_project_name=compose_project_name,
                compose_path=compose_path,
                env=env,
                service_names=service_names,
                probe_port=probe_port,
            )
            if stalled_detail is not None:
                stdout, stderr = terminate_compose_process(process)
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
            stall_deadline = monotonic() + compose_port_publish_stall_seconds(env)

        if monotonic() >= deadline:
            stdout, stderr = terminate_compose_process(process)
            timed_out_error = f"Command timed out after {timeout_seconds:.1f}s: docker compose {' '.join(args)}"
            if (
                service_names
                and compose_handoff_ready(
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
            stalled_detail = compose_stalled_port_detail(
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


def compose_port_publish_stall_seconds(env: Mapping[str, str] | None) -> float:
    return env_float(env, "ENVCTL_SUPABASE_COMPOSE_PORT_PUBLISH_STALL_SECONDS", 45.0, minimum=5.0)


def compose_unpublished_port_detail(
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
        container_port = published_container_port_for_service(service_name)
        if container_port is None:
            continue
        status = str(service_state.get("status") or "").strip().lower()
        health = str(service_state.get("health") or "").strip().lower()
        container = str(service_state.get("container") or "").strip()
        if not container or status != "running" or health not in {"", "healthy"}:
            continue
        expected_port = expected_host_port_for_service(service_name, compose_root=compose_root)
        if expected_port is None:
            continue
        if bool(process_runner.wait_for_port(expected_port, timeout=0.5)):
            continue
        host_port_label = "API" if is_gateway_service_name(service_name) else "DB"
        return (
            f"Docker Compose stalled before publishing Supabase {host_port_label} host port {expected_port}: "
            f"Docker reported {service_name} running/healthy, but the host socket is not reachable."
        )
    return None


def compose_stalled_port_detail(
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
    public_port = compose_public_port(compose_root=compose_root)
    if public_port is not None and any(is_gateway_service_name(service_name) for service_name in service_names):
        if not bool(process_runner.wait_for_port(public_port, timeout=0.2)):
            return f"Docker Compose stalled before publishing Supabase API host port {public_port}."
    return compose_unpublished_port_detail(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        service_names=service_names,
    )


def published_container_port_for_service(service_name: str) -> int | None:
    normalized = str(service_name or "").strip().lower()
    if normalized in {"supabase-db", "db"}:
        return 5432
    if normalized in {"supabase-kong", "kong", "gateway"}:
        return 8000
    return None


def expected_host_port_for_service(service_name: str, *, compose_root: Path) -> int | None:
    normalized = str(service_name or "").strip().lower()
    if normalized in {"supabase-db", "db"}:
        return compose_db_port(compose_root=compose_root)
    if is_gateway_service_name(normalized):
        return compose_public_port(compose_root=compose_root)
    return None


def is_gateway_service_name(service_name: str) -> bool:
    return str(service_name or "").strip().lower() in {"supabase-kong", "kong", "gateway"}


def is_compose_port_publish_stall(error: str | None) -> bool:
    normalized = " ".join(str(error or "").lower().split())
    return "docker compose stalled before publishing supabase" in normalized


def compose_services_started(
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
    return bool(states) and all(compose_service_state_ready(state) for state in states)


def compose_handoff_ready(
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
    public_port = compose_public_port(compose_root=compose_root)
    if public_port is not None and any(is_gateway_service_name(service_name) for service_name in service_names):
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
    services_ready = all(compose_service_state_ready(state) for state in states)
    if not services_ready:
        return False
    return True


def compose_service_state_ready(service_state: Mapping[str, object]) -> bool:
    status = str(service_state.get("status") or "").strip().lower()
    health = str(service_state.get("health") or "").strip().lower()
    if status != "running":
        return False
    return health in {"", "healthy"}


def terminate_compose_process(process: subprocess.Popen[str]) -> tuple[str, str]:
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


def compose_db_port(*, compose_root: Path) -> int | None:
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


def compose_public_port(*, compose_root: Path) -> int | None:
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


def compose_timeout_recovered(
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
        if compose_service_state_ready(service_state):
            return True
    return False


__all__ = [
    "compose_db_port",
    "compose_handoff_ready",
    "compose_port_publish_stall_seconds",
    "compose_public_port",
    "compose_service_state_ready",
    "compose_services_started",
    "compose_stalled_port_detail",
    "compose_timeout_recovered",
    "compose_unpublished_port_detail",
    "compose_up_handoff",
    "expected_host_port_for_service",
    "is_compose_port_publish_stall",
    "is_gateway_service_name",
    "published_container_port_for_service",
    "terminate_compose_process",
]
