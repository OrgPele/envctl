from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, cast

from envctl_engine.state.models import RequirementsResult, RunState
from envctl_engine.runtime.lifecycle_requirement_ports import (
    release_requirement_ports,
    requirement_key_for_project,
    requirement_port_values,
)
from envctl_engine.runtime.lifecycle_service_termination import (
    service_port,
    terminate_service_record,
    terminate_services_from_state,
    terminate_started_services,
)
from envctl_engine.requirements.common import (
    build_container_name,
    container_exists as _container_exists,
    run_docker,
    run_result_error,
)
from envctl_engine.requirements.supabase import build_supabase_project_name
from envctl_engine.state.runtime_map import build_runtime_map

container_exists = _container_exists

__all__ = [
    "blast_worktree_before_delete",
    "container_exists",
    "release_requirement_ports",
    "requirement_key_for_project",
    "service_port",
    "terminate_service_record",
    "terminate_services_from_state",
    "terminate_started_services",
]


def _collect_requirement_ports(requirements: RequirementsResult) -> set[int]:
    return requirement_port_values(requirements)


def _prune_project_metadata(state: RunState, *, project_name: str) -> list[Path]:
    removed_paths: list[Path] = []
    for metadata_key in ("project_pr_links", "project_roots"):
        raw = state.metadata.get(metadata_key)
        if not isinstance(raw, dict):
            continue
        raw.pop(project_name, None)
        if raw:
            state.metadata[metadata_key] = raw
        else:
            state.metadata.pop(metadata_key, None)

    summaries_raw = state.metadata.get("project_test_summaries")
    if isinstance(summaries_raw, dict):
        entry = summaries_raw.pop(project_name, None)
        if isinstance(entry, dict):
            for path_key in ("summary_path", "short_summary_path", "state_path", "manifest_path"):
                raw_path = str(entry.get(path_key, "") or "").strip()
                if raw_path:
                    removed_paths.append(Path(raw_path))
        if summaries_raw:
            state.metadata["project_test_summaries"] = summaries_raw
        else:
            state.metadata.pop("project_test_summaries", None)
            state.metadata.pop("project_test_results_root", None)
            state.metadata.pop("project_test_results_updated_at", None)
    return removed_paths


def _cleanup_artifact_paths(runtime: Any, *, project_name: str, paths: set[Path], warnings: list[str]) -> None:
    for artifact_path in sorted(paths):
        try:
            if artifact_path.is_file():
                artifact_path.unlink()
                runtime._emit(
                    "cleanup.worktree.artifact.removed",
                    project=project_name,
                    path=str(artifact_path),
                )
        except OSError as exc:
            warning = f"artifact cleanup failed for {project_name} ({artifact_path}): {exc}"
            warnings.append(warning)
            runtime._emit(
                "cleanup.worktree.warning",
                project=project_name,
                path=str(artifact_path),
                warning=warning,
            )
            continue

        parent = artifact_path.parent
        while parent != parent.parent:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


