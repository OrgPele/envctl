from __future__ import annotations

from typing import Any, Callable, Literal, cast

from envctl_engine.actions.project_action_domain import DirtyWorktreeReport
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard.command_input_support import read_interactive_line
from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.textual.screens.selector import _run_selector_with_impl


DirtyPrDecision = Literal["commit", "skip", "cancel"]


def maybe_prepare_pr_commit(owner: Any, route: Route, state: RunState, rt: object) -> tuple[Route | None, RunState]:
    runtime_any = cast(Any, rt)
    dirty_reports = owner._dirty_pr_reports(route, state, runtime_any)
    dirty_targets = [report for report in dirty_reports if report.dirty]
    runtime_any._emit(
        "dashboard.pr_dirty_state",
        command="pr",
        selected_project_count=len(dirty_reports),
        dirty_project_count=len(dirty_targets),
        staged=any(report.staged for report in dirty_targets),
        unstaged=any(report.unstaged for report in dirty_targets),
        untracked=any(report.untracked for report in dirty_targets),
    )
    if not dirty_targets:
        return route, state

    prompt = dirty_pr_prompt(dirty_targets)
    runtime_any._emit(
        "dashboard.pr_dirty_commit.prompt",
        command="pr",
        dirty_project_count=len(dirty_targets),
        staged=any(report.staged for report in dirty_targets),
        unstaged=any(report.unstaged for report in dirty_targets),
        untracked=any(report.untracked for report in dirty_targets),
    )
    decision = owner._prompt_dirty_pr_menu(
        runtime_any,
        title="Commit dirty changes before PR?",
        prompt=prompt,
    )
    if decision == "cancel":
        runtime_any._emit(
            "dashboard.pr_dirty_commit.cancelled",
            command="pr",
            dirty_project_count=len(dirty_targets),
        )
        print("Cancelled PR creation.")
        return None, state
    if decision == "skip":
        runtime_any._emit(
            "dashboard.pr_dirty_commit.declined",
            command="pr",
            dirty_project_count=len(dirty_targets),
        )
        return route, state

    runtime_any._emit("dashboard.pr_dirty_commit.accepted", command="pr", dirty_project_count=len(dirty_targets))
    commit_route = Route(
        command="commit",
        mode=route.mode,
        raw_args=["commit"],
        passthrough_args=[],
        projects=[report.project_name for report in dirty_targets],
        flags={"batch": True, "interactive_command": True},
    )
    commit_route = owner._apply_commit_selection(commit_route, state, runtime_any)
    if commit_route is None:
        runtime_any._emit(
            "dashboard.pr_dirty_commit.cancelled",
            command="pr",
            dirty_project_count=len(dirty_targets),
        )
        return None, state
    code = runtime_any.dispatch(commit_route)
    refreshed = runtime_any._try_load_existing_state(mode=state.mode, strict_mode_match=True)
    next_state = refreshed if refreshed is not None else state
    if code != 0:
        runtime_any._emit("dashboard.pr_dirty_commit.failed", command="pr", dirty_project_count=len(dirty_targets))
        owner._print_interactive_failure_details(commit_route, next_state, code=code)
        return None, next_state
    runtime_any._emit("dashboard.pr_dirty_commit.completed", command="pr", dirty_project_count=len(dirty_targets))
    return route, next_state


def dirty_pr_prompt(dirty_targets: list[DirtyWorktreeReport]) -> str:
    if len(dirty_targets) == 1:
        target = dirty_targets[0]
        return f"UNSTAGED CODE IN WORKTREE {target.project_name} - DO YOU WANT TO STAGE IT?"
    return "UNSTAGED CODE IN SELECTED WORKTREES - DO YOU WANT TO STAGE IT?"


def dirty_categories(report: DirtyWorktreeReport) -> list[str]:
    categories: list[str] = []
    if bool(getattr(report, "staged", False)):
        categories.append("staged changes")
    if bool(getattr(report, "unstaged", False)):
        categories.append("unstaged changes")
    if bool(getattr(report, "untracked", False)):
        categories.append("untracked files")
    return categories


def prompt_dirty_pr_menu(
    runtime: Any,
    *,
    title: str,
    prompt: str,
    run_selector_fn: Callable[..., list[str] | None] = _run_selector_with_impl,
) -> DirtyPrDecision:
    values = run_selector_fn(
        prompt=prompt,
        options=[
            SelectorItem(
                id="dirty-pr:commit",
                label="Commit",
                kind="",
                token="__DIRTY_PR_COMMIT__",
                scope_signature=("dirty-pr:commit",),
            ),
            SelectorItem(
                id="dirty-pr:skip",
                label="Do nothing",
                kind="",
                token="__DIRTY_PR_SKIP__",
                scope_signature=("dirty-pr:skip",),
            ),
        ],
        multi=False,
        initial_tokens=["__DIRTY_PR_COMMIT__"],
        emit=getattr(runtime, "_emit", None),
    )
    if not values:
        return "cancel"
    chosen = str(values[0]).strip()
    if chosen == "__DIRTY_PR_COMMIT__":
        return "commit"
    if chosen == "__DIRTY_PR_SKIP__":
        return "skip"
    return prompt_yes_no_dialog(runtime, title=title, prompt=prompt)


def prompt_yes_no_dialog(runtime: Any, *, title: str, prompt: str) -> DirtyPrDecision:
    confirm = getattr(runtime, "_prompt_yes_no", None)
    if callable(confirm):
        try:
            result = confirm(title=title, prompt=prompt)
        except TypeError:
            result = confirm(prompt)
        if result is None:
            return "cancel"
        return "commit" if bool(result) else "skip"
    response = read_interactive_line(runtime, prompt).strip().lower()
    if response in {"y", "yes"}:
        return "commit"
    if response in {"", "n", "no"}:
        return "skip"
    if response in {"c", "cancel", "q", "quit", "esc", "escape"}:
        return "cancel"
    return "skip"
