from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from ..adapter_base import env_bool
from ..docker_runtime import run_docker, run_result_error


def _is_docker_address_pool_exhaustion(error: str | None) -> bool:
    return "all predefined address pools have been fully subnetted" in str(error or "").lower()


def _is_docker_network_missing(error: str | None) -> bool:
    normalized = " ".join(str(error or "").lower().split())
    if not normalized:
        return False
    if (
        "failed to set up container networking" in normalized
        and "network" in normalized
        and "not found" in normalized
    ):
        return True
    return bool(re.search(r"\bnetwork\s+[0-9a-f]{12,64}\s+not\s+found\b", normalized))


def _recover_missing_supabase_network_for_project(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    compose_path: Path,
    env: Mapping[str, str] | None,
) -> tuple[bool, str | None]:
    down_result, down_error = run_docker(
        process_runner,
        ["compose", "-p", compose_project_name, "-f", str(compose_path), "down", "--remove-orphans"],
        cwd=compose_root,
        env=env,
        timeout=60.0,
    )
    if down_result is not None and getattr(down_result, "returncode", 1) == 0:
        return True, "compose_down_remove_orphans"

    down_detail = down_error
    if down_result is not None and getattr(down_result, "returncode", 1) != 0:
        down_detail = run_result_error(down_result, "docker compose down --remove-orphans failed")

    removed_count, cleanup_error = _remove_empty_supabase_networks_for_project(
        process_runner=process_runner,
        compose_root=compose_root,
        compose_project_name=compose_project_name,
        env=env,
    )
    if removed_count > 0:
        detail = f"current_project_empty_networks_removed={removed_count}"
        if cleanup_error:
            detail = f"{detail}; cleanup_error={cleanup_error}"
        return True, detail

    if cleanup_error:
        return False, f"compose_down_error={down_detail}; network_cleanup_error={cleanup_error}"
    if _global_empty_network_recovery_enabled(env):
        global_count, global_error = _remove_empty_envctl_supabase_networks(
            process_runner=process_runner,
            compose_root=compose_root,
            env=env,
        )
        if global_count > 0:
            detail = f"global_empty_networks_removed={global_count}"
            if global_error:
                detail = f"{detail}; cleanup_error={global_error}"
            return True, detail
        if global_error:
            return False, f"compose_down_error={down_detail}; global_cleanup_error={global_error}"
    return False, f"compose_down_error={down_detail or 'unknown'}; no current-project empty Supabase networks removed"


def _remove_empty_supabase_networks_for_project(
    *,
    process_runner,
    compose_root: Path,
    compose_project_name: str,
    env: Mapping[str, str] | None,
) -> tuple[int, str | None]:
    def include_network(network_name: str) -> bool:
        if not network_name.startswith(f"{compose_project_name}_"):
            return False
        suffix = network_name[len(compose_project_name) :]
        return suffix in {"_default", "_supabase-net"}

    return _remove_empty_docker_networks(
        process_runner=process_runner,
        compose_root=compose_root,
        env=env,
        include_network=include_network,
    )


def _global_empty_network_recovery_enabled(env: Mapping[str, str] | None) -> bool:
    return env_bool(env, "ENVCTL_SUPABASE_NETWORK_RECOVERY_ALLOW_GLOBAL_EMPTY_CLEANUP", False)


def _remove_empty_envctl_supabase_networks(
    *,
    process_runner,
    compose_root: Path,
    env: Mapping[str, str] | None,
) -> tuple[int, str | None]:
    return _remove_empty_docker_networks(
        process_runner=process_runner,
        compose_root=compose_root,
        env=env,
        include_network=lambda network_name: network_name.startswith("envctl-supabase-"),
    )


def _remove_empty_docker_networks(
    *,
    process_runner,
    compose_root: Path,
    env: Mapping[str, str] | None,
    include_network,
) -> tuple[int, str | None]:
    result, run_error = run_docker(
        process_runner,
        ["network", "ls", "--format", "{{.Name}}"],
        cwd=compose_root,
        env=env,
        timeout=20.0,
    )
    if result is None:
        return 0, run_error or "docker network ls failed"
    if getattr(result, "returncode", 1) != 0:
        return 0, run_result_error(result, "docker network ls failed")

    names = [line.strip() for line in str(getattr(result, "stdout", "") or "").splitlines() if line.strip()]
    cleanup_errors: list[str] = []
    removed_count = 0
    for network_name in names:
        if not bool(include_network(network_name)):
            continue
        inspect_result, inspect_error = run_docker(
            process_runner,
            ["network", "inspect", "-f", "{{len .Containers}}", network_name],
            cwd=compose_root,
            env=env,
            timeout=20.0,
        )
        if inspect_result is None:
            cleanup_errors.append(inspect_error or f"failed inspecting Docker network {network_name}")
            continue
        if getattr(inspect_result, "returncode", 1) != 0:
            cleanup_errors.append(run_result_error(inspect_result, f"failed inspecting Docker network {network_name}"))
            continue
        try:
            container_count = int(str(getattr(inspect_result, "stdout", "") or "").strip() or "0")
        except ValueError:
            cleanup_errors.append(f"failed inspecting Docker network {network_name}: invalid container count")
            continue
        if container_count != 0:
            continue
        rm_result, rm_error = run_docker(
            process_runner,
            ["network", "rm", network_name],
            cwd=compose_root,
            env=env,
            timeout=20.0,
        )
        if rm_result is None:
            cleanup_errors.append(rm_error or f"failed removing empty Docker network {network_name}")
            continue
        if getattr(rm_result, "returncode", 1) != 0:
            cleanup_errors.append(run_result_error(rm_result, f"failed removing empty Docker network {network_name}"))
            continue
        removed_count += 1

    return removed_count, "; ".join(cleanup_errors) if cleanup_errors else None