def _blast_tree_listener_ports(runtime: Any, *, project_name: str, ports: set[int], warnings: list[str]) -> None:
    if not ports:
        return
    orchestrator = getattr(runtime, "lifecycle_cleanup_orchestrator", None)
    run_best_effort = getattr(orchestrator, "run_best_effort_command", None)
    looks_like_docker = getattr(orchestrator, "looks_like_docker_process", None)
    process_command = getattr(runtime, "_blast_all_process_command", None)
    kill_pid_tree = getattr(runtime, "_blast_all_kill_pid_tree", None)
    if not callable(run_best_effort) or not callable(process_command) or not callable(kill_pid_tree):
        return

    seen_pids: set[int] = set()
    for port in sorted(ports):
        code, stdout, _stderr = cast(
            tuple[int, str, str],
            run_best_effort(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"], timeout=2.0),
        )
        if code not in {0, 1} or not stdout.strip():
            continue
        for raw_pid in stdout.splitlines():
            raw_pid = raw_pid.strip()
            if not raw_pid.isdigit():
                continue
            pid = int(raw_pid)
            if pid <= 0 or pid in seen_pids:
                continue
            seen_pids.add(pid)
            command_text = str(process_command(pid) or "")
            if callable(looks_like_docker) and looks_like_docker(command_text):
                runtime._emit(
                    "cleanup.worktree.port.skip",
                    project=project_name,
                    pid=pid,
                    port=port,
                    reason="docker_managed",
                )
                continue
            runtime._emit(
                "cleanup.worktree.port.kill",
                project=project_name,
                pid=pid,
                port=port,
            )
            try:
                kill_pid_tree(pid)
            except Exception as exc:  # noqa: BLE001
                warning = f"listener cleanup failed for {project_name} (pid {pid}, port {port}): {exc}"
                warnings.append(warning)
                runtime._emit(
                    "cleanup.worktree.warning",
                    project=project_name,
                    pid=pid,
                    port=port,
                    warning=warning,
                )


def _blast_tree_cwd_processes(runtime: Any, *, project_name: str, project_root: Path, warnings: list[str]) -> None:
    kill_pid_tree = getattr(runtime, "_blast_all_kill_pid_tree", None)
    process_command = getattr(runtime, "_blast_all_process_command", None)
    looks_like_docker = getattr(runtime, "_looks_like_docker_process", None)
    if not callable(kill_pid_tree):
        return

    resolved_root = project_root.resolve()
    seen_pids: set[int] = set()
    skip_pids = {os.getpid(), os.getppid()}
    proc_root = Path("/proc")
    try:
        proc_dirs = list(proc_root.iterdir())
    except FileNotFoundError:
        return

    for proc_dir in proc_dirs:
        raw_pid = proc_dir.name.strip()
        if not raw_pid.isdigit():
            continue
        pid = int(raw_pid)
        if pid <= 0 or pid in skip_pids or pid in seen_pids:
            continue

        try:
            cwd_path = (proc_dir / "cwd").resolve()
        except OSError:
            continue
        if cwd_path != resolved_root and resolved_root not in cwd_path.parents:
            continue

        command_text = ""
        if callable(process_command):
            try:
                command_text = str(process_command(pid) or "")
            except Exception:
                command_text = ""
        if callable(looks_like_docker) and looks_like_docker(command_text):
            runtime._emit(
                "cleanup.worktree.cwd.skip",
                project=project_name,
                pid=pid,
                reason="docker_managed",
            )
            continue

        seen_pids.add(pid)
        runtime._emit(
            "cleanup.worktree.cwd.kill",
            project=project_name,
            pid=pid,
            cwd=str(cwd_path),
        )
        try:
            kill_pid_tree(pid, skip_pids=skip_pids)
        except Exception as exc:  # noqa: BLE001
            warning = f"cwd cleanup failed for {project_name} (pid {pid}): {exc}"
            warnings.append(warning)
            runtime._emit(
                "cleanup.worktree.warning",
                project=project_name,
                pid=pid,
                cwd=str(cwd_path),
                warning=warning,
            )


def _legacy_container_name(*, prefix: str, project_name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", project_name).strip("-").lower() or "project"
    return f"{prefix}-{normalized}"[:63].rstrip("-")


def _remove_tree_containers(
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
        _legacy_container_name(prefix="envctl-postgres", project_name=project_name): "postgres",
        _legacy_container_name(prefix="envctl-redis", project_name=project_name): "redis",
        _legacy_container_name(prefix="envctl-n8n", project_name=project_name): "n8n",
    }
    supabase_prefixes: set[str] = set()
    if include_supabase:
        supabase_prefixes = {
            build_supabase_project_name(project_root=resolved_root, project_name=project_name) + "-",
            _legacy_container_name(prefix="envctl-supabase", project_name=project_name) + "-",
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


def blast_worktree_before_delete(
    runtime: Any,
    *,
    project_name: str,
    project_root: Path,
    source_command: str = "delete-worktree",
) -> list[str]:
    normalized_project = str(project_name).strip()
    if not normalized_project:
        return []

    resolved_root = project_root.resolve()
    warnings: list[str] = []
    target_lower = normalized_project.lower()
    blast_mode = source_command == "blast-worktree"
    target_ports: set[int] = set()
    artifact_paths: set[Path] = set()
    runtime._emit(
        "cleanup.worktree.start",
        project=normalized_project,
        root=str(resolved_root),
        source_command=source_command,
    )

    for mode in ("trees", "main"):
        state = runtime._try_load_existing_state(mode=mode, strict_mode_match=True)
        if state is None:
            continue

        selected_services = {
            name
            for name in list(state.services.keys())
            if runtime._project_name_from_service(name).strip().lower() == target_lower
        }
        for service_name in selected_services:
            service = state.services.get(service_name)
            if service is None:
                continue
            port = service_port(service)
            if port is not None:
                target_ports.add(port)
            log_path_raw = str(getattr(service, "log_path", "") or "").strip()
            if blast_mode and log_path_raw:
                artifact_paths.add(Path(log_path_raw))
        requirement_key = requirement_key_for_project(state, normalized_project)
        if not selected_services and requirement_key is None:
            continue

        runtime._terminate_services_from_state(
            state,
            selected_services=selected_services,
            aggressive=True,
            verify_ownership=False,
        )
        for service_name in selected_services:
            state.services.pop(service_name, None)

        if requirement_key is not None:
            requirement_entry = state.requirements.pop(requirement_key, None)
            if requirement_entry is not None:
                target_ports.update(_collect_requirement_ports(requirement_entry))
                release_requirement_ports(runtime, requirement_entry)

        remaining_projects: set[str] = set()
        for service_name in state.services:
            project = runtime._project_name_from_service(service_name)
            if project:
                remaining_projects.add(project)
        for project in list(state.requirements.keys()):
            if project in remaining_projects:
                continue
            requirement_entry = state.requirements.pop(project)
            release_requirement_ports(runtime, requirement_entry)

        artifact_paths.update(_prune_project_metadata(state, project_name=normalized_project))

        try:
            runtime.state_repository.save_selected_stop_state(
                state=state,
                emit=runtime._emit,
                runtime_map_builder=build_runtime_map,
            )
        except Exception as exc:  # noqa: BLE001
            warning = f"state update failed for {normalized_project} ({mode}): {exc}"
            warnings.append(warning)
            runtime._emit(
                "cleanup.worktree.warning",
                project=normalized_project,
                mode=mode,
                warning=warning,
            )
            continue

        runtime._emit(
            "cleanup.worktree.state.updated",
            project=normalized_project,
            mode=mode,
            services_removed=len(selected_services),
            requirements_removed=(requirement_key is not None),
        )

    if blast_mode:
        _blast_tree_listener_ports(runtime, project_name=normalized_project, ports=target_ports, warnings=warnings)
        _blast_tree_cwd_processes(
            runtime,
            project_name=normalized_project,
            project_root=resolved_root,
            warnings=warnings,
        )
        fingerprint_path_fn = getattr(runtime, "_supabase_fingerprint_path", None)
        if callable(fingerprint_path_fn):
            try:
                fingerprint_path = fingerprint_path_fn(normalized_project)
                if isinstance(fingerprint_path, str | os.PathLike):
                    artifact_paths.add(Path(fingerprint_path))
            except Exception:
                pass
        _cleanup_artifact_paths(runtime, project_name=normalized_project, paths=artifact_paths, warnings=warnings)
    elif source_command == "self-destruct-worktree":
        _blast_tree_cwd_processes(
            runtime,
            project_name=normalized_project,
            project_root=resolved_root,
            warnings=warnings,
        )

    _remove_tree_containers(
        runtime,
        project_name=normalized_project,
        project_root=resolved_root,
        include_supabase=blast_mode,
        remove_named_volumes=blast_mode,
        warnings=warnings,
    )

    runtime._emit(
        "cleanup.worktree.finish",
        project=normalized_project,
        root=str(resolved_root),
        source_command=source_command,
        warnings=len(warnings),
    )
    return warnings
