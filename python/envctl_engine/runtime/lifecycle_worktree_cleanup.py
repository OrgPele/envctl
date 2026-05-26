from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from envctl_engine.runtime.lifecycle_requirement_ports import (
    release_requirement_ports,
    requirement_key_for_project,
    requirement_port_values,
)
from envctl_engine.runtime.lifecycle_service_termination import service_port
from envctl_engine.runtime.lifecycle_worktree_containers import (
    legacy_container_name as _legacy_container_name,
)
from envctl_engine.runtime.lifecycle_worktree_containers import (
    remove_tree_containers as _remove_tree_containers,
)
from envctl_engine.runtime.lifecycle_worktree_metadata import (
    cleanup_artifact_paths as _cleanup_artifact_paths,
)
from envctl_engine.runtime.lifecycle_worktree_metadata import (
    prune_project_metadata as _prune_project_metadata,
)
from envctl_engine.runtime.lifecycle_worktree_processes import (
    blast_tree_cwd_processes as _blast_tree_cwd_processes,
)
from envctl_engine.runtime.lifecycle_worktree_processes import (
    blast_tree_listener_ports as _blast_tree_listener_ports,
)
from envctl_engine.state.models import RequirementsResult, RunState
from envctl_engine.state.runtime_map import build_runtime_map

__all__ = [
    "WorktreeCleanupDependencies",
    "_blast_tree_cwd_processes",
    "_blast_tree_listener_ports",
    "_cleanup_artifact_paths",
    "_legacy_container_name",
    "_prune_project_metadata",
    "_remove_tree_containers",
    "blast_worktree_before_delete",
]

CollectRequirementPortsFn = Callable[[RequirementsResult], set[int]]


class PruneProjectMetadataFn(Protocol):
    def __call__(self, state: RunState, *, project_name: str) -> list[Path]: ...


class CleanupArtifactPathsFn(Protocol):
    def __call__(self, runtime: Any, *, project_name: str, paths: set[Path], warnings: list[str]) -> None: ...


class BlastTreeListenerPortsFn(Protocol):
    def __call__(self, runtime: Any, *, project_name: str, ports: set[int], warnings: list[str]) -> None: ...


class BlastTreeCwdProcessesFn(Protocol):
    def __call__(self, runtime: Any, *, project_name: str, project_root: Path, warnings: list[str]) -> None: ...


class RemoveTreeContainersFn(Protocol):
    def __call__(
        self,
        runtime: Any,
        *,
        project_name: str,
        project_root: Path,
        include_supabase: bool,
        remove_named_volumes: bool,
        warnings: list[str],
    ) -> None: ...


def _collect_requirement_ports(requirements: RequirementsResult) -> set[int]:
    return requirement_port_values(requirements)


@dataclass(frozen=True, slots=True)
class WorktreeCleanupDependencies:
    collect_requirement_ports: CollectRequirementPortsFn = _collect_requirement_ports
    prune_project_metadata: PruneProjectMetadataFn = _prune_project_metadata
    cleanup_artifact_paths: CleanupArtifactPathsFn = _cleanup_artifact_paths
    blast_tree_listener_ports: BlastTreeListenerPortsFn = _blast_tree_listener_ports
    blast_tree_cwd_processes: BlastTreeCwdProcessesFn = _blast_tree_cwd_processes
    remove_tree_containers: RemoveTreeContainersFn = _remove_tree_containers


def blast_worktree_before_delete(
    runtime: Any,
    *,
    project_name: str,
    project_root: Path,
    source_command: str = "delete-worktree",
    dependencies: WorktreeCleanupDependencies | None = None,
    collect_requirement_ports_fn: CollectRequirementPortsFn | None = None,
    prune_project_metadata_fn: PruneProjectMetadataFn | None = None,
    cleanup_artifact_paths_fn: CleanupArtifactPathsFn | None = None,
    blast_tree_listener_ports_fn: BlastTreeListenerPortsFn | None = None,
    blast_tree_cwd_processes_fn: BlastTreeCwdProcessesFn | None = None,
    remove_tree_containers_fn: RemoveTreeContainersFn | None = None,
) -> list[str]:
    cleanup = dependencies or WorktreeCleanupDependencies()
    if collect_requirement_ports_fn is not None:
        cleanup = replace(cleanup, collect_requirement_ports=collect_requirement_ports_fn)
    if prune_project_metadata_fn is not None:
        cleanup = replace(cleanup, prune_project_metadata=prune_project_metadata_fn)
    if cleanup_artifact_paths_fn is not None:
        cleanup = replace(cleanup, cleanup_artifact_paths=cleanup_artifact_paths_fn)
    if blast_tree_listener_ports_fn is not None:
        cleanup = replace(cleanup, blast_tree_listener_ports=blast_tree_listener_ports_fn)
    if blast_tree_cwd_processes_fn is not None:
        cleanup = replace(cleanup, blast_tree_cwd_processes=blast_tree_cwd_processes_fn)
    if remove_tree_containers_fn is not None:
        cleanup = replace(cleanup, remove_tree_containers=remove_tree_containers_fn)

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
                target_ports.update(cleanup.collect_requirement_ports(requirement_entry))
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

        artifact_paths.update(cleanup.prune_project_metadata(state, project_name=normalized_project))

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
        cleanup.blast_tree_listener_ports(
            runtime, project_name=normalized_project, ports=target_ports, warnings=warnings
        )
        cleanup.blast_tree_cwd_processes(
            runtime,
            project_name=normalized_project,
            project_root=resolved_root,
            warnings=warnings,
        )
        fingerprint_path_fn = getattr(runtime, "_supabase_fingerprint_path", None)
        if callable(fingerprint_path_fn):
            try:
                fingerprint_path = fingerprint_path_fn(normalized_project)
                filesystem_path = (
                    os.fspath(fingerprint_path) if isinstance(fingerprint_path, os.PathLike) else fingerprint_path
                )
                if isinstance(filesystem_path, str):
                    artifact_paths.add(Path(filesystem_path))
            except Exception:
                pass
        cleanup.cleanup_artifact_paths(
            runtime,
            project_name=normalized_project,
            paths=artifact_paths,
            warnings=warnings,
        )
    elif source_command == "self-destruct-worktree":
        cleanup.blast_tree_cwd_processes(
            runtime,
            project_name=normalized_project,
            project_root=resolved_root,
            warnings=warnings,
        )

    cleanup.remove_tree_containers(
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
