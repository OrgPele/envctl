from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path

from envctl_engine.dashboard_metadata import (
    DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY,
    DASHBOARD_STOPPED_SERVICES_KEY,
    dashboard_project_configured_services_from_metadata,
    normalize_dashboard_service_types,
)
from envctl_engine.planning import list_planning_files, planning_existing_counts, select_projects_for_plan_files
from envctl_engine.runtime.command_router import MODE_TREE_TOKENS, Route
from envctl_engine.runtime.runtime_context import resolve_port_allocator, resolve_process_runtime
from envctl_engine.shared.protocols import PortAllocator, ProcessRuntime
from envctl_engine.shared.services import (
    resolve_service_project_name,
    service_display_name,
    service_matches_selector,
    service_project_name,
    service_slug_from_record,
)
from envctl_engine.state.models import RunState
from envctl_engine.startup.protocols import ProjectContextLike, StartupRuntime

_MODE_TREE_TOKENS_NORMALIZED = {str(token).strip().lower() for token in MODE_TREE_TOKENS}


def project_ports_text(context: ProjectContextLike) -> str:
    return (
        f"backend={context.ports['backend'].final} "
        f"frontend={context.ports['frontend'].final} "
        f"db={context.ports['db'].final} "
        f"redis={context.ports['redis'].final} "
        f"n8n={context.ports['n8n'].final}"
    )


def project_app_ports_text(context: ProjectContextLike) -> str:
    return f"backend={context.ports['backend'].final} frontend={context.ports['frontend'].final}"


def state_project_names(*, runtime: StartupRuntime, state: RunState) -> set[str]:
    requirements = getattr(state, "requirements", {})
    names = {
        str(getattr(requirement, "project", "") or storage_name).strip()
        for storage_name, requirement in requirements.items()
        if str(getattr(requirement, "project", "") or storage_name).strip()
    }
    for service_name, service in getattr(state, "services", {}).items():
        normalized = resolve_service_project_name(
            service_name,
            service,
            project_name_from_service=runtime._project_name_from_service,
        )
        if normalized:
            names.add(normalized)
    metadata = getattr(state, "metadata", {})
    metadata_roots = metadata.get("project_roots") if isinstance(metadata, Mapping) else None
    if isinstance(metadata_roots, dict):
        for project_name in metadata_roots:
            normalized = str(project_name).strip()
            if normalized:
                names.add(normalized)
    if isinstance(metadata, Mapping):
        names.update(dashboard_project_configured_services_from_metadata(metadata))
        raw_stopped = metadata.get(DASHBOARD_STOPPED_SERVICES_KEY)
        if isinstance(raw_stopped, list):
            for item in raw_stopped:
                if not isinstance(item, Mapping):
                    continue
                project_name = str(item.get("project", "") or "").strip()
                if project_name:
                    names.add(project_name)
    if not names and str(getattr(state, "mode", "")).strip().lower() == "main":
        names.add("Main")
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


def trees_start_selection_required(*, route: Route, runtime_mode: str) -> bool:
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
    *, runtime: StartupRuntime, project_contexts: list[ProjectContextLike]
) -> list[str]:
    repository = getattr(runtime, "state_repository", None)
    load_all = getattr(repository, "load_all", None)
    states = [state for state in load_all(mode="trees") if isinstance(state, RunState)] if callable(load_all) else []
    if not states:
        state = runtime._try_load_existing_state(mode="trees", strict_mode_match=True)
        states = [state] if state is not None else []
    available = {str(context.name).strip().lower(): str(context.name).strip() for context in project_contexts}
    if not states:
        return _tree_preselected_projects_from_plans(runtime=runtime, project_contexts=project_contexts)
    preselected: list[str] = []
    seen: set[str] = set()
    active_names = {name for state in states for name in state_project_names(runtime=runtime, state=state)}
    for name in sorted(active_names):
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
    plan_counts = OrderedDict(
        (plan_file, count) for plan_file in planning_files if (count := int(existing_counts.get(plan_file, 0))) > 0
    )
    if not plan_counts:
        return []
    try:
        selected = select_projects_for_plan_files(projects=projects, plan_counts=plan_counts)
    except Exception:
        return []
    return [name for name, _root in selected if str(name).strip()]


def select_start_tree_projects(
    *, runtime: StartupRuntime, route: Route, project_contexts: list[ProjectContextLike]
) -> list[ProjectContextLike]:
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


