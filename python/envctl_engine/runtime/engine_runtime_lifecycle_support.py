from __future__ import annotations

from pathlib import Path
from typing import Any

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
from envctl_engine.runtime.lifecycle_worktree_cleanup import (
    _blast_tree_cwd_processes as _blast_tree_cwd_processes_impl,
    _blast_tree_listener_ports as _blast_tree_listener_ports_impl,
    _cleanup_artifact_paths as _cleanup_artifact_paths_impl,
    _legacy_container_name as _legacy_container_name_impl,
    _prune_project_metadata as _prune_project_metadata_impl,
    _remove_tree_containers as _remove_tree_containers_impl,
    blast_worktree_before_delete as _blast_worktree_before_delete_impl,
)
from envctl_engine.requirements.common import (
    container_exists as _container_exists,
)

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
    return _prune_project_metadata_impl(state, project_name=project_name)


def _cleanup_artifact_paths(runtime: Any, *, project_name: str, paths: set[Path], warnings: list[str]) -> None:
    _cleanup_artifact_paths_impl(runtime, project_name=project_name, paths=paths, warnings=warnings)


def _blast_tree_listener_ports(runtime: Any, *, project_name: str, ports: set[int], warnings: list[str]) -> None:
    _blast_tree_listener_ports_impl(runtime, project_name=project_name, ports=ports, warnings=warnings)


def _blast_tree_cwd_processes(runtime: Any, *, project_name: str, project_root: Path, warnings: list[str]) -> None:
    _blast_tree_cwd_processes_impl(runtime, project_name=project_name, project_root=project_root, warnings=warnings)


def _legacy_container_name(*, prefix: str, project_name: str) -> str:
    return _legacy_container_name_impl(prefix=prefix, project_name=project_name)


def _remove_tree_containers(
    runtime: Any,
    *,
    project_name: str,
    project_root: Path,
    include_supabase: bool,
    remove_named_volumes: bool,
    warnings: list[str],
) -> None:
    _remove_tree_containers_impl(
        runtime,
        project_name=project_name,
        project_root=project_root,
        include_supabase=include_supabase,
        remove_named_volumes=remove_named_volumes,
        warnings=warnings,
    )


def blast_worktree_before_delete(
    runtime: Any,
    *,
    project_name: str,
    project_root: Path,
    source_command: str = "delete-worktree",
) -> list[str]:
    return _blast_worktree_before_delete_impl(
        runtime,
        project_name=project_name,
        project_root=project_root,
        source_command=source_command,
        collect_requirement_ports_fn=_collect_requirement_ports,
        prune_project_metadata_fn=_prune_project_metadata,
        cleanup_artifact_paths_fn=_cleanup_artifact_paths,
        blast_tree_listener_ports_fn=_blast_tree_listener_ports,
        blast_tree_cwd_processes_fn=_blast_tree_cwd_processes,
        remove_tree_containers_fn=_remove_tree_containers,
    )
