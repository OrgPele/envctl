from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

from envctl_engine.actions.actions_test import default_test_commands
from envctl_engine.dashboard_metadata import normalize_dashboard_service_types
from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.services import (
    project_name_from_service_name,
    service_display_name,
    service_project_name,
    service_slug_from_record,
)
from envctl_engine.startup.startup_selection_support import (
    _tree_preselected_projects_from_state as _tree_preselected_projects_from_state_impl,
)
from envctl_engine.state.models import RunState
from envctl_engine.test_output.failure_summary import summary_excerpt_from_entry
from envctl_engine.ui.dashboard.restart_selection_support import (
    dashboard_configured_missing_services_by_project,
    dashboard_project_configured_services,
)
from envctl_engine.ui.selection_support import (
    project_names_from_state as selection_project_names_from_state,
    route_has_explicit_target as selection_route_has_explicit_target,
    service_types_from_service_names as selection_service_types_from_service_names,
    SimpleProject,
)


def default_interactive_targets(route: Route, state: RunState, rt: object) -> Route:
    _ = state, rt
    return route


def route_has_explicit_target(route: Route, runtime: object) -> bool:
    return selection_route_has_explicit_target(route, cast(Any, runtime))


def apply_interactive_target_selection(owner: Any, route: Route, state: RunState, rt: object) -> Route | None:
    if route.command == "restart":
        return route
    if route.command == "pr":
        return owner._apply_pr_selection(route, state, rt)
    if route.command == "commit":
        return owner._apply_commit_selection(route, state, rt)
    if route.command not in owner._dashboard_owned_target_selection_commands():
        return route

    if route.command in owner._dashboard_owned_project_selection_commands():
        selected_route = owner._apply_project_target_selection(route, state, rt)
        if selected_route is None:
            return None
        if selected_route.command == "review":
            return owner._apply_review_tab_launch_selection(selected_route, state, rt)
        return selected_route

    runtime_any = cast(Any, rt)
    if owner._route_has_explicit_target(route, runtime_any):
        return route

    projects = owner._project_names_from_state(state, runtime_any)
    selected_projects = owner._select_dashboard_projects(
        command=route.command,
        state=state,
        projects=projects,
        runtime=runtime_any,
    )
    if selected_projects is None:
        print(owner._no_target_selected_message(route.command))
        return None
    route.projects = list(selected_projects)

    selected_service_types = owner._select_dashboard_service_types(
        command=route.command,
        state=state,
        selected_projects=selected_projects,
        runtime=runtime_any,
    )
    if selected_service_types is None:
        print(owner._no_target_selected_message(route.command))
        return None

    if route.command == "test":
        apply_dashboard_test_target_selection(
            owner,
            route,
            state,
            runtime_any,
            selected_projects=selected_projects,
            selected_service_types=selected_service_types,
        )
    return route


def apply_dashboard_test_target_selection(
    owner: Any,
    route: Route,
    state: RunState,
    runtime: Any,
    *,
    selected_projects: list[str],
    selected_service_types: list[str],
) -> None:
    route.flags = {
        key: value
        for key, value in route.flags.items()
        if key not in {"backend", "frontend", "services", "failed"}
    }
    if any(service_type == "failed" for service_type in selected_service_types):
        route.flags["failed"] = True
        return
    selected_service_names = owner._service_names_for_projects_and_types(
        state,
        runtime,
        project_names=selected_projects,
        service_types=selected_service_types,
    )
    if selected_service_names:
        route.flags["services"] = selected_service_names
    selected_types = set(selected_service_types)
    if selected_types == {"backend"}:
        route.flags = {**route.flags, "backend": True, "frontend": False}
    elif selected_types == {"frontend"}:
        route.flags = {**route.flags, "backend": False, "frontend": True}


def restart_service_types_from_service_names(service_names: list[str]) -> list[str]:
    types: list[str] = []
    seen: set[str] = set()
    for name in service_names:
        normalized = str(name).strip().lower()
        if normalized.endswith(" backend"):
            service_type = "backend"
        elif normalized.endswith(" frontend"):
            service_type = "frontend"
        else:
            service_type = str(name).strip().lower().removeprefix("service:")
        if service_type and service_type not in seen:
            seen.add(service_type)
            types.append(service_type)
    return types


def service_types_from_service_names(service_names: list[str]) -> set[str]:
    return selection_service_types_from_service_names(service_names)


def dashboard_project_names_from_state(state: RunState, rt: object) -> list[object]:
    return selection_project_names_from_state(cast(Any, rt), state)


def project_name_list(projects: list[object]) -> list[str]:
    return [name for name in (str(getattr(project, "name", "")).strip() for project in projects) if name]


