from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import time
from typing import Protocol

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree
from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.protocols import ProjectContextLike, StartupRuntime
from envctl_engine.startup.session import ImportedStartupContext, StartupSession


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
        try:
            project_contexts = runtime._select_import_project(route, project_contexts)
        except RuntimeError as exc:
            print(str(exc))
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
    if _plan_agent_worktree_handoff_requested(route) and not bool(route.flags.get("dry_run")):
        _prepare_plan_agent_worktrees(session, runtime=runtime, project_contexts=project_contexts)
    session.selected_contexts = list(project_contexts)
    if route.command == "import" and not bool(route.flags.get("dry_run")):
        _record_imported_startup_context(session, runtime=runtime)
    session.contexts_to_start = [] if _local_startup_disabled(route) else list(project_contexts)
    return None


def _plan_agent_worktree_handoff_requested(route: Route) -> bool:
    if bool(route.flags.get("planning_prs")):
        return False
    if route.command == "plan":
        return True
    if route.command != "import":
        return False
    return any(bool(route.flags.get(flag_name)) for flag_name in ("cmux", "tmux", "omx", "codex", "opencode"))


def _local_startup_disabled(route: Route) -> bool:
    return (
        route.flags.get("launch_backend") is False
        and route.flags.get("launch_frontend") is False
        and route.flags.get("launch_dependencies") is False
    )


def _record_imported_startup_context(session: StartupSession, *, runtime: StartupRuntime) -> None:
    planning_orchestrator = getattr(runtime, "planning_worktree_orchestrator", None)
    selection_getter = getattr(planning_orchestrator, "last_import_result", None)
    result = selection_getter() if callable(selection_getter) else None
    ref = getattr(result, "ref", None)
    worktree = getattr(result, "worktree", None)
    if ref is None or worktree is None:
        return
    session.imported_startup_context = ImportedStartupContext(
        remote_ref=str(getattr(ref, "remote_ref", "") or ""),
        local_branch=str(getattr(ref, "local_branch", "") or ""),
        project=str(getattr(worktree, "name", "") or ""),
        worktree_root=str(getattr(worktree, "root", "") or ""),
        action=str(getattr(result, "action", "") or ""),
    )


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
