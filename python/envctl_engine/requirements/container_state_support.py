from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from envctl_engine.requirements.docker_runtime import run_docker, run_result_error
from envctl_engine.shared.protocols import ProcessRuntime


def container_exists(
    process_runner: ProcessRuntime,
    *,
    container_name: str,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[bool, str | None]:
    result, error = run_docker(
        process_runner,
        ["ps", "-a", "--filter", f"name=^/{container_name}$", "--format", "{{.Names}}"],
        cwd=cwd,
        env=env,
    )
    if result is None:
        return False, error
    if getattr(result, "returncode", 1) != 0:
        return False, run_result_error(result, "failed listing container")
    output = (getattr(result, "stdout", "") or "").strip()
    return output == container_name, None


def container_status(
    process_runner: ProcessRuntime,
    *,
    container_name: str,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[str | None, str | None]:
    result, error = run_docker(
        process_runner,
        ["inspect", "-f", "{{.State.Status}}", container_name],
        cwd=cwd,
        env=env,
    )
    if result is None:
        return None, error
    if getattr(result, "returncode", 1) != 0:
        return None, run_result_error(result, "failed inspecting container")
    status = (getattr(result, "stdout", "") or "").strip()
    return status or None, None


def container_state_error(
    process_runner: ProcessRuntime,
    *,
    container_name: str,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[str | None, str | None]:
    result, error = run_docker(
        process_runner,
        ["inspect", "-f", "{{.State.Error}}", container_name],
        cwd=cwd,
        env=env,
    )
    if result is None:
        return None, error
    if getattr(result, "returncode", 1) != 0:
        return None, run_result_error(result, "failed inspecting container state error")
    state_error = (getattr(result, "stdout", "") or "").strip()
    return state_error or None, None


def container_host_port(
    process_runner: ProcessRuntime,
    *,
    container_name: str,
    container_port: int,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[int | None, str | None]:
    inspect_result, inspect_error = run_docker(
        process_runner,
        ["inspect", "-f", "{{json .HostConfig.PortBindings}}", container_name],
        cwd=cwd,
        env=env,
        timeout=10.0,
    )
    if inspect_result is not None and getattr(inspect_result, "returncode", 1) == 0:
        inspected = _parse_port_binding_json(str(getattr(inspect_result, "stdout", "") or ""), container_port)
        if inspected is not None:
            return inspected, None

    result, error = run_docker(
        process_runner,
        ["port", container_name, str(container_port)],
        cwd=cwd,
        env=env,
        timeout=10.0,
    )
    if result is None:
        return None, error
    if getattr(result, "returncode", 1) != 0:
        port_error = run_result_error(result, "failed reading container port mapping")
        if not is_missing_port_mapping_error(port_error):
            return None, port_error

        if inspect_result is None:
            return None, inspect_error
        if getattr(inspect_result, "returncode", 1) != 0:
            return None, port_error
        return None, None
    raw = (getattr(result, "stdout", "") or "").strip()
    if not raw:
        return None, None
    first = raw.splitlines()[0].strip()
    if ":" not in first:
        return None, None
    try:
        return int(first.rsplit(":", 1)[1]), None
    except ValueError:
        return None, None


def _parse_port_binding_json(raw_payload: str, container_port: int) -> int | None:
    payload = raw_payload.strip()
    if not payload:
        return None
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict):
        return None
    binding = decoded.get(f"{container_port}/tcp")
    if not isinstance(binding, list) or not binding:
        return None
    first = binding[0]
    if not isinstance(first, dict):
        return None
    host_port = str(first.get("HostPort", "")).strip()
    if not host_port:
        return None
    try:
        return int(host_port)
    except ValueError:
        return None


def is_missing_port_mapping_error(error: str | None) -> bool:
    if not error:
        return False
    normalized = error.lower()
    tokens = (
        "no public port",
        "not published",
        "port is not exposed",
        "no host port",
    )
    return any(token in normalized for token in tokens)


def stop_and_remove_container(
    process_runner: ProcessRuntime,
    *,
    container_name: str,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> str | None:
    stop_result, stop_error = run_docker(
        process_runner,
        ["stop", container_name],
        cwd=cwd,
        env=env,
    )
    if stop_result is None:
        return stop_error
    if getattr(stop_result, "returncode", 0) not in {0, 1}:
        return run_result_error(stop_result, "failed stopping container")

    rm_result, rm_error = run_docker(
        process_runner,
        ["rm", "-f", container_name],
        cwd=cwd,
        env=env,
    )
    if rm_result is None:
        return rm_error
    if getattr(rm_result, "returncode", 1) != 0:
        return run_result_error(rm_result, "failed removing container")
    return None
