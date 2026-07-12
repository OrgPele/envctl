from __future__ import annotations

from typing import Any, cast

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.lifecycle_service_termination import unconfirmed_service_names
from envctl_engine.state.lookup import call_state_loader
from envctl_engine.state.models import RequirementsResult, RunState
from envctl_engine.state.runtime_map import build_runtime_map


def clear_runtime_state(
    owner: Any,
    *,
    command: str,
    aggressive: bool = False,
    route: Route | None = None,
) -> bool:
    """Reconcile repository-wide stop and blast state."""

    rt = owner.runtime
    if command == "stop-all":
        rt._emit("cleanup.stop_all", aggressive=aggressive)
    elif aggressive:
        rt._emit("cleanup.blast", aggressive=aggressive)
    else:
        rt._emit("cleanup.stop", aggressive=aggressive)
    state_repository = owner._state_repository(rt)
    load_all = getattr(state_repository, "load_all", None)
    mode_filter = None
    if command == "stop-all" and route is not None and rt._state_lookup_strict_mode_match(route):
        mode_filter = route.mode
    if callable(load_all):
        states = [state for state in load_all(mode=mode_filter) if isinstance(state, RunState)]
    else:
        states = []
    if not states:
        state = call_state_loader(
            rt._try_load_existing_state,
            mode=mode_filter,
            strict_mode_match=mode_filter is not None,
        )
        states = [state] if isinstance(state, RunState) else []
    seen_run_ids: set[str] = set()
    failed_by_run: dict[str, set[str]] = {}
    failed_requirements_by_run: dict[str, set[str]] = {}
    for state in states:
        if state.run_id in seen_run_ids:
            continue
        seen_run_ids.add(state.run_id)
        termination_result = rt._terminate_services_from_state(
            state,
            selected_services=None,
            aggressive=aggressive,
            verify_ownership=not aggressive,
        )
        failed_services = unconfirmed_service_names(termination_result, set(state.services))
        state.services = {name: service for name, service in state.services.items() if name in failed_services}
        if failed_services:
            failed_by_run[state.run_id] = failed_services
        failed_projects = {
            project_name
            for name, service in state.services.items()
            if (project_name := owner._project_name_for_service(name, service))
        }
        requirements_to_release: list[tuple[str, RequirementsResult]] = []
        retained_requirements: dict[str, RequirementsResult] = {}
        for storage_key, requirements in state.requirements.items():
            requirement_project = owner._requirement_project_key(storage_key, requirements)
            if failed_projects and requirement_project in failed_projects:
                retained_requirements[storage_key] = requirements
                continue
            containers_stopped = owner._stop_requirement_containers(
                requirements,
                best_effort=command in {"stop-all", "blast-all"},
            )
            if not containers_stopped:
                retained_requirements[storage_key] = requirements
                failed_requirements_by_run.setdefault(state.run_id, set()).add(
                    str(getattr(requirements, "project", "") or storage_key).strip() or storage_key
                )
            else:
                requirements_to_release.append((storage_key, requirements))

        for storage_key, requirements in requirements_to_release:
            if owner._release_requirement_ports_best_effort(requirements):
                continue
            retained_requirements[storage_key] = requirements
            failed_requirements_by_run.setdefault(state.run_id, set()).add(
                str(getattr(requirements, "project", "") or storage_key).strip() or storage_key
            )

        state.requirements = retained_requirements
        if state.services or state.requirements:
            state_repository.save_selected_stop_state(
                state=state,
                emit=rt._emit,
                runtime_map_builder=lambda raw_state: build_runtime_map(cast(RunState, raw_state)),
            )
        else:
            owner._deactivate_runtime_state(state, release_session_when_empty=False)

    if failed_by_run or failed_requirements_by_run:
        rt._emit(
            "cleanup.incomplete",
            failed_services={run_id: sorted(names) for run_id, names in failed_by_run.items()},
            failed_requirements={run_id: sorted(names) for run_id, names in failed_requirements_by_run.items()},
        )
        return False

    if aggressive and owner.blast_all_ecosystem_enabled():
        owner.blast_all_ecosystem_cleanup(route=route)
    elif command == "stop-all" and route is not None and bool(route.flags.get("stop_all_remove_volumes")):
        rt._emit("cleanup.stop_all.remove_volumes", requested=True)
        volume_route = Route(
            command=route.command,
            mode=route.mode,
            raw_args=route.raw_args,
            passthrough_args=route.passthrough_args,
            projects=route.projects,
            flags={
                **route.flags,
                "blast_keep_worktree_volumes": False,
                "blast_remove_main_volumes": True,
            },
        )
        removed = owner.blast_all_docker_cleanup(route=volume_route)
        rt._emit("cleanup.stop_all.remove_volumes.finish", removed=removed)

    if aggressive or command != "stop-all" or not owner._has_active_runs(state_repository):
        owner._purge_runtime_state(aggressive=aggressive)
    repository = owner._state_repository(rt)
    if aggressive and getattr(repository, "compat_mode", None) == getattr(
        repository,
        "COMPAT_READ_WRITE",
        "compat_read_write",
    ):
        owner.blast_all_purge_legacy_state_artifacts()
    return True
