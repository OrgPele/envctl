from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any, Callable, cast

from envctl_engine.actions.action_git_state_support import detect_pr_base_branch
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard.pr_flow import run_pr_flow
from envctl_engine.ui.dashboard.pr_scope_support import pr_git_root
from envctl_engine.ui.selector_model import SelectorItem


def _dashboard_git_output(git_root: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(git_root), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def _detect_pr_base_branch(git_root: Path) -> str:
    return detect_pr_base_branch(git_root, git_output=_dashboard_git_output)


def apply_pr_selection(owner: Any, route: Route, state: RunState, rt: object) -> Route | None:
    runtime_any = cast(Any, rt)
    default_branch = owner._default_pr_base_branch(runtime_any)
    if owner._route_has_explicit_target(route, runtime_any):
        route.flags = {**route.flags, "pr_base": route.flags.get("pr_base") or default_branch}
        return route

    projects = owner._project_names_from_state(state, runtime_any)
    single_project = owner._single_project_name(projects)
    if single_project:
        route.projects = [single_project]
        runtime_any._emit(
            "dashboard.target_scope.defaulted",
            command="pr",
            mode=state.mode,
            scope="single_project",
            project_count=1,
            projects=[single_project],
        )
    selection_raw = owner._run_pr_selection_flow(
        projects=projects,
        initial_project_names=[single_project] if single_project else (),
        default_branch=default_branch,
        runtime=runtime_any,
    )
    if selection_raw is None:
        print(owner._no_target_selected_message(route.command))
        return None
    selection = cast(Any, selection_raw)
    if selection.cancelled:
        if str(getattr(selection, "cancelled_step", "")).strip().lower() == "branch":
            print("No PR base branch selected.")
        else:
            print(owner._no_target_selected_message(route.command))
        return None
    if selection.project_names:
        route.projects = list(selection.project_names)
    else:
        print(owner._no_target_selected_message(route.command))
        return None
    if not isinstance(selection.base_branch, str) or not selection.base_branch.strip():
        print("No PR base branch selected.")
        return None
    base_branch = selection.base_branch.strip()
    route.flags = {**route.flags, "pr_base": base_branch}
    runtime_any._emit(
        "dashboard.pr_base.selected",
        command="pr",
        base_branch=base_branch,
        explicit=base_branch != default_branch,
    )
    raw = owner._prompt_pr_message(runtime_any)
    if raw is None:
        print(owner._no_target_selected_message(route.command))
        return None
    message = str(raw).strip()
    if message:
        route.flags = {**route.flags, "pr_body": message}
        runtime_any._emit(
            "dashboard.pr_body.selected",
            command="pr",
            explicit=True,
            length=len(message),
        )
    return route


def default_pr_base_branch(
    owner: Any,
    runtime: Any,
    *,
    detect_default_branch_fn: Callable[[Path], str] = _detect_pr_base_branch,
    pr_git_root_fn: Callable[[Any, Any], Path] = pr_git_root,
) -> str:
    git_root = pr_git_root_fn(owner, runtime)
    try:
        default_branch = detect_default_branch_fn(git_root).strip()
    except Exception:
        default_branch = ""
    return default_branch or "main"


def pr_base_branch_options(
    owner: Any,
    runtime: Any,
    *,
    default_branch: str,
    pr_git_root_fn: Callable[[Any, Any], Path] = pr_git_root,
    run_fn: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[SelectorItem]:
    git_root = pr_git_root_fn(owner, runtime)
    listed = run_fn(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads"],
        cwd=str(git_root),
        text=True,
        capture_output=True,
        check=False,
    )
    branch_names = (
        [line.strip() for line in listed.stdout.splitlines() if line.strip()] if listed.returncode == 0 else []
    )
    if default_branch and default_branch not in branch_names:
        branch_names.append(default_branch)
    if not branch_names:
        branch_names = [default_branch or "main"]
    seen: set[str] = set()
    items: list[SelectorItem] = []
    for branch_name in sorted(branch_names, key=str.casefold):
        lowered = branch_name.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        items.append(
            SelectorItem(
                id=f"branch:{branch_name}",
                label=branch_name,
                kind="branch",
                token=branch_name,
                scope_signature=(f"branch:{branch_name}",),
                section="Branches",
            )
        )
    return items


def run_pr_selection_flow(
    owner: Any,
    *,
    projects: list[object],
    initial_project_names: tuple[str, ...] | list[str],
    default_branch: str,
    runtime: Any,
):
    return run_pr_flow(
        projects=projects,
        initial_project_names=initial_project_names,
        branch_options=pr_base_branch_options(owner, runtime, default_branch=default_branch),
        default_branch=default_branch,
        emit=getattr(runtime, "_emit", None),
    )
