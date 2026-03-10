from __future__ import annotations

from typing import Any

from envctl_engine.runtime.command_router import MODE_TREE_TOKENS, Route
from envctl_engine.state.models import RunState

_MODE_TREE_TOKENS_NORMALIZED = {str(token).strip().lower() for token in MODE_TREE_TOKENS}

def _project_ports_text(context: Any) -> str:
    return (
        f"backend={context.ports['backend'].final} "
        f"frontend={context.ports['frontend'].final} "
        f"db={context.ports['db'].final} "
        f"redis={context.ports['redis'].final} "
        f"n8n={context.ports['n8n'].final}"
    )

def _state_project_names(*, runtime: Any, state: RunState) -> set[str]:
    names = {str(name).strip() for name in state.requirements.keys() if str(name).strip()}
    for service_name in state.services:
        project_name = runtime._project_name_from_service(service_name)  # type: ignore[attr-defined]
        if isinstance(project_name, str) and project_name.strip():
            names.add(project_name.strip())
    return names

def _state_matches_selected_projects(orchestrator, *, runtime: Any, state: RunState, contexts: list[Any]) -> bool:
    selected = {str(context.name).strip() for context in contexts if str(getattr(context, "name", "")).strip()}
    if not selected:
        return False
    state_projects = _state_project_names(runtime=runtime, state=state)
    if not state_projects:
        return False
    return selected == state_projects


def _state_covers_selected_projects(orchestrator, *, runtime: Any, state: RunState, contexts: list[Any]) -> bool:
    selected = {str(context.name).strip() for context in contexts if str(getattr(context, "name", "")).strip()}
    if not selected:
        return False
    state_projects = _state_project_names(runtime=runtime, state=state)
    if not state_projects:
        return False
    return selected.issubset(state_projects)

def _route_explicit_trees_mode(route: Route) -> bool:
    for token in route.raw_args:
        normalized = str(token).strip().lower()
        if normalized in _MODE_TREE_TOKENS_NORMALIZED:
            return True
    return False

def _trees_start_selection_required(orchestrator, *, route: Route, runtime_mode: str) -> bool:
    if runtime_mode != "trees" or route.command != "start":
        return False
    if route.projects or route.passthrough_args:
        return False
    if bool(route.flags.get("planning_prs")):
        return False
    if bool(route.flags.get("setup_worktree")) or bool(route.flags.get("setup_worktrees")):
        return False
    return True

def _tree_preselected_projects_from_state(orchestrator, *, runtime: Any, project_contexts: list[Any]) -> list[str]:
    state = runtime._try_load_existing_state(mode="trees", strict_mode_match=True)  # type: ignore[attr-defined]
    if state is None:
        return []
    available = {str(context.name).strip().lower(): str(context.name).strip() for context in project_contexts}
    preselected: list[str] = []
    seen: set[str] = set()
    for name in sorted(_state_project_names(runtime=runtime, state=state)):
        normalized = str(name).strip().lower()
        resolved = available.get(normalized)
        if not resolved:
            continue
        if resolved.lower() in seen:
            continue
        seen.add(resolved.lower())
        preselected.append(resolved)
    return preselected

def _select_start_tree_projects(orchestrator, *, route: Route, project_contexts: list[Any]) -> list[Any]:
    rt: Any = orchestrator.runtime
    if not project_contexts:
        return project_contexts
    can_tty = bool(getattr(rt, "_can_interactive_tty", lambda: False)())  # type: ignore[call-arg]
    if not can_tty:
        rt._emit(
            "trees.start.selector.skipped",
            reason="non_tty",
            discovered_count=len(project_contexts),
        )
        print(
            "No TTY available for tree selection. "
            "Run 'envctl --list-trees --json' and retry with '--project <tree>' or '--headless --plan <selector>'."
        )
        return []

    preselected = _tree_preselected_projects_from_state(
        orchestrator,
        runtime=rt,
        project_contexts=project_contexts,
    )
    rt._emit(
        "trees.start.selector.prompt",
        discovered_count=len(project_contexts),
        preselected=preselected,
    )
    selection = rt._select_project_targets(
        prompt="Run worktrees for",
        projects=list(project_contexts),
        allow_all=True,
        allow_untested=False,
        multi=True,
        initial_project_names=preselected,
    )
    if selection.cancelled:
        rt._emit("trees.start.selector.cancelled", discovered_count=len(project_contexts))
        return []
    if selection.all_selected:
        rt._emit(
            "trees.start.selector.applied",
            all_selected=True,
            selected_count=len(project_contexts),
            selected=[str(context.name) for context in project_contexts],
        )
        return project_contexts

    selected_names = {str(name).strip().lower() for name in selection.project_names if str(name).strip()}
    if not selected_names:
        rt._emit("trees.start.selector.empty", discovered_count=len(project_contexts))
        return []
    filtered = [context for context in project_contexts if str(context.name).strip().lower() in selected_names]
    if not filtered:
        rt._emit(
            "trees.start.selector.miss",
            discovered_count=len(project_contexts),
            selected=sorted(selected_names),
        )
        return []
    rt._emit(
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
        project_set = {project.strip().lower() for project in route.projects if isinstance(project, str) and project.strip()}
        for name in state.services:
            project = _project_name_from_service_name(name)
            if project and project.lower() in project_set:
                selected.add(name)
        if selected:
            return selected

    return set(state.services.keys())

def _restart_target_projects(*, state: RunState, route: Route, runtime: Any) -> set[str]:
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
        project = runtime._project_name_from_service(service_name)  # type: ignore[attr-defined]
        if project:
            targets.add(project)
    return targets

def _restart_target_projects_for_selected_services(*, selected_services: set[str], state: RunState, runtime: Any) -> set[str]:
    targets: set[str] = set()
    for service_name in selected_services:
        project = runtime._project_name_from_service(service_name)  # type: ignore[attr-defined]
        if project:
            targets.add(project)
    if targets:
        return targets
    for service_name in state.services:
        project = runtime._project_name_from_service(service_name)  # type: ignore[attr-defined]
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

def _port_allocator(runtime: Any) -> Any:
    runtime_context = getattr(runtime, "runtime_context", None)
    candidate = getattr(runtime_context, "port_allocator", None)
    if candidate is None:
        candidate = getattr(runtime, "port_planner", None)
    return candidate

def _process_runtime(runtime: Any) -> Any:
    runtime_context = getattr(runtime, "runtime_context", None)
    candidate = getattr(runtime_context, "process_runtime", None)
    if candidate is None:
        candidate = getattr(runtime, "process_runner", None)
    return candidate
