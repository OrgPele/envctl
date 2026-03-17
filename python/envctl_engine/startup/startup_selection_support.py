from __future__ import annotations

from pathlib import Path
from typing import Protocol

from envctl_engine.planning import list_planning_files, planning_existing_counts, select_projects_for_plan_files
from envctl_engine.runtime.command_router import MODE_TREE_TOKENS, Route
from envctl_engine.runtime.runtime_context import resolve_port_allocator, resolve_process_runtime
from envctl_engine.shared.protocols import PortAllocator, ProcessRuntime
from envctl_engine.state.models import RunState
from envctl_engine.startup.protocols import ProjectContextLike, StartupRuntime

_MODE_TREE_TOKENS_NORMALIZED = {str(token).strip().lower() for token in MODE_TREE_TOKENS}


class _RuntimeOwner(Protocol):
    runtime: StartupRuntime


def project_ports_text(context: ProjectContextLike) -> str:
    return (
        f"backend={context.ports['backend'].final} "
        f"frontend={context.ports['frontend'].final} "
        f"db={context.ports['db'].final} "
        f"redis={context.ports['redis'].final} "
        f"n8n={context.ports['n8n'].final}"
    )


def state_project_names(*, runtime: StartupRuntime, state: RunState) -> set[str]:
    names = {str(name).strip() for name in state.requirements.keys() if str(name).strip()}
    for service_name in state.services:
        project_name = runtime._project_name_from_service(service_name)
        if isinstance(project_name, str) and project_name.strip():
            names.add(project_name.strip())
    metadata_roots = state.metadata.get("project_roots")
    if isinstance(metadata_roots, dict):
        for project_name in metadata_roots:
            normalized = str(project_name).strip()
            if normalized:
                names.add(normalized)
    return names


def state_matches_selected_projects(
    orchestrator: object, *, runtime: StartupRuntime, state: RunState, contexts: list[ProjectContextLike]
) -> bool:
    _ = orchestrator
    selected = {str(context.name).strip() for context in contexts if str(getattr(context, "name", "")).strip()}
    if not selected:
        return False
    state_projects = state_project_names(runtime=runtime, state=state)
    if not state_projects:
        return False
    return selected == state_projects


def state_covers_selected_projects(
    orchestrator: object, *, runtime: StartupRuntime, state: RunState, contexts: list[ProjectContextLike]
) -> bool:
    _ = orchestrator
    selected = {str(context.name).strip() for context in contexts if str(getattr(context, "name", "")).strip()}
    if not selected:
        return False
    state_projects = state_project_names(runtime=runtime, state=state)
    if not state_projects:
        return False
    return selected.issubset(state_projects)


def _route_explicit_trees_mode(route: Route) -> bool:
    for token in route.raw_args:
        normalized = str(token).strip().lower()
        if normalized in _MODE_TREE_TOKENS_NORMALIZED:
            return True
    return False


def trees_start_selection_required(orchestrator: object, *, route: Route, runtime_mode: str) -> bool:
    _ = orchestrator
    if runtime_mode != "trees" or route.command != "start":
        return False
    if route.projects or route.passthrough_args:
        return False
    if bool(route.flags.get("planning_prs")):
        return False
    if bool(route.flags.get("setup_worktree")) or bool(route.flags.get("setup_worktrees")):
        return False
    return True


def tree_preselected_projects_from_state(
    orchestrator: object, *, runtime: StartupRuntime, project_contexts: list[ProjectContextLike]
) -> list[str]:
    _ = orchestrator
    state = runtime._try_load_existing_state(mode="trees", strict_mode_match=True)
    available = {str(context.name).strip().lower(): str(context.name).strip() for context in project_contexts}
    if state is None:
        return _tree_preselected_projects_from_plans(runtime=runtime, project_contexts=project_contexts)
    preselected: list[str] = []
    seen: set[str] = set()
    for name in sorted(state_project_names(runtime=runtime, state=state)):
        normalized = str(name).strip().lower()
        resolved = available.get(normalized)
        if not resolved:
            continue
        if resolved.lower() in seen:
            continue
        seen.add(resolved.lower())
        preselected.append(resolved)
    if preselected:
        return preselected
    return _tree_preselected_projects_from_plans(runtime=runtime, project_contexts=project_contexts)


