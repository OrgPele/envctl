from __future__ import annotations

import concurrent.futures
import os
import signal
from pathlib import Path
from typing import Any

from envctl_engine.state.models import RequirementsResult, RunState
from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.requirements.common import build_container_name, container_exists, run_docker, run_result_error
from envctl_engine.state.runtime_map import build_runtime_map


def terminate_started_services(runtime: Any, services: dict[str, object]) -> None:
    for service in services.values():
        runtime._terminate_service_record(service, aggressive=False, verify_ownership=False)


def terminate_services_from_state(
    runtime: Any,
    state: RunState,
    *,
    selected_services: set[str] | None,
    aggressive: bool,
    verify_ownership: bool,
) -> None:
    work_items: list[tuple[str, object]] = []
    for name, service in state.services.items():
        if selected_services is not None and name not in selected_services:
            continue
        work_items.append((name, service))

    def terminate_one(item: tuple[str, object]) -> tuple[str, bool, int | None]:
        name, service = item
        terminated = runtime._terminate_service_record(service, aggressive=aggressive, verify_ownership=verify_ownership)
        return name, terminated, service_port(service)

    if len(work_items) <= 1:
        results = [terminate_one(item) for item in work_items]
    else:
        worker_count = min(len(work_items), 8)
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
            results = list(pool.map(terminate_one, work_items))

    for _name, terminated, port in results:
        if terminated and port is not None:
            runtime.port_planner.release(port)


def terminate_service_record(runtime: Any, service: object, *, aggressive: bool, verify_ownership: bool) -> bool:
    pid = getattr(service, "pid", None)
    if not isinstance(pid, int) or pid <= 0:
        return True
    if pid in {os.getpid(), os.getppid()}:
        runtime._emit("cleanup.skip", service=getattr(service, "name", "unknown"), pid=pid, reason="self_or_parent")
        return False
    port = service_port(service)
    if verify_ownership:
        if port is None:
            runtime._emit(
                "cleanup.skip",
                service=getattr(service, "name", "unknown"),
                pid=pid,
                reason="missing_port_for_ownership",
            )
            return False
        try:
            is_owner = bool(runtime.process_runner.pid_owns_port(pid, port))
        except Exception:  # noqa: BLE001
            is_owner = False
        if not is_owner:
            runtime._emit("cleanup.skip", service=getattr(service, "name", "unknown"), pid=pid, port=port)
            return False

    try:
        return bool(runtime.process_runner.terminate(pid, term_timeout=0.5 if aggressive else 2.0, kill_timeout=1.0))
    except Exception:  # noqa: BLE001
        pass
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return True
    return True


def service_port(service: object) -> int | None:
    actual = getattr(service, "actual_port", None)
    if isinstance(actual, int) and actual > 0:
        return actual
    requested = getattr(service, "requested_port", None)
    if isinstance(requested, int) and requested > 0:
        return requested
    return None


def release_requirement_ports(runtime: Any, requirements: RequirementsResult) -> None:
    for definition in dependency_definitions():
        component = requirements.component(definition.id)
        if not bool(component.get("enabled", False)):
            continue
        port = component.get("final")
        if isinstance(port, int) and port > 0:
            runtime.port_planner.release(port)


def requirement_key_for_project(state: RunState, project_name: str) -> str | None:
    target = str(project_name).strip().lower()
    if not target:
        return None
    for key in state.requirements:
        if str(key).strip().lower() == target:
            return key
    return None


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

    for service_name, prefix in (
        ("postgres", "envctl-postgres"),
        ("redis", "envctl-redis"),
        ("n8n", "envctl-n8n"),
    ):
        container_name = build_container_name(
            prefix=prefix,
            project_root=resolved_root,
            project_name=normalized_project,
        )
        exists, exists_error = container_exists(
            runtime.process_runner,
            container_name=container_name,
            cwd=resolved_root,
            env=runtime.env,
        )
        if exists_error:
            warning = (
                f"{service_name} cleanup skipped for {normalized_project} "
                f"({container_name}): {exists_error}"
            )
            warnings.append(warning)
            runtime._emit(
                "cleanup.worktree.warning",
                project=normalized_project,
                service=service_name,
                container=container_name,
                warning=warning,
            )
            continue
        if not exists:
            continue

        rm_result, rm_error = run_docker(
            runtime.process_runner,
            ["rm", "-f", "-v", container_name],
            cwd=resolved_root,
            env=runtime.env,
            timeout=60.0,
        )
        if rm_result is None:
            warning = (
                f"failed removing {service_name} container for {normalized_project} "
                f"({container_name}): {rm_error or 'docker unavailable'}"
            )
            warnings.append(warning)
            runtime._emit(
                "cleanup.worktree.warning",
                project=normalized_project,
                service=service_name,
                container=container_name,
                warning=warning,
            )
            continue

        if getattr(rm_result, "returncode", 1) != 0:
            error_text = run_result_error(rm_result, f"failed removing {container_name}")
            if "no such container" in error_text.lower():
                continue
            warning = (
                f"failed removing {service_name} container for {normalized_project} "
                f"({container_name}): {error_text}"
            )
            warnings.append(warning)
            runtime._emit(
                "cleanup.worktree.warning",
                project=normalized_project,
                service=service_name,
                container=container_name,
                warning=warning,
            )
            continue

        runtime._emit(
            "cleanup.worktree.container.removed",
            project=normalized_project,
            service=service_name,
            container=container_name,
        )

    runtime._emit(
        "cleanup.worktree.finish",
        project=normalized_project,
        root=str(resolved_root),
        source_command=source_command,
        warnings=len(warnings),
    )
    return warnings