def restart_include_requirements(route: Route) -> bool:
    explicit = route.flags.get("restart_include_requirements")
    if explicit is not None:
        return bool(explicit)
    runtime_scope = route.flags.get("runtime_scope")
    if runtime_scope in {"backend", "frontend", "fullstack"}:
        return False
    if runtime_scope in {"dependencies", "entire-system"}:
        return True
    launch_dependencies = route.flags.get("launch_dependencies")
    if launch_dependencies is not None:
        return bool(launch_dependencies)
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
    project_keys = {
        str(project).strip().casefold()
        for project in route.projects
        if str(project).strip()
    }

    def in_selected_projects(name: str, service: object) -> bool:
        if not project_keys:
            return True
        project = service_project_name(service) or _project_name_from_service_name(name)
        return bool(project and project.casefold() in project_keys)

    if isinstance(service_filters, list):
        filters = [str(value).strip() for value in service_filters if str(value).strip()]
        for selector in filters:
            selected.update(
                {
                    name
                    for name, service in state.services.items()
                    if (name == selector or service_matches_selector(service, selector))
                    and in_selected_projects(name, service)
                }
            )
        return selected

    explicit_types = route.flags.get("restart_service_types")
    if isinstance(explicit_types, list):
        selected_types = {str(value).strip().lower() for value in explicit_types if str(value).strip()}
        project_set = {
            project.strip().lower() for project in route.projects if isinstance(project, str) and project.strip()
        }
        for name, service in state.services.items():
            project = service_project_name(service) or _project_name_from_service_name(name)
            if project_set and (not project or project.lower() not in project_set):
                continue
            service_type = service_slug_from_record(service)
            if not service_type:
                lowered = str(name).strip().lower()
                if lowered.endswith(" backend"):
                    service_type = "backend"
                elif lowered.endswith(" frontend"):
                    service_type = "frontend"
            if service_type in selected_types:
                selected.add(name)
        return selected
    if selected:
        return selected

    runtime_scope = route.flags.get("runtime_scope")
    if runtime_scope in {"backend", "frontend", "fullstack", "dependencies"}:
        selected_types = {
            "backend",
            "frontend",
        } if runtime_scope == "fullstack" else ({str(runtime_scope)} if runtime_scope != "dependencies" else set())
        return {
            name
            for name, service in state.services.items()
            if service_slug_from_record(service) in selected_types and in_selected_projects(name, service)
        }

    if route.projects:
        project_set = {
            project.strip().lower() for project in route.projects if isinstance(project, str) and project.strip()
        }
        for name, service in state.services.items():
            project = service_project_name(service) or _project_name_from_service_name(name)
            if project and project.lower() in project_set:
                selected.add(name)
        return selected

    return set(state.services.keys())


def restart_target_projects(*, state: RunState, route: Route, runtime: StartupRuntime) -> set[str]:
    targets: set[str] = set()
    known_projects = {name.casefold(): name for name in state_project_names(runtime=runtime, state=state)}
    for value in route.projects:
        if isinstance(value, str) and value.strip():
            normalized = value.strip()
            targets.add(known_projects.get(normalized.casefold(), normalized))
    if targets:
        return targets

    services = route.flags.get("services")
    if isinstance(services, list):
        for selector in services:
            if not isinstance(selector, str):
                continue
            observed = set(
                _observed_service_types_for_selector(
                    state=state,
                    runtime=runtime,
                    selector=selector,
                )
            )
            if observed:
                targets.update(observed)
                continue
            configured_projects = _configured_service_projects_for_selector(
                state=state,
                runtime=runtime,
                selector=selector,
            )
            if len(configured_projects) == 1:
                targets.update(configured_projects)
        return targets

    return state_project_names(runtime=runtime, state=state)


def _stopped_service_projects_for_selector(state: RunState, selector: str) -> set[str]:
    target = str(selector).strip().lower().removeprefix("service:").strip()
    if not target:
        return set()
    metadata = getattr(state, "metadata", {})
    raw_stopped = metadata.get(DASHBOARD_STOPPED_SERVICES_KEY) if isinstance(metadata, Mapping) else None
    if not isinstance(raw_stopped, list):
        return set()
    projects: set[str] = set()
    for item in raw_stopped:
        if not isinstance(item, Mapping):
            continue
        project = str(item.get("project", "") or "").strip()
        name = str(item.get("name", "") or "").strip()
        service_type = str(item.get("type", "") or "").strip().lower()
        candidates = {name.lower(), service_type, service_display_name(service_type).lower()} - {""}
        if project and target in candidates:
            projects.add(project)
    return projects