def _tree_preselected_projects_from_plans(
    *, runtime: StartupRuntime, project_contexts: list[ProjectContextLike]
) -> list[str]:
    config = getattr(runtime, "config", None)
    planning_dir = getattr(config, "planning_dir", None)
    if not isinstance(planning_dir, Path):
        return []
    try:
        planning_files = list_planning_files(planning_dir)
    except Exception:
        return []
    if not planning_files:
        return []

    projects = [
        (str(context.name).strip(), getattr(context, "root"))
        for context in project_contexts
        if str(getattr(context, "name", "")).strip()
    ]
    existing_counts = planning_existing_counts(projects=projects, planning_files=planning_files)
    plan_counts = {
        plan_file: int(existing_counts.get(plan_file, 0))
        for plan_file in planning_files
        if int(existing_counts.get(plan_file, 0)) > 0
    }
    if not plan_counts:
        return []
    try:
        selected = select_projects_for_plan_files(projects=projects, plan_counts=plan_counts)  # type: ignore[arg-type]
    except Exception:
        return []
    return [name for name, _root in selected if str(name).strip()]


def select_start_tree_projects(
    orchestrator: _RuntimeOwner, *, route: Route, project_contexts: list[ProjectContextLike]
) -> list[ProjectContextLike]:
    runtime = orchestrator.runtime
    if not project_contexts:
        return project_contexts
    can_tty = runtime._can_interactive_tty()
    if not can_tty:
        runtime._emit(
            "trees.start.selector.skipped",
            reason="non_tty",
            discovered_count=len(project_contexts),
        )
        print(
            "No TTY available for tree selection. "
            "Run 'envctl --list-trees --json' and retry with '--project <tree>' or '--headless --plan <selector>'."
        )
        return []

    preselected = tree_preselected_projects_from_state(
        orchestrator,
        runtime=runtime,
        project_contexts=project_contexts,
    )
    runtime._emit(
        "trees.start.selector.prompt",
        discovered_count=len(project_contexts),
        preselected=preselected,
    )
    selection = runtime._select_project_targets(
        prompt="Run worktrees for",
        projects=list(project_contexts),
        allow_all=True,
        allow_untested=False,
        multi=True,
        initial_project_names=preselected,
    )
    if selection.cancelled:
        runtime._emit("trees.start.selector.cancelled", discovered_count=len(project_contexts))
        return []
    if selection.all_selected:
        runtime._emit(
            "trees.start.selector.applied",
            all_selected=True,
            selected_count=len(project_contexts),
            selected=[str(context.name) for context in project_contexts],
        )
        return project_contexts

    selected_names = {str(name).strip().lower() for name in selection.project_names if str(name).strip()}
    if not selected_names:
        runtime._emit("trees.start.selector.empty", discovered_count=len(project_contexts))
        return []
    filtered = [context for context in project_contexts if str(context.name).strip().lower() in selected_names]
    if not filtered:
        runtime._emit(
            "trees.start.selector.miss",
            discovered_count=len(project_contexts),
            selected=sorted(selected_names),
        )
        return []
    runtime._emit(
        "trees.start.selector.applied",
        all_selected=False,
        selected_count=len(filtered),
        selected=[str(context.name) for context in filtered],
    )
    return filtered


def _restart_include_requirements(route: Route) -> bool:
    explicit = route.flags.get("restart_include_requirements")
    if explicit is not None:
        return bool(explicit)
    if bool(route.flags.get("all")):
        return True
    services = route.flags.get("services")
    if isinstance(services, list) and services:
        return False
    if route.projects:
        return False
    return True


