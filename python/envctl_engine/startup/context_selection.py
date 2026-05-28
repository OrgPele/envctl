from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
import time
from typing import Protocol, cast

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree, PlanSelectionResult, PlanWorktreeSyncResult
from envctl_engine.planning.worktree_import_commands import list_importable_origin_branches
from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.protocols import ProjectContextLike, StartupRuntime
from envctl_engine.startup.session import StartupSession


class SelectStartTreeProjects(Protocol):
    def __call__(
        self, *, runtime: StartupRuntime, route: Route, project_contexts: list[ProjectContextLike]
    ) -> list[ProjectContextLike]: ...


def select_startup_contexts(
    *,
    runtime: StartupRuntime,
    session: StartupSession,
    trees_start_selection_required: Callable[..., bool],
    select_start_tree_projects: SelectStartTreeProjects,
    apply_restart_ports: Callable[[StartupSession, list[ProjectContextLike]], None],
    emit_phase: Callable[..., None],
    emit_snapshot: Callable[..., None],
) -> int | None:
    route = session.effective_route
    runtime_mode = session.runtime_mode
    selection_started = time.monotonic()
    project_contexts = runtime._discover_projects(mode=runtime_mode)
    if route.command == "plan":
        project_contexts = runtime._select_plan_projects(route, project_contexts)
    elif route.command == "import":
        project_contexts = _select_imported_worktree(
            session,
            runtime=runtime,
            discovered_project_contexts=project_contexts,
        )
        if not project_contexts:
            return 1
    elif trees_start_selection_required(route=route, runtime_mode=runtime_mode):
        project_contexts = select_start_tree_projects(runtime=runtime, route=route, project_contexts=project_contexts)
    else:
        try:
            project_contexts = runtime._apply_setup_worktree_selection(route, project_contexts)
        except RuntimeError as exc:
            print(str(exc))
            return 1
    if route.projects:
        allow = {project.lower() for project in route.projects}
        project_contexts = [ctx for ctx in project_contexts if ctx.name.lower() in allow]
    apply_restart_ports(session, project_contexts)
    duplicate_error = runtime._duplicate_project_context_error(project_contexts)
    if duplicate_error:
        emit_phase(session, "project_selection", selection_started, status="error")
        print(duplicate_error)
        runtime._emit("planning.projects.duplicate", error=duplicate_error)
        return 1
    emit_phase(
        session,
        "project_selection",
        selection_started,
        status="ok",
        project_count=len(project_contexts),
    )
    emit_snapshot(
        session,
        "plan_selector_exit",
        command=route.command,
        mode=runtime_mode,
        project_count=len(project_contexts),
        projects=[context.name for context in project_contexts],
    )
    if not project_contexts:
        if trees_start_selection_required(route=route, runtime_mode=runtime_mode):
            print("No worktrees selected.")
        else:
            print("No projects discovered for selected mode.")
        return 1
    if (
        route.command in {"plan", "import"}
        and not bool(route.flags.get("planning_prs"))
        and not bool(route.flags.get("dry_run"))
    ):
        _prepare_plan_agent_worktrees(session, runtime=runtime, project_contexts=project_contexts)
    session.selected_contexts = list(project_contexts)
    session.contexts_to_start = list(project_contexts)
    return None


def _select_imported_worktree(
    session: StartupSession,
    *,
    runtime: StartupRuntime,
    discovered_project_contexts: list[ProjectContextLike],
) -> list[ProjectContextLike]:
    route = session.effective_route
    branch_input = next((arg.strip() for arg in route.passthrough_args if arg.strip()), "")
    planning_orchestrator = getattr(runtime, "planning_worktree_orchestrator", None)
    importer = getattr(planning_orchestrator, "import_remote_branch_worktree", None)
    if not branch_input:
        selected_branch = _select_import_branch_from_tty(
            runtime=runtime,
            route=route,
            discovered_project_contexts=discovered_project_contexts,
        )
        if selected_branch is None:
            return []
        branch_input = selected_branch
    if not branch_input or not callable(importer):
        print("--import requires a remote branch argument.")
        return []
    result = cast(PlanWorktreeSyncResult, importer(branch_input=branch_input))
    if result.error:
        print(result.error)
        return []
    project_contexts = runtime._contexts_from_raw_projects(list(result.raw_projects))
    setattr(
        planning_orchestrator,
        "_last_plan_selection_result",
        PlanSelectionResult(
            raw_projects=list(result.raw_projects),
            selected_contexts=list(project_contexts),
            created_worktrees=result.created_worktrees,
            error=result.error,
        ),
    )
    return list(project_contexts)


def _select_import_branch_from_tty(
    *,
    runtime: StartupRuntime,
    route: Route,
    discovered_project_contexts: list[ProjectContextLike],
) -> str | None:
    if route.flags.get("batch") or not runtime._can_interactive_tty():
        if route.flags.get("batch"):
            print("--import requires a remote branch argument when running headless.")
        else:
            print("--import requires a remote branch argument.")
        return None

    repo_root = Path(runtime.config.base_dir)
    branches = list_importable_origin_branches(
        repo_root=repo_root,
        trees_dir_name=str(getattr(runtime.config, "trees_dir_name", "trees")),
        discovered_projects=discovered_project_contexts,
    )
    if not branches:
        print("No importable origin branches found.")
        return None

    projects = cast(
        list[ProjectContextLike],
        [
            SimpleNamespace(name=branch, root=repo_root / "refs" / "remotes" / "origin" / branch, ports={})
            for branch in branches
        ],
    )
    runtime._emit("planning.import.selector.prompt", discovered_count=len(branches))
    selection = runtime._select_project_targets(
        prompt="Import remote branch",
        projects=projects,
        allow_all=False,
        allow_untested=False,
        multi=False,
        initial_project_names=None,
    )
    if selection.cancelled:
        runtime._emit("planning.import.selector.cancelled", discovered_count=len(branches))
        return None
    selected = next((str(name).strip() for name in selection.project_names if str(name).strip()), "")
    if not selected:
        runtime._emit("planning.import.selector.empty", discovered_count=len(branches))
        return None
    if selected not in set(branches):
        runtime._emit("planning.import.selector.miss", discovered_count=len(branches), selected=selected)
        return None
    runtime._emit("planning.import.selector.applied", selected=selected)
    return selected


def _prepare_plan_agent_worktrees(
    session: StartupSession,
    *,
    runtime: StartupRuntime,
    project_contexts: list[ProjectContextLike],
) -> None:
    route = session.effective_route
    planning_orchestrator = getattr(runtime, "planning_worktree_orchestrator", None)
    selection_getter = getattr(planning_orchestrator, "last_plan_selection_result", None)
    if not callable(selection_getter):
        return
    session.plan_agent_launch_requested = True
    selection_result = selection_getter()
    selected_names = {context.name for context in project_contexts}
    created_worktrees = tuple(
        worktree
        for worktree in getattr(selection_result, "created_worktrees", ())
        if isinstance(worktree, CreatedPlanWorktree) and worktree.name in selected_names
    )
    explicit_plan_agent_launch = any(
        bool(route.flags.get(flag_name)) for flag_name in ("cmux", "tmux", "omx", "codex", "opencode")
    )
    if not created_worktrees and explicit_plan_agent_launch:
        created_worktrees = tuple(
            CreatedPlanWorktree(
                name=context.name,
                root=Path(context.root),
                plan_file="",
            )
            for context in project_contexts
        )
    session.pending_plan_agent_worktrees = created_worktrees