def _stopped_service_entries(state: RunState) -> list[tuple[str, str, str]]:
    metadata = getattr(state, "metadata", {})
    raw_stopped = metadata.get(DASHBOARD_STOPPED_SERVICES_KEY) if isinstance(metadata, Mapping) else None
    if not isinstance(raw_stopped, list):
        return []
    entries: list[tuple[str, str, str]] = []
    for item in raw_stopped:
        if not isinstance(item, Mapping):
            continue
        project = str(item.get("project", "") or "").strip()
        normalized_types = normalize_dashboard_service_types([item.get("type", "")])
        service_type = normalized_types[0] if normalized_types else ""
        name = str(item.get("name", "") or "").strip()
        if project and service_type:
            entries.append((project, service_type, name))
    return entries


def _additional_service_enabled_for_project(
    service: object,
    *,
    state: RunState,
    project_name: str,
) -> bool:
    mode = str(getattr(state, "mode", "") or "main").strip().lower()
    metadata = getattr(state, "metadata", {})
    roots = metadata.get("project_roots") if isinstance(metadata, Mapping) else None
    project_root = None
    if isinstance(roots, Mapping):
        for raw_project, raw_root in roots.items():
            if str(raw_project).strip().casefold() == project_name.casefold():
                project_root = Path(str(raw_root))
                break
    enabled_for_project = getattr(service, "enabled_for_project_root", None)
    if callable(enabled_for_project) and project_root is not None:
        return bool(enabled_for_project(mode, project_root))
    enabled_for_mode = getattr(service, "enabled_for_mode", None)
    if callable(enabled_for_mode):
        return bool(enabled_for_mode(mode))
    return True


def configured_service_types_for_project(
    *,
    state: RunState,
    runtime: StartupRuntime,
    project_name: str,
) -> set[str]:
    metadata = getattr(state, "metadata", {})
    configured_by_project = (
        dashboard_project_configured_services_from_metadata(metadata)
        if isinstance(metadata, Mapping)
        else {}
    )
    if isinstance(metadata, Mapping) and DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY in metadata:
        snapshot_types: set[str] = set()
        for project, service_types in configured_by_project.items():
            if project.casefold() == project_name.casefold():
                snapshot_types = set(service_types)
                break
        service_enabled = getattr(runtime, "_service_enabled_for_mode", None)
        mode = str(getattr(state, "mode", "") or "main").strip().lower()
        if callable(service_enabled):
            snapshot_types = {
                service_type
                for service_type in snapshot_types
                if service_type not in {"backend", "frontend"}
                or bool(service_enabled(mode, service_type))
            }
        config = getattr(runtime, "config", None)
        if config is not None and hasattr(config, "additional_services"):
            enabled_additional = {
                str(getattr(service, "name", "") or "").strip().lower()
                for service in tuple(getattr(config, "additional_services", ()) or ())
                if str(getattr(service, "name", "") or "").strip()
                and _additional_service_enabled_for_project(
                    service,
                    state=state,
                    project_name=project_name,
                )
            }
            snapshot_types = {
                service_type
                for service_type in snapshot_types
                if service_type in {"backend", "frontend"} or service_type in enabled_additional
            }
        return snapshot_types

    configured: set[str] = set()
    service_enabled = getattr(runtime, "_service_enabled_for_mode", None)
    mode = str(getattr(state, "mode", "") or "main").strip().lower()
    for service_type in ("backend", "frontend"):
        if not callable(service_enabled) or bool(service_enabled(mode, service_type)):
            configured.add(service_type)
    for service in tuple(getattr(getattr(runtime, "config", None), "additional_services", ()) or ()):
        service_type = str(getattr(service, "name", "") or "").strip().lower()
        if service_type and _additional_service_enabled_for_project(
            service,
            state=state,
            project_name=project_name,
        ):
            configured.add(service_type)
    for service_name, service in getattr(state, "services", {}).items():
        project = resolve_service_project_name(
            service_name,
            service,
            project_name_from_service=runtime._project_name_from_service,
        )
        service_type = _service_type_from_record_name(service_name, service)
        if project and project.casefold() == project_name.casefold() and service_type:
            configured.add(service_type)
    for project, service_type, _service_name in _stopped_service_entries(state):
        if project.casefold() == project_name.casefold():
            configured.add(service_type)
    return configured


