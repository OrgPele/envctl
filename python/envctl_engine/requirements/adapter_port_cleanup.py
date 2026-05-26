from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from .adapter_policy import env_bool
from .container_state_support import stop_and_remove_container
from .docker_runtime import run_docker, run_result_error


def bind_safe_cleanup_enabled(env: Mapping[str, str] | None, *, service_name: str) -> bool:
    global_default = env_bool(env, "ENVCTL_REQUIREMENT_BIND_SAFE_CLEANUP", False)
    service_key = f"ENVCTL_REQUIREMENT_{service_name.upper()}_BIND_SAFE_CLEANUP"
    return env_bool(env, service_key, global_default)


def cleanup_envctl_owned_port_containers(
    *,
    process_runner: object,
    project_root: Path,
    env: Mapping[str, str] | None,
    port: int,
    allowed_prefixes: tuple[str, ...],
) -> tuple[bool, str | None]:
    result, error = run_docker(
        process_runner,
        ["ps", "-a", "--filter", f"publish={port}", "--format", "{{.Names}}"],
        cwd=project_root,
        env=env,
    )
    if result is None:
        return False, error
    if getattr(result, "returncode", 1) != 0:
        return False, run_result_error(result, "failed listing bind-conflict containers")
    raw = str(getattr(result, "stdout", "") or "")
    candidates = [line.strip() for line in raw.splitlines() if line.strip()]
    removable = sorted({name for name in candidates if any(name.startswith(prefix) for prefix in allowed_prefixes)})
    if not removable:
        return False, None
    for container_name in removable:
        cleanup_error = stop_and_remove_container(
            process_runner,
            container_name=container_name,
            cwd=project_root,
            env=env,
        )
        if cleanup_error:
            return False, cleanup_error
    return True, None


def format_bind_conflict_guidance(service_name: str, port: int, error: str | None) -> str:
    detail = (error or "bind conflict").strip() or "bind conflict"
    return (
        f"{detail}. Unable to acquire port {port} for {service_name}. "
        "Resolve the conflict manually or run with ENVCTL_REQUIREMENT_BIND_SAFE_CLEANUP=true "
        "to allow safe cleanup of envctl-owned stale containers, then retry."
    )


def wait_for_port_ready(process_runner: object, port: int, *, timeout: float) -> bool:
    waiter = getattr(process_runner, "wait_for_port", None)
    if not callable(waiter):
        return False
    try:
        return bool(waiter(port, timeout=timeout))
    except TypeError:
        return bool(waiter(port))


__all__ = tuple(name for name in globals() if not name.startswith("_"))
