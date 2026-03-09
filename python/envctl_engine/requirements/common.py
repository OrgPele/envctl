from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(slots=True)
class RetryResult:
    success: bool
    port: int
    attempts: int
    failure: str | None = None


@dataclass(slots=True)
class ContainerStartResult:
    success: bool
    container_name: str
    error: str | None = None
    reason_code: str | None = None
    failure_class: str | None = None
    stage_events: list[dict[str, object]] | None = None
    stage_durations_ms: dict[str, float] | None = None
    command_timings: list[dict[str, object]] | None = None
    probe_attempts: list[dict[str, object]] | None = None
    docker_command_count: int = 0
    probe_attempt_count: int = 0
    listener_wait_ms: float = 0.0
    container_reused: bool = False
    container_recreated: bool = False
    effective_port: int | None = None
    port_adopted: bool = False
    port_mismatch_requested_port: int | None = None
    port_mismatch_existing_port: int | None = None
    port_mismatch_action: str | None = None


def is_bind_conflict(error: str | None) -> bool:
    if not error:
        return False
    lower = error.lower()
    return (
        "address already in use" in lower
        or "bind" in lower
        or "port is already allocated" in lower
        or "published host port missing" in lower
        or "host port binding incomplete" in lower
    )


def run_with_retry(*, initial_port: int, start: Callable[[int], tuple[bool, str | None]], reserve_next: Callable[[int], int], max_retries: int = 3) -> RetryResult:
    port = initial_port
    attempts = 0
    while attempts < max_retries:
        attempts += 1
        success, error = start(port)
        if success:
            return RetryResult(success=True, port=port, attempts=attempts)
        if not is_bind_conflict(error):
            return RetryResult(success=False, port=port, attempts=attempts, failure=error or "unknown")
        port = reserve_next(port + 1)
    return RetryResult(success=False, port=port, attempts=attempts, failure="retry_limit")


def build_container_name(*, prefix: str, project_root: Path, project_name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", project_name).strip("-").lower() or "project"
    digest = hashlib.sha1(str(project_root).encode("utf-8")).hexdigest()[:8]
    separator = "-"
    suffix = f"{separator}{digest}"
    base_prefix = f"{prefix}{separator}"
    max_len = 63
    available = max_len - len(base_prefix) - len(suffix)
    if available <= 0:
        return f"{prefix[: max_len - len(suffix)].rstrip(separator)}{suffix}".rstrip(separator)
    trimmed = normalized[:available].rstrip(separator) or "project"
    return f"{base_prefix}{trimmed}{suffix}"[:max_len].rstrip(separator)


def run_docker(
    process_runner,
    args: list[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = 60.0,
) -> tuple[object | None, str | None]:
    try:
        result = process_runner.run(
            ["docker", *args],
            cwd=cwd,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return None, f"Command timed out after {timeout:.1f}s: {' '.join(exc.cmd if isinstance(exc.cmd, list) else ['docker', *args])}"
    except OSError as exc:
        return None, f"docker unavailable: {exc}"
    return result, None


def run_result_error(result: object, fallback: str) -> str:
    stderr = getattr(result, "stderr", "")
    stdout = getattr(result, "stdout", "")
    returncode = getattr(result, "returncode", 1)
    text = (stderr or stdout or f"exit:{returncode}").strip()
    return text or fallback


def container_exists(
    process_runner,
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
    process_runner,
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
    process_runner,
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
    process_runner,
    *,
    container_name: str,
    container_port: int,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[int | None, str | None]:
    def _parse_port_binding_json(raw_payload: str) -> int | None:
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

    result, error = run_docker(
        process_runner,
        ["port", container_name, str(container_port)],
        cwd=cwd,
        env=env,
    )
    if result is None:
        return None, error
    if getattr(result, "returncode", 1) != 0:
        port_error = run_result_error(result, "failed reading container port mapping")
        if not is_missing_port_mapping_error(port_error):
            return None, port_error

        # `docker port` returns "no public port..." for stopped containers even if
        # HostConfig still has the published mapping. Inspect fallback preserves reuse.
        inspect_result, inspect_error = run_docker(
            process_runner,
            ["inspect", "-f", "{{json .HostConfig.PortBindings}}", container_name],
            cwd=cwd,
            env=env,
        )
        if inspect_result is None:
            return None, inspect_error
        if getattr(inspect_result, "returncode", 1) != 0:
            return None, port_error
        inspected = _parse_port_binding_json(str(getattr(inspect_result, "stdout", "") or ""))
        return inspected, None
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
    process_runner,
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