def select_dashboard_projects(
    owner: Any,
    *,
    command: str,
    state: RunState,
    projects: list[object],
    runtime: Any,
) -> list[str] | None:
    project_names = owner._project_name_list(projects)
    single_project = owner._single_project_name(projects)
    if single_project:
        runtime._emit(
            "dashboard.target_scope.defaulted",
            command=command,
            mode=state.mode,
            scope="single_project",
            project_count=1,
            projects=[single_project],
        )
        return [single_project]
    initial_project_names = owner._dashboard_preselected_projects(
        state=state,
        projects=projects,
        runtime=runtime,
    )
    selection = runtime._select_project_targets(
        prompt=owner._worktree_prompt(command),
        projects=projects,
        allow_all=False,
        allow_untested=False,
        multi=True,
        initial_project_names=initial_project_names,
    )
    if selection.cancelled:
        return None
    selected = [name for name in selection.project_names if name]
    return selected or project_names


def dashboard_preselected_projects(
    *,
    state: RunState,
    projects: list[object],
    runtime: Any,
    tree_preselected_projects_fn: Callable[..., list[str]] = _tree_preselected_projects_from_state_impl,
) -> list[str]:
    if str(state.mode).strip().lower() != "trees":
        return []
    startup = getattr(runtime, "startup_orchestrator", None)
    if startup is None:
        return []
    try:
        return list(
            tree_preselected_projects_fn(
                runtime=runtime,
                project_contexts=cast(Any, projects),
            )
        )
    except Exception:
        return []


def select_dashboard_service_types(
    owner: Any,
    *,
    command: str,
    state: RunState,
    selected_projects: list[str],
    runtime: Any,
) -> list[str] | None:
    if command == "test":
        return owner._select_dashboard_test_scope(
            state=state,
            selected_projects=selected_projects,
            runtime=runtime,
        )
    available_types = owner._available_service_types_for_projects(
        state,
        runtime,
        project_names=selected_projects,
    )
    all_tests_available = command == "test" and owner._all_tests_scope_available(
        state,
        runtime,
        project_names=selected_projects,
    )
    failed_scope_available = command == "test" and owner._failed_test_scope_available(
        state,
        project_names=selected_projects,
    )
    if (
        len(available_types) <= 1
        and not failed_scope_available
        and not (all_tests_available and not available_types)
    ):
        return list(available_types)
    default_service_names = [service_type.title() for service_type in available_types]
    initial_service_names = list(default_service_names)
    if all_tests_available and not available_types:
        default_service_names.append("All tests")
        initial_service_names.append("All tests")
    if failed_scope_available:
        default_service_names.append("All failed tests")
        if not initial_service_names:
            initial_service_names.append("All failed tests")
    selection = runtime._select_project_targets(
        prompt=owner._service_prompt(command),
        projects=[SimpleProject(name=label) for label in default_service_names],
        allow_all=False,
        allow_untested=False,
        multi=True,
        initial_project_names=initial_service_names,
    )
    if selection.cancelled:
        return None
    selected_types: list[str] = []
    for name in selection.project_names:
        normalized = name.strip().lower()
        if not normalized:
            continue
        if normalized == "all tests":
            selected_types.append("all")
            continue
        if normalized == "all failed tests":
            selected_types.append("failed")
            continue
        selected_types.append(normalized)
    return selected_types or list(available_types)


def select_dashboard_test_scope(
    owner: Any,
    *,
    state: RunState,
    selected_projects: list[str],
    runtime: Any,
) -> list[str] | None:
    available_types = owner._available_service_types_for_projects(
        state,
        runtime,
        project_names=selected_projects,
    )
    all_tests_available = owner._all_tests_scope_available(
        state,
        runtime,
        project_names=selected_projects,
    )
    failed_scope_available = owner._failed_test_scope_available(
        state,
        project_names=selected_projects,
    )
    if (
        len(available_types) <= 1
        and not failed_scope_available
        and not (all_tests_available and not available_types)
    ):
        return list(available_types)
    options: list[str] = []
    initial_names: list[str] = []
    for service_type in available_types:
        label = service_type.title()
        options.append(label)
        initial_names.append(label)
    if all_tests_available and not available_types:
        options.append("All tests")
        initial_names.append("All tests")
    if failed_scope_available:
        options.append("Failed tests")
    if not options:
        return []
    if len(options) == 1:
        only = options[0].strip().lower()
        if only == "all tests":
            return ["all"]
        if only == "failed tests":
            return ["failed"]
        return [only]
    selection = runtime._select_project_targets(
        prompt=owner._service_prompt("test"),
        projects=[SimpleProject(name=label) for label in options],
        allow_all=False,
        allow_untested=False,
        multi=True,
        initial_project_names=initial_names,
        exclusive_project_name="Failed tests" if failed_scope_available else None,
    )
    if selection.cancelled:
        return None
    chosen_types = [str(name).strip().lower() for name in selection.project_names if str(name).strip()]
    if not chosen_types:
        return None
    if "failed tests" in chosen_types:
        return ["failed"]
    if "all tests" in chosen_types:
        return ["all"]
    return [name for name in chosen_types if name in {"backend", "frontend"}]