def _restart_selected_services(*, state: RunState, route: Route) -> set[str]:
    service_filters = route.flags.get("services")
    selected: set[str] = set()
    if isinstance(service_filters, list):
        filter_set = {str(value).strip() for value in service_filters if str(value).strip()}
        selected.update({name for name in state.services if name in filter_set})
    if selected:
        return selected

    if route.projects:
        project_set = {
            project.strip().lower() for project in route.projects if isinstance(project, str) and project.strip()
        }
        for name in state.services:
            project = _project_name_from_service_name(name)
            if project and project.lower() in project_set:
                selected.add(name)
        if selected:
            return selected

    return set(state.services.keys())


def restart_target_projects(*, state: RunState, route: Route, runtime: StartupRuntime) -> set[str]:
    targets: set[str] = set()
    for value in route.projects:
        if isinstance(value, str) and value.strip():
            targets.add(value.strip())
    if targets:
        return targets

    services = route.flags.get("services")
    if isinstance(services, list):
        for service_name in services:
            if not isinstance(service_name, str):
                continue
            project = _project_name_from_service_name(service_name)
            if project:
                targets.add(project)
    if targets:
        return targets

    for service_name in state.services:
        project = runtime._project_name_from_service(service_name)
        if project:
            targets.add(project)
    return targets


def restart_target_projects_for_selected_services(
    *, selected_services: set[str], state: RunState, runtime: StartupRuntime
) -> set[str]:
    targets: set[str] = set()
    for service_name in selected_services:
        project = runtime._project_name_from_service(service_name)
        if project:
            targets.add(project)
    if targets:
        return targets
    for service_name in state.services:
        project = runtime._project_name_from_service(service_name)
        if project:
            targets.add(project)
    return targets


def _project_name_from_service_name(name: str) -> str | None:
    lowered = str(name).strip().lower()
    if lowered.endswith(" backend"):
        return str(name)[: -len(" Backend")].strip()
    if lowered.endswith(" frontend"):
        return str(name)[: -len(" Frontend")].strip()
    return None


def _restart_service_types_for_project(
    *,
    route: Route | None,
    project_name: str,
    default_service_types: set[str] | None = None,
) -> set[str]:
    if route is None or not bool(route.flags.get("_restart_request")):
        return set(default_service_types or {"backend", "frontend"})

    services_value = route.flags.get("services")
    service_types: set[str] = set()
    if isinstance(services_value, list):
        for raw_name in services_value:
            if not isinstance(raw_name, str):
                continue
            project = _project_name_from_service_name(raw_name)
            if project and project != project_name:
                continue
            lowered = raw_name.strip().lower()
            if lowered.endswith(" backend"):
                service_types.add("backend")
            elif lowered.endswith(" frontend"):
                service_types.add("frontend")
    if service_types:
        return service_types.intersection(default_service_types or service_types)

    explicit_types = route.flags.get("restart_service_types")
    if isinstance(explicit_types, list):
        normalized = {
            str(value).strip().lower()
            for value in explicit_types
            if str(value).strip().lower() in {"backend", "frontend"}
        }
        if normalized:
            return normalized.intersection(default_service_types or normalized)
    return set(default_service_types or {"backend", "frontend"})


def port_allocator(runtime: object) -> PortAllocator:
    return resolve_port_allocator(runtime)


def process_runtime(runtime: object) -> ProcessRuntime:
    return resolve_process_runtime(runtime)


_project_ports_text = project_ports_text
_state_project_names = state_project_names
_state_matches_selected_projects = state_matches_selected_projects
_state_covers_selected_projects = state_covers_selected_projects
_trees_start_selection_required = trees_start_selection_required
_tree_preselected_projects_from_state = tree_preselected_projects_from_state
_select_start_tree_projects = select_start_tree_projects
_restart_target_projects = restart_target_projects
_restart_target_projects_for_selected_services = restart_target_projects_for_selected_services
_port_allocator = port_allocator
_process_runtime = process_runtime