def _selector_key(selector: str) -> str:
    return str(selector).strip().casefold().removeprefix("service:").strip()


def _selector_matches_service_type(
    selector: str,
    *,
    project_name: str,
    service_type: str,
    service_name: str = "",
) -> bool:
    target = _selector_key(selector)
    if not target:
        return False
    display = service_display_name(service_type)
    candidates = {
        str(service_name).strip().casefold(),
        service_type.casefold(),
        display.casefold(),
        f"{project_name} {display}".strip().casefold(),
    }
    candidates.discard("")
    return target in candidates


def _observed_service_types_for_selector(
    *,
    state: RunState,
    runtime: StartupRuntime,
    selector: str,
) -> dict[str, set[str]]:
    matches: dict[str, set[str]] = {}
    for service_name, service in getattr(state, "services", {}).items():
        project = resolve_service_project_name(
            service_name,
            service,
            project_name_from_service=runtime._project_name_from_service,
        )
        service_type = _service_type_from_record_name(service_name, service)
        if not project or not service_type:
            continue
        configured = configured_service_types_for_project(
            state=state,
            runtime=runtime,
            project_name=project,
        )
        if service_type not in configured:
            continue
        if service_matches_selector(service, selector) or _selector_matches_service_type(
            selector,
            project_name=project,
            service_type=service_type,
            service_name=service_name,
        ):
            matches.setdefault(project, set()).add(service_type)
    for project, service_type, service_name in _stopped_service_entries(state):
        configured = configured_service_types_for_project(
            state=state,
            runtime=runtime,
            project_name=project,
        )
        if service_type in configured and _selector_matches_service_type(
            selector,
            project_name=project,
            service_type=service_type,
            service_name=service_name,
        ):
            matches.setdefault(project, set()).add(service_type)
    return matches


def _configured_service_projects_for_selector(
    *,
    state: RunState,
    runtime: StartupRuntime,
    selector: str,
) -> dict[str, set[str]]:
    matches: dict[str, set[str]] = {}
    for project in sorted(state_project_names(runtime=runtime, state=state), key=str.casefold):
        for service_type in configured_service_types_for_project(
            state=state,
            runtime=runtime,
            project_name=project,
        ):
            if _selector_matches_service_type(
                selector,
                project_name=project,
                service_type=service_type,
            ):
                matches.setdefault(project, set()).add(service_type)
    return matches


def _configured_service_target_projects(
    *,
    state: RunState,
    runtime: StartupRuntime,
    selector: str,
) -> set[str]:
    matching_projects = set(
        _configured_service_projects_for_selector(
            state=state,
            runtime=runtime,
            selector=selector,
        )
    )
    return matching_projects if len(matching_projects) == 1 else set()


def restart_target_projects_for_selected_services(
    *, selected_services: set[str], state: RunState, runtime: StartupRuntime
) -> set[str]:
    targets: set[str] = set()
    for service_name in selected_services:
        service = state.services.get(service_name)
        project = resolve_service_project_name(
            service_name,
            service,
            project_name_from_service=runtime._project_name_from_service,
        )
        if project:
            targets.add(project)
    if targets:
        return targets
    return state_project_names(runtime=runtime, state=state)