def all_tests_scope_available(
    state: RunState,
    runtime: Any,
    *,
    project_names: list[str],
) -> bool:
    if not project_names:
        return False
    metadata = state.metadata if isinstance(state.metadata, dict) else {}
    project_roots_raw = metadata.get("project_roots")
    project_roots = project_roots_raw if isinstance(project_roots_raw, dict) else {}
    repo_root = Path(str(getattr(getattr(runtime, "config", None), "base_dir", Path.cwd())))
    for project_name in project_names:
        root_raw = str(project_roots.get(project_name, "") or "").strip()
        project_root = repo_root if not root_raw else Path(root_raw)
        if not project_root.is_absolute():
            project_root = repo_root / project_root
        try:
            if default_test_commands(project_root):
                return True
        except Exception:
            continue
    return False


def failed_test_scope_available(state: RunState, *, project_names: list[str]) -> bool:
    metadata = state.metadata.get("project_test_summaries")
    if not isinstance(metadata, dict):
        return False
    requested = {name.casefold() for name in project_names}
    for project_name, entry in metadata.items():
        if requested and str(project_name).casefold() not in requested:
            continue
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status", "") or "").strip().lower()
        if status == "passed":
            continue
        for key in ("failed_tests", "failed_manifest_entries"):
            raw_count = entry.get(key)
            with suppress(TypeError, ValueError):
                if int(str(raw_count)) > 0:
                    return True
        if summary_excerpt_from_entry(entry, max_lines=1):
            return True
        if str(entry.get("manifest_path", "") or "").strip():
            return True
        if str(entry.get("short_summary_path", "") or "").strip():
            return True
        if str(entry.get("summary_path", "") or "").strip():
            return True
        if status == "failed":
            return True
    return False


def available_service_types_for_projects(
    state: RunState,
    runtime: Any,
    *,
    project_names: list[str],
) -> list[str]:
    requested = {name.casefold() for name in project_names}
    ordered: list[str] = []
    seen: set[str] = set()
    for service_name, service in state.services.items():
        project_name = service_project_name(service)
        if not project_name:
            project_name = str(runtime._project_name_from_service(service_name) or "").strip()
        if not project_name:
            project_name = str(project_name_from_service_name(str(service_name))).strip()
        if requested and project_name.casefold() not in requested:
            continue
        service_type = service_slug_from_record(service) if service is not None else ""
        if service_type and service_type not in seen:
            seen.add(service_type)
            ordered.append(service_type)
    for project_name, service_types in dashboard_project_configured_services(state).items():
        if requested and project_name.casefold() not in requested:
            continue
        for normalized in sorted(service_types):
            if normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
    if ordered:
        return ordered
    for normalized in normalize_dashboard_service_types(state.metadata.get("dashboard_configured_service_types")):
        if normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def service_names_for_projects_and_types(
    state: RunState,
    runtime: Any,
    *,
    project_names: list[str],
    service_types: list[str],
) -> list[str]:
    requested_projects = {name.casefold() for name in project_names}
    requested_types = {name.casefold() for name in service_types}
    selected: list[str] = []
    seen_names: set[str] = set()
    for service_name, service in state.services.items():
        project_name = service_project_name(service)
        if not project_name:
            project_name = str(runtime._project_name_from_service(service_name) or "").strip()
        if not project_name:
            project_name = str(project_name_from_service_name(str(service_name))).strip()
        if requested_projects and project_name.casefold() not in requested_projects:
            continue
        service_type = service_slug_from_record(service) if service is not None else ""
        if service_type and service_type.casefold() in requested_types:
            selected.append(service_name)
            seen_names.add(str(service_name))
    configured_missing_services = dashboard_configured_missing_services_by_project(state)
    for project_name, missing_service_types in configured_missing_services.items():
        if requested_projects and project_name.casefold() not in requested_projects:
            continue
        for service_type in sorted(missing_service_types):
            if service_type.casefold() not in requested_types:
                continue
            service_name = f"{project_name} {service_display_name(service_type)}"
            if service_name in seen_names:
                continue
            selected.append(service_name)
            seen_names.add(service_name)
    return selected


def worktree_prompt(command: str) -> str:
    prompt_map = {
        "test": "Choose worktrees to test",
        "restart": "Choose worktrees",
    }
    return prompt_map.get(command, "Choose worktrees")


def service_prompt(command: str) -> str:
    prompt_map = {
        "test": "Choose test scope",
        "restart": "Choose services",
    }
    return prompt_map.get(command, "Choose services")
