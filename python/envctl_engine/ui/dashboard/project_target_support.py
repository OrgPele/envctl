from __future__ import annotations

from typing import Any

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState


def apply_commit_selection(owner: Any, route: Route, state: RunState, rt: object) -> Route | None:
    runtime = rt
    selected_route = owner._apply_project_target_selection(route, state, rt)
    if selected_route is None:
        return None
    route = selected_route
    if isinstance(route.flags.get("commit_message"), str) and str(route.flags.get("commit_message")).strip():
        return route
    if (
        isinstance(route.flags.get("commit_message_file"), str)
        and str(route.flags.get("commit_message_file")).strip()
    ):
        return route
    raw = owner._prompt_commit_message(runtime)
    if raw is None:
        print(owner._no_target_selected_message(route.command))
        return None
    message = str(raw).strip()
    if not message:
        return route
    route.flags = {
        **{key: value for key, value in route.flags.items() if key != "commit_message_file"},
        "commit_message": message,
    }
    runtime._emit(
        "dashboard.commit_message.selected",
        command="commit",
        explicit=True,
        length=len(message),
    )
    return route


def dashboard_owned_target_selection_commands() -> set[str]:
    # Commands that already have downstream interactive selectors should not
    # be pre-selected here; otherwise the dashboard changes their contract.
    return {
        "test",
        "pr",
        "commit",
        "review",
        "migrate",
        "blast-worktree",
    }


def dashboard_owned_project_selection_commands() -> set[str]:
    return {"pr", "commit", "review", "migrate", "blast-worktree"}


def apply_project_target_selection(owner: Any, route: Route, state: RunState, rt: object) -> Route | None:
    runtime = rt
    if owner._route_has_explicit_target(route, runtime):
        return route

    projects = owner._project_names_from_state(state, runtime)
    single_project = owner._single_project_name(projects)
    if single_project:
        route.projects = [single_project]
        runtime._emit(
            "dashboard.target_scope.defaulted",
            command=route.command,
            mode=state.mode,
            scope="single_project",
            project_count=1,
            projects=[single_project],
        )
        return route
    selection = runtime._select_project_targets(
        prompt=owner._interactive_target_prompt(route.command),
        projects=projects,
        allow_all=True,
        allow_untested=False,
        multi=True,
    )
    if selection.cancelled:
        print(owner._no_target_selected_message(route.command))
        return None
    if selection.all_selected:
        scoped_projects = [str(getattr(project, "name", "")).strip() for project in projects]
        scoped_projects = [project for project in scoped_projects if project]
        if scoped_projects:
            route.projects = scoped_projects
            route.flags = {key: value for key, value in route.flags.items() if key != "all"}
            runtime._emit(
                "dashboard.target_scope.defaulted",
                command=route.command,
                mode=state.mode,
                scope="run_state_all_selection",
                project_count=len(scoped_projects),
                projects=scoped_projects,
            )
            return route
        route.flags = {**route.flags, "all": True}
        return route
    if selection.project_names:
        route.projects = list(selection.project_names)
        return route
    print(owner._no_target_selected_message(route.command))
    return None
