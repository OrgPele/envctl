from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from envctl_engine.requirements.common_contracts import build_container_name
from envctl_engine.requirements.docker_runtime import run_docker, run_result_error
from envctl_engine.requirements.supabase import build_supabase_project_name
from envctl_engine.runtime.docker_service_runtime import docker_service_container_name


def legacy_container_name(*, prefix: str, project_name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", project_name).strip("-").lower() or "project"
    return f"{prefix}-{normalized}"[:63].rstrip("-")


def remove_tree_containers(
    runtime: Any,
    *,
    project_name: str,
    project_root: Path,
    include_supabase: bool,
    remove_named_volumes: bool,
    warnings: list[str],
) -> None:
    resolved_root = project_root.resolve()
    if not callable(getattr(runtime.process_runner, "run", None)):
        return
    exact_names = {
        build_container_name(
            prefix="envctl-postgres", project_root=resolved_root, project_name=project_name
        ): "postgres",
        build_container_name(prefix="envctl-redis", project_root=resolved_root, project_name=project_name): "redis",
        build_container_name(prefix="envctl-n8n", project_root=resolved_root, project_name=project_name): "n8n",
        legacy_container_name(prefix="envctl-postgres", project_name=project_name): "postgres",
        legacy_container_name(prefix="envctl-redis", project_name=project_name): "redis",
        legacy_container_name(prefix="envctl-n8n", project_name=project_name): "n8n",
    }
    app_service_names = ["backend", "frontend"]
    app_service_names.extend(
        str(getattr(service, "name", "") or "").strip()
        for service in getattr(getattr(runtime, "config", None), "additional_services", ())
        if str(getattr(service, "name", "") or "").strip()
    )
    for service_name in app_service_names:
        exact_names[
            docker_service_container_name(
                project_name=project_name,
                project_root=resolved_root,
                service_name=service_name,
            )
        ] = service_name
    supabase_prefixes: set[str] = set()
    if include_supabase:
        supabase_prefixes = {
            build_supabase_project_name(project_root=resolved_root, project_name=project_name) + "-",
            legacy_container_name(prefix="envctl-supabase", project_name=project_name) + "-",
        }

    result, error = run_docker(
        runtime.process_runner,
        ["ps", "-a", "--format", "{{.ID}}|{{.Names}}"],
        cwd=resolved_root,
        env=runtime.env,
        timeout=20.0,
    )
    if result is None:
        warning = f"docker cleanup skipped for {project_name}: {error or 'docker unavailable'}"
        warnings.append(warning)
        runtime._emit(
            "cleanup.worktree.warning",
            project=project_name,
            warning=warning,
        )
        return
    if getattr(result, "returncode", 1) != 0:
        warning = f"docker cleanup skipped for {project_name}: {run_result_error(result, 'docker ps failed')}"
        warnings.append(warning)
        runtime._emit(
            "cleanup.worktree.warning",
            project=project_name,
            warning=warning,
        )
        return

    volume_candidates: list[str] = []
    collect_volumes = getattr(runtime, "_collect_container_volume_candidates", None)
    matched = False
    for line in str(getattr(result, "stdout", "") or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 1)
        if len(parts) != 2:
            continue
        cid, name = parts[0].strip(), parts[1].strip()
        service_name = exact_names.get(name)
        if service_name is None and not (
            include_supabase and supabase_prefixes and any(name.startswith(prefix) for prefix in supabase_prefixes)
        ):
            continue
        matched = True
        if service_name is None:
            service_name = "supabase"
        if remove_named_volumes and callable(collect_volumes):
            try:
                collect_volumes(cid, volume_candidates)
            except Exception:
                pass
        rm_result, rm_error = run_docker(
            runtime.process_runner,
            ["rm", "-f", "-v", cid],
            cwd=resolved_root,
            env=runtime.env,
            timeout=60.0,
        )
        if rm_result is None:
            warning = (
                f"failed removing {service_name} container for {project_name} ({name}): "
                f"{rm_error or 'docker unavailable'}"
            )
            warnings.append(warning)
            runtime._emit(
                "cleanup.worktree.warning",
                project=project_name,
                service=service_name,
                container=name,
                warning=warning,
            )
            continue
        if getattr(rm_result, "returncode", 1) != 0:
            error_text = run_result_error(rm_result, f"failed removing {name}")
            if "no such container" in error_text.lower():
                continue
            warning = f"failed removing {service_name} container for {project_name} ({name}): {error_text}"
            warnings.append(warning)
            runtime._emit(
                "cleanup.worktree.warning",
                project=project_name,
                service=service_name,
                container=name,
                warning=warning,
            )
            continue
        runtime._emit(
            "cleanup.worktree.container.removed",
            project=project_name,
            service=service_name,
            container=name,
        )

    if remove_named_volumes:
        for volume_name in volume_candidates:
            volume_result, volume_error = run_docker(
                runtime.process_runner,
                ["volume", "rm", volume_name],
                cwd=resolved_root,
                env=runtime.env,
                timeout=30.0,
            )
            if volume_result is None:
                warning = (
                    f"failed removing Docker volume for {project_name} ({volume_name}): "
                    f"{volume_error or 'docker unavailable'}"
                )
                warnings.append(warning)
                runtime._emit(
                    "cleanup.worktree.warning",
                    project=project_name,
                    volume=volume_name,
                    warning=warning,
                )
                continue
            if getattr(volume_result, "returncode", 1) != 0:
                error_text = run_result_error(volume_result, f"failed removing volume {volume_name}")
                if "no such volume" in error_text.lower():
                    continue
                warning = f"failed removing Docker volume for {project_name} ({volume_name}): {error_text}"
                warnings.append(warning)
                runtime._emit(
                    "cleanup.worktree.warning",
                    project=project_name,
                    volume=volume_name,
                    warning=warning,
                )
                continue
            runtime._emit(
                "cleanup.worktree.volume.removed",
                project=project_name,
                volume=volume_name,
            )

    if not matched:
        runtime._emit(
            "cleanup.worktree.container.none",
            project=project_name,
            root=str(resolved_root),
            include_supabase=include_supabase,
        )
