from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from ..common import run_docker
from .compose import _compose_run
from .formatting import _format_auth_service_state
from .inspect import _inspect_auth_gateway_service

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


def _gateway_public_port_mismatch(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    gateway_service: str,
    expected_port: int,
    include_created: bool = False,
) -> dict[str, object] | None:
    if expected_port <= 0:
        return None
    service_state = _inspect_auth_gateway_service(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        service_name=gateway_service,
    )
    container = str(service_state.get("container") or "").strip()
    status = str(service_state.get("status") or "").strip().lower()
    ignored_statuses = {"", "missing", "unknown"}
    if not include_created:
        ignored_statuses.add("created")
    if not container or status in ignored_statuses:
        return None
    configured_port = _container_host_config_port(
        process_runner=process_runner,
        container_name=container,
        container_port=8000,
        cwd=compose_root,
        env=env,
    )
    if configured_port is None:
        return None
    if int(configured_port) == int(expected_port):
        if status == "created" or bool(process_runner.wait_for_port(expected_port, timeout=0.5)):
            return None
        mismatch = dict(service_state)
        mismatch["actual_port"] = "unpublished"
        return mismatch
    mismatch = dict(service_state)
    mismatch["actual_port"] = int(configured_port)
    return mismatch


def _container_host_config_port(
    *,
    process_runner,
    container_name: str,
    container_port: int,
    cwd: Path,
    env: Mapping[str, str] | None,
) -> int | None:
    result, error = run_docker(
        process_runner,
        ["inspect", "-f", "{{json .HostConfig.PortBindings}}", container_name],
        cwd=cwd,
        env=env,
        timeout=10.0,
    )
    if result is None or error is not None or getattr(result, "returncode", 1) != 0:
        return None
    try:
        payload = json.loads(str(getattr(result, "stdout", "") or "").strip() or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    bindings = payload.get(f"{container_port}/tcp")
    if not isinstance(bindings, list) or not bindings:
        return None
    first = bindings[0]
    if not isinstance(first, dict):
        return None
    raw_port = str(first.get("HostPort") or "").strip()
    if not raw_port:
        return None
    try:
        parsed = int(raw_port)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _format_gateway_port_mismatch(mismatch: Mapping[str, object], *, expected_port: int) -> str:
    actual = str(mismatch.get("actual_port") or "unknown").strip()
    base = _format_auth_service_state(mismatch)
    return f"expected_public_port={expected_port} actual_public_port={actual} service_state={base}"


def _recreate_auth_gateway_services(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_names: list[str],
) -> str | None:
    remove_error = _remove_auth_gateway_services(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        service_names=service_names,
    )
    if remove_error is not None:
        return remove_error
    return _compose_run(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=["up", "-d", *service_names],
    )


def _remove_auth_gateway_services(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
    service_names: list[str],
) -> str | None:
    if not service_names:
        return None
    stop_error = _compose_run(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=["stop", *service_names],
    )
    if stop_error is not None:
        return stop_error
    return _compose_run(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        compose_path=compose_path,
        env=env,
        args=["rm", "-f", *service_names],
    )


