from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from envctl_engine.actions.project_action_domain import (
    DirtyWorktreeReport,
    probe_dirty_worktree as default_probe_dirty_worktree,
    resolve_git_root,
)
from envctl_engine.planning.plan_agent.cmux_transport import (
    launch_review_agent_terminal as default_launch_review_agent_terminal,
    review_agent_launch_readiness as default_review_agent_launch_readiness,
)
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard import pr_commit_support, pr_scope_support, pr_selection_support, review_tab_support
from envctl_engine.ui.selection_support import (
    no_target_selected_message as selection_no_target_selected_message,
)
from envctl_engine.ui.textual.screens.selector import _run_selector_with_impl


DirtyPrDecision = Literal["commit", "skip", "cancel"]
_REVIEW_TAB_OPEN_TOKEN = "__REVIEW_TAB_OPEN__"
_REVIEW_TAB_SKIP_TOKEN = "__REVIEW_TAB_SKIP__"
_REVIEW_TAB_LAUNCH_FLAG = "dashboard_review_tab_launch"


@dataclass(frozen=True, slots=True)
class DashboardPrDependencies:
    probe_dirty_worktree: Callable[..., DirtyWorktreeReport]
    launch_review_agent_terminal: Callable[..., object]
    review_agent_launch_readiness: Callable[..., object]
    run_selector: Callable[..., list[str] | None]


DEFAULT_DASHBOARD_PR_DEPENDENCIES = DashboardPrDependencies(
    probe_dirty_worktree=default_probe_dirty_worktree,
    launch_review_agent_terminal=default_launch_review_agent_terminal,
    review_agent_launch_readiness=default_review_agent_launch_readiness,
    run_selector=_run_selector_with_impl,
)


apply_pr_selection = pr_selection_support.apply_pr_selection
maybe_prepare_pr_commit = pr_commit_support.maybe_prepare_pr_commit


def dirty_pr_reports(
    owner: Any,
    route: Route,
    state: RunState,
    runtime: Any,
    *,
    dependencies: DashboardPrDependencies = DEFAULT_DASHBOARD_PR_DEPENDENCIES,
) -> list[DirtyWorktreeReport]:
    return pr_scope_support.dirty_pr_reports(
        owner,
        route,
        state,
        runtime,
        probe_dirty_worktree_fn=dependencies.probe_dirty_worktree,
    )


def dedupe_route_projects_by_git_root(owner: Any, route: Route, state: RunState, rt: object) -> Route:
    return pr_scope_support.dedupe_route_projects_by_git_root(
        owner,
        route,
        state,
        rt,
        resolve_git_root_fn=resolve_git_root,
    )


repo_root_from_runtime = pr_scope_support.repo_root_from_runtime
project_roots_for_route = pr_scope_support.project_roots_for_route


def maybe_offer_review_tab_launch(
    owner: Any,
    route: Route,
    state: RunState,
    rt: object,
    *,
    dependencies: DashboardPrDependencies = DEFAULT_DASHBOARD_PR_DEPENDENCIES,
) -> None:
    return review_tab_support.maybe_offer_review_tab_launch(
        owner,
        route,
        state,
        rt,
        launch_review_agent_terminal_fn=dependencies.launch_review_agent_terminal,
        repo_root_from_runtime_fn=repo_root_from_runtime,
    )


def apply_review_tab_launch_selection(
    owner: Any,
    route: Route,
    state: RunState,
    rt: object,
    *,
    dependencies: DashboardPrDependencies = DEFAULT_DASHBOARD_PR_DEPENDENCIES,
) -> Route:
    return review_tab_support.apply_review_tab_launch_selection(
        owner,
        route,
        state,
        rt,
        review_agent_launch_readiness_fn=dependencies.review_agent_launch_readiness,
    )


def review_tab_target(owner: Any, route: Route, state: RunState, runtime: Any) -> tuple[str, Path] | None:
    return review_tab_support.review_tab_target(
        owner,
        route,
        state,
        runtime,
        repo_root_from_runtime_fn=repo_root_from_runtime,
        project_roots_for_route_fn=project_roots_for_route,
        resolve_git_root_fn=resolve_git_root,
    )


review_tab_unavailable_message = review_tab_support.review_tab_unavailable_message
review_bundle_path = review_tab_support.review_bundle_path
dirty_pr_prompt = pr_commit_support.dirty_pr_prompt


def prompt_review_tab_menu(
    runtime: Any,
    *,
    project_name: str,
    dependencies: DashboardPrDependencies = DEFAULT_DASHBOARD_PR_DEPENDENCIES,
) -> DirtyPrDecision:
    prompt = f"Open an origin-side AI review tab for {project_name}?"
    return review_tab_support.prompt_review_tab_menu(
        runtime,
        project_name=project_name,
        run_selector_fn=dependencies.run_selector,
        prompt_yes_no_dialog_fn=lambda runtime_arg: prompt_yes_no_dialog(
            runtime_arg,
            title="Open origin review tab?",
            prompt=prompt,
        ),
    )


dirty_categories = pr_commit_support.dirty_categories


def prompt_dirty_pr_menu(
    runtime: Any,
    *,
    title: str,
    prompt: str,
    dependencies: DashboardPrDependencies = DEFAULT_DASHBOARD_PR_DEPENDENCIES,
) -> DirtyPrDecision:
    return pr_commit_support.prompt_dirty_pr_menu(
        runtime,
        title=title,
        prompt=prompt,
        run_selector_fn=dependencies.run_selector,
    )


prompt_yes_no_dialog = pr_commit_support.prompt_yes_no_dialog
read_interactive_line = pr_commit_support.read_interactive_line
default_pr_base_branch = pr_selection_support.default_pr_base_branch
pr_base_branch_options = pr_selection_support.pr_base_branch_options


def pr_git_root(owner: Any, runtime: Any) -> Path:
    return pr_scope_support.pr_git_root(owner, runtime, resolve_git_root_fn=resolve_git_root)


def run_pr_selection_flow(
    owner: Any,
    *,
    projects: list[object],
    initial_project_names: tuple[str, ...] | list[str],
    default_branch: str,
    runtime: Any,
):
    return pr_selection_support.run_pr_selection_flow(
        owner,
        projects=projects,
        initial_project_names=initial_project_names,
        default_branch=default_branch,
        runtime=runtime,
    )


def single_project_name(projects: list[object]) -> str:
    names = [
        str(getattr(project, "name", "")).strip()
        for project in projects
        if str(getattr(project, "name", "")).strip()
    ]
    if len(names) != 1:
        return ""
    return names[0]


def interactive_target_prompt(command: str) -> str:
    label_map = {
        "stop": "Stop services",
        "test": "Run tests for",
        "logs": "Tail logs for",
        "clear-logs": "Clear logs for",
        "errors": "Errors for",
        "pr": "Create PR for",
        "commit": "Commit changes for",
        "review": "Review changes for",
        "migrate": "Run migrations for",
        "blast-worktree": "Blast and delete worktree for",
    }
    return label_map.get(command, f"Select {command} target")


def no_target_selected_message(command: str) -> str:
    return selection_no_target_selected_message(command, route=None, interactive_allowed=True)