def _project_name_from_service_name(name: str) -> str | None:
    lowered = str(name).strip().lower()
    if lowered.endswith(" backend"):
        return str(name)[: -len(" Backend")].strip()
    if lowered.endswith(" frontend"):
        return str(name)[: -len(" Frontend")].strip()
    parts = str(name).strip().rsplit(" ", 1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return parts[0].strip()
    return None


def _service_type_from_record_name(name: str, service: object) -> str:
    service_type = service_slug_from_record(service)
    if service_type:
        return service_type
    lowered = str(name).strip().lower()
    if lowered.endswith(" backend"):
        return "backend"
    if lowered.endswith(" frontend"):
        return "frontend"
    return ""


def _service_filter_types_for_project(
    *, route: Route, project_name: str, configured_service_types: set[str]
) -> set[str]:
    services_value = route.flags.get("services")
    service_types: set[str] = set()
    if not isinstance(services_value, list):
        return service_types
    for raw_name in services_value:
        if not isinstance(raw_name, str):
            continue
        lowered = raw_name.strip().lower()
        if lowered.startswith("service:"):
            lowered = lowered.removeprefix("service:").strip()
        matched_type = False
        for service_type in configured_service_types:
            display = service_display_name(service_type).lower()
            project_display = f"{project_name} {service_display_name(service_type)}".strip().lower()
            if lowered in {service_type, display, project_display}:
                service_types.add(service_type)
                matched_type = True
        if matched_type:
            continue
        project = _project_name_from_service_name(raw_name)
        if project and project != project_name:
            continue
        if lowered.endswith(" backend"):
            service_types.add("backend")
        elif lowered.endswith(" frontend"):
            service_types.add("frontend")
    return service_types


def _expand_service_dependencies(
    service_types: set[str], *, route: Route, project_name: str, additional_services: tuple[object, ...]
) -> set[str]:
    if bool(route.flags.get("ignore_service_deps")):
        return service_types
    expanded = set(service_types)
    service_by_name = {str(getattr(service, "name", "")).strip().lower(): service for service in additional_services}
    emit_dependency = route.flags.get("emit_service_dependency")
    changed = True
    while changed:
        changed = False
        for service_name in list(expanded):
            service = service_by_name.get(service_name)
            if service is None:
                continue
            for dependency in tuple(getattr(service, "depends_on", ()) or ()):  # built-in or additional service only
                dep = str(dependency).strip().lower()
                if dep not in {"backend", "frontend", *service_by_name.keys()}:
                    continue
                if dep in expanded:
                    continue
                expanded.add(dep)
                changed = True
                if callable(emit_dependency):
                    emit_dependency(project=project_name, service=service_name, dependency=dep)
    return expanded


def restart_service_types_by_project(
    *,
    state: RunState,
    route: Route,
    runtime: StartupRuntime,
    target_projects: set[str],
) -> dict[str, set[str]]:
    additional_services = tuple(
        getattr(getattr(runtime, "config", None), "additional_services", ()) or ()
    )
    active_types: dict[str, set[str]] = {}
    for service_name, service in getattr(state, "services", {}).items():
        project = resolve_service_project_name(
            service_name,
            service,
            project_name_from_service=runtime._project_name_from_service,
        )
        service_type = _service_type_from_record_name(service_name, service)
        if project and service_type:
            active_types.setdefault(project.casefold(), set()).add(service_type)

    selectors = route.flags.get("services")
    explicit_types = route.flags.get("restart_service_types")
    selected_by_project: dict[str, set[str]] = {}
    for project in sorted(target_projects, key=str.casefold):
        configured = configured_service_types_for_project(
            state=state,
            runtime=runtime,
            project_name=project,
        )
        selected: set[str]
        if isinstance(selectors, list):
            selected = set()
            for selector in selectors:
                if not isinstance(selector, str) or not selector.strip():
                    continue
                observed = _observed_service_types_for_selector(
                    state=state,
                    runtime=runtime,
                    selector=selector,
                )
                configured_matches = _configured_service_projects_for_selector(
                    state=state,
                    runtime=runtime,
                    selector=selector,
                )
                for candidate_project, service_types in (*observed.items(), *configured_matches.items()):
                    if candidate_project.casefold() == project.casefold():
                        selected.update(service_types)
            selected = _expand_service_dependencies(
                selected,
                route=route,
                project_name=project,
                additional_services=additional_services,
            )
        elif isinstance(explicit_types, list):
            selected = {
                str(service_type).strip().lower()
                for service_type in explicit_types
                if str(service_type).strip()
            }
        else:
            selected = set(active_types.get(project.casefold(), set()))
            runtime_scope = str(route.flags.get("runtime_scope") or "").strip().lower()
            if runtime_scope in {"backend", "frontend"}:
                selected.intersection_update({runtime_scope})
            elif runtime_scope == "fullstack":
                selected.intersection_update({"backend", "frontend"})
            elif runtime_scope == "dependencies":
                selected.clear()
        selected.intersection_update(configured)
        selected_by_project[project] = _apply_startup_service_launch_flags(selected, route=route)
    return selected_by_project


def restart_selected_services_for_type_map(
    *,
    state: RunState,
    runtime: StartupRuntime,
    service_types_by_project: Mapping[str, set[str]],
) -> set[str]:
    selected: set[str] = set()
    type_map = {
        str(project).strip().casefold(): {str(value).strip().lower() for value in service_types}
        for project, service_types in service_types_by_project.items()
        if str(project).strip()
    }
    for service_name, service in getattr(state, "services", {}).items():
        project = resolve_service_project_name(
            service_name,
            service,
            project_name_from_service=runtime._project_name_from_service,
        )
        service_type = _service_type_from_record_name(service_name, service)
        if project and service_type in type_map.get(project.casefold(), set()):
            selected.add(service_name)
    return selected


def _restart_service_types_for_project(
    *,
    route: Route | None,
    project_name: str,
    default_service_types: set[str] | None = None,
    additional_services: tuple[object, ...] = (),
) -> set[str]:
    configured_service_types = set(default_service_types or {"backend", "frontend"})
    if route is None:
        return configured_service_types

    type_map = route.flags.get("_restart_service_types_by_project")
    if isinstance(type_map, Mapping):
        selected: set[str] = set()
        for raw_project, raw_types in type_map.items():
            if str(raw_project).strip().casefold() != project_name.casefold():
                continue
            if isinstance(raw_types, (list, tuple, set, frozenset)):
                selected.update(
                    str(service_type).strip().lower()
                    for service_type in raw_types
                    if str(service_type).strip()
                )
            break
        return _apply_startup_service_launch_flags(
            selected.intersection(configured_service_types),
            route=route,
        )

    services_value = route.flags.get("services")
    if isinstance(services_value, list) and services_value:
        service_types = _service_filter_types_for_project(
            route=route,
            project_name=project_name,
            configured_service_types=configured_service_types,
        )
        if service_types:
            service_types = _expand_service_dependencies(
                service_types,
                route=route,
                project_name=project_name,
                additional_services=additional_services,
            )
            return _apply_startup_service_launch_flags(
                service_types.intersection(configured_service_types or service_types),
                route=route,
            )

    runtime_scope = route.flags.get("runtime_scope")
    if runtime_scope in {"backend", "frontend"}:
        return _apply_startup_service_launch_flags(
            {str(runtime_scope)}.intersection(configured_service_types),
            route=route,
        )
    if runtime_scope == "dependencies":
        return set()
    if runtime_scope in {"fullstack", "entire-system"} and not bool(route.flags.get("_restart_request")):
        return _apply_startup_service_launch_flags(configured_service_types, route=route)

    if not bool(route.flags.get("_restart_request")):
        return _apply_startup_service_launch_flags(configured_service_types, route=route)

    explicit_types = route.flags.get("restart_service_types")
    if isinstance(explicit_types, list):
        normalized = {str(value).strip().lower() for value in explicit_types if str(value).strip().lower()}
        if not normalized:
            return set()
        return _apply_startup_service_launch_flags(
            normalized.intersection(configured_service_types or normalized),
            route=route,
        )
    selected_services = route.flags.get("_restart_selected_services")
    if isinstance(selected_services, list):
        selected_names = {str(value).strip().casefold() for value in selected_services if str(value).strip()}
        selected_types = {
            service_type
            for service_type in configured_service_types
            if f"{project_name} {service_display_name(service_type)}".casefold() in selected_names
        }
        return _apply_startup_service_launch_flags(selected_types, route=route)
    return _apply_startup_service_launch_flags(configured_service_types, route=route)


def _apply_startup_service_launch_flags(service_types: set[str], *, route: Route) -> set[str]:
    if route.flags.get("launch_backend") is False and route.flags.get("launch_frontend") is False:
        return set()
    selected = set(service_types)
    if "launch_backend" in route.flags or "launch_frontend" in route.flags:
        explicitly_selected: set[str] = set()
        if route.flags.get("launch_backend") is True:
            explicitly_selected.add("backend")
        if route.flags.get("launch_frontend") is True:
            explicitly_selected.add("frontend")
        return selected.intersection(explicitly_selected)
    if route.flags.get("launch_backend") is False:
        selected.discard("backend")
    if route.flags.get("launch_frontend") is False:
        selected.discard("frontend")
    return selected


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
_restart_include_requirements = restart_include_requirements
_restart_target_projects = restart_target_projects
_restart_target_projects_for_selected_services = restart_target_projects_for_selected_services
_port_allocator = port_allocator
_process_runtime = process_runtime
