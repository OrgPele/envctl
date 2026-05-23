from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any, Literal, cast

from envctl_engine.actions.project_action_domain import (
    DirtyWorktreeReport,
    detect_default_branch,
    probe_dirty_worktree,
    resolve_git_root,
)
from envctl_engine.planning.plan_agent.cmux_transport import launch_review_agent_terminal, review_agent_launch_readiness
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard.pr_flow import run_pr_flow
from envctl_engine.ui.selection_support import (
    no_target_selected_message as selection_no_target_selected_message,
)
from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.textual.screens.selector import _run_selector_with_impl


DirtyPrDecision = Literal["commit", "skip", "cancel"]
_REVIEW_TAB_OPEN_TOKEN = "__REVIEW_TAB_OPEN__"
_REVIEW_TAB_SKIP_TOKEN = "__REVIEW_TAB_SKIP__"
_REVIEW_TAB_LAUNCH_FLAG = "dashboard_review_tab_launch"


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

def dirty_pr_reports(owner: Any, route: Route, state: RunState, runtime: Any) -> list[DirtyWorktreeReport]:
    repo_root = repo_root_from_runtime(runtime)
    project_roots = project_roots_for_route(owner, route, state, runtime)
    reports_by_git_root: dict[str, DirtyWorktreeReport] = {}
    for project_name in route.projects or []:
        project_root = project_roots.get(project_name)
        if project_root is None:
            continue
        report = probe_dirty_worktree(project_root, repo_root, project_name=project_name)
        git_root_key = str(report.git_root.resolve())
        existing = reports_by_git_root.get(git_root_key)
        if existing is None:
            reports_by_git_root[git_root_key] = report
    return list(reports_by_git_root.values())

def dedupe_route_projects_by_git_root(owner: Any, route: Route, state: RunState, rt: object) -> Route:
    runtime_any = cast(Any, rt)
    if len(route.projects) <= 1:
        return route
    repo_root = repo_root_from_runtime(runtime_any)
    project_roots = project_roots_for_route(owner, route, state, runtime_any)
    unique_projects: list[str] = []
    seen_git_roots: set[str] = set()
    collapsed = False
    for project_name in route.projects:
        project_root = project_roots.get(project_name)
        if project_root is None:
            unique_projects.append(project_name)
            continue
        git_root = resolve_git_root(project_root, repo_root)
        git_root_key = str(git_root.resolve())
        if git_root_key in seen_git_roots:
            collapsed = True
            continue
        seen_git_roots.add(git_root_key)
        unique_projects.append(project_name)
    if collapsed:
        route.projects = unique_projects
        runtime_any._emit(
            "dashboard.pr_target_scope.deduped_git_roots",
            command="pr",
            original_project_count=len(project_roots) if project_roots else len(route.projects),
            deduped_project_count=len(unique_projects),
            projects=list(unique_projects),
        )
    return route

def repo_root_from_runtime(runtime: Any) -> Path:
    base_dir = getattr(getattr(runtime, "config", None), "base_dir", Path.cwd())
    return Path(str(base_dir)).resolve()

def project_roots_for_route(owner: Any, route: Route, state: RunState, runtime: Any) -> dict[str, Path]:
    repo_root = repo_root_from_runtime(runtime)
    metadata = state.metadata if isinstance(state.metadata, dict) else {}
    raw_project_roots = metadata.get("project_roots")
    project_roots: dict[str, Path] = {}
    if isinstance(raw_project_roots, dict):
        for name, root in raw_project_roots.items():
            project_name = str(name).strip()
            root_raw = str(root or "").strip()
            if not project_name or not root_raw:
                continue
            resolved = Path(root_raw)
            if not resolved.is_absolute():
                resolved = repo_root / resolved
            project_roots[project_name] = resolved.resolve()
    for project_name in route.projects or []:
        if project_name in project_roots:
            continue
        if str(project_name).strip().casefold() == "main":
            project_roots[project_name] = repo_root
    return project_roots

def maybe_offer_review_tab_launch(owner: Any, route: Route, state: RunState, rt: object) -> None:
    runtime_any = cast(Any, rt)
    if not bool(route.flags.get(_REVIEW_TAB_LAUNCH_FLAG)):
        return
    target = owner._review_tab_target(route, state, runtime_any)
    if target is None:
        runtime_any._emit("dashboard.review_tab.skipped", command="review", reason="ineligible_target_scope")
        return
    project_name, project_root = target
    launch_review_agent_terminal(
        runtime_any,
        repo_root=repo_root_from_runtime(runtime_any),
        project_name=project_name,
        project_root=project_root,
        review_bundle_path=review_bundle_path(state, project_name=project_name),
    )

def apply_review_tab_launch_selection(owner: Any, route: Route, state: RunState, rt: object) -> Route:
    runtime_any = cast(Any, rt)
    route.flags = {key: value for key, value in route.flags.items() if key != _REVIEW_TAB_LAUNCH_FLAG}
    target = owner._review_tab_target(route, state, runtime_any)
    runtime_any._emit(
        "dashboard.review_tab.evaluate",
        command="review",
        project_count=len(route.projects or []),
        eligible=target is not None,
    )
    if target is None:
        runtime_any._emit("dashboard.review_tab.skipped", command="review", reason="ineligible_target_scope")
        return route
    project_name, _project_root = target
    readiness = review_agent_launch_readiness(runtime_any)
    if not readiness.ready:
        runtime_any._emit(
            "dashboard.review_tab.skipped",
            command="review",
            reason=readiness.reason,
            project=project_name,
            cli=readiness.cli,
            missing=list(readiness.missing),
        )
        message = review_tab_unavailable_message(readiness.reason, readiness.missing)
        if message:
            print(message)
        return route
    runtime_any._emit("dashboard.review_tab.prompt", command="review", project=project_name, cli=readiness.cli)
    decision = owner._prompt_review_tab_menu(runtime_any, project_name=project_name)
    if decision != "commit":
        runtime_any._emit(
            "dashboard.review_tab.declined",
            command="review",
            project=project_name,
            cli=readiness.cli,
        )
        return route
    runtime_any._emit("dashboard.review_tab.accepted", command="review", project=project_name, cli=readiness.cli)
    route.flags = {**route.flags, _REVIEW_TAB_LAUNCH_FLAG: True}
    return route

def review_tab_target(owner: Any, route: Route, state: RunState, runtime: Any) -> tuple[str, Path] | None:
    repo_root = repo_root_from_runtime(runtime)
    project_roots = project_roots_for_route(owner, route, state, runtime)
    distinct_targets: list[tuple[str, Path]] = []
    seen_git_roots: set[str] = set()
    for project_name in route.projects or []:
        project_root = project_roots.get(project_name)
        if project_root is None:
            continue
        git_root = resolve_git_root(project_root, repo_root)
        if git_root == repo_root and project_root != repo_root and not (project_root / ".git").exists():
            git_root = project_root
        git_root_key = str(git_root.resolve())
        if git_root_key in seen_git_roots:
            continue
        seen_git_roots.add(git_root_key)
        distinct_targets.append((project_name, project_root))
    if len(distinct_targets) != 1:
        return None
    project_name, project_root = distinct_targets[0]
    if str(project_name).strip().casefold() == "main":
        return None
    if project_root.resolve() == repo_root:
        return None
    return project_name, project_root

def review_tab_unavailable_message(reason: str, missing: tuple[str, ...]) -> str:
    if reason == "missing_executables" and missing:
        return f"Origin review tab unavailable: missing required executables: {', '.join(missing)}."
    if reason in {"missing_cmux_context", "workspace_unavailable"}:
        return "Origin review tab unavailable: current cmux workspace context is unavailable."
    return ""

def review_bundle_path(state: RunState, *, project_name: str) -> Path | None:
    metadata = state.metadata if isinstance(state.metadata, dict) else {}
    reports = metadata.get("project_action_reports")
    if not isinstance(reports, dict):
        return None
    project_entry = reports.get(project_name)
    if not isinstance(project_entry, dict):
        return None
    review_entry = project_entry.get("review")
    if not isinstance(review_entry, dict):
        return None
    if str(review_entry.get("status", "")).strip().lower() != "success":
        return None
    raw_path = str(review_entry.get("bundle_path", "") or "").strip()
    if not raw_path:
        return None
    return Path(raw_path).expanduser()

def dirty_pr_prompt(dirty_targets: list[DirtyWorktreeReport]) -> str:
    if len(dirty_targets) == 1:
        target = dirty_targets[0]
        return f"UNSTAGED CODE IN WORKTREE {target.project_name} - DO YOU WANT TO STAGE IT?"
    return "UNSTAGED CODE IN SELECTED WORKTREES - DO YOU WANT TO STAGE IT?"

def prompt_review_tab_menu(runtime: Any, *, project_name: str) -> DirtyPrDecision:
    prompt = f"Open an origin-side AI review tab for {project_name}?"
    values = _run_selector_with_impl(
        prompt=prompt,
        options=[
            SelectorItem(
                id="review-tab:open",
                label="Yes",
                kind="",
                token=_REVIEW_TAB_OPEN_TOKEN,
                scope_signature=("review-tab:open",),
            ),
            SelectorItem(
                id="review-tab:skip",
                label="No",
                kind="",
                token=_REVIEW_TAB_SKIP_TOKEN,
                scope_signature=("review-tab:skip",),
            ),
        ],
        multi=False,
        initial_tokens=[_REVIEW_TAB_SKIP_TOKEN],
        emit=getattr(runtime, "_emit", None),
    )
    if not values:
        return "skip"
    chosen = str(values[0]).strip()
    if chosen == _REVIEW_TAB_OPEN_TOKEN:
        return "commit"
    if chosen == _REVIEW_TAB_SKIP_TOKEN:
        return "skip"
    return prompt_yes_no_dialog(runtime, title="Open origin review tab?", prompt=prompt)

def dirty_categories(report: DirtyWorktreeReport) -> list[str]:
    categories: list[str] = []
    if bool(getattr(report, "staged", False)):
        categories.append("staged changes")
    if bool(getattr(report, "unstaged", False)):
        categories.append("unstaged changes")
    if bool(getattr(report, "untracked", False)):
        categories.append("untracked files")
    return categories

def prompt_dirty_pr_menu(runtime: Any, *, title: str, prompt: str) -> DirtyPrDecision:
    values = _run_selector_with_impl(
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

def read_interactive_line(runtime: Any, prompt: str) -> str:
    reader = getattr(runtime, "_read_interactive_command_line", None)
    if callable(reader):
        return str(reader(prompt))
    # This fallback is intentionally imported lazily so the owner module can be
    # tested without importing terminal UI dependencies on selector-only paths.
    from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI

    env = getattr(runtime, "env", {})
    return str(RuntimeTerminalUI.read_interactive_command_line(prompt, env))

def default_pr_base_branch(owner: Any, runtime: Any) -> str:
    git_root = pr_git_root(owner, runtime)
    try:
        default_branch = detect_default_branch(git_root).strip()
    except Exception:
        default_branch = ""
    return default_branch or "main"

def pr_base_branch_options(owner: Any, runtime: Any, *, default_branch: str) -> list[SelectorItem]:
    git_root = pr_git_root(owner, runtime)
    command = ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads"]
    listed = subprocess.run(
        command,
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

def pr_git_root(owner: Any, runtime: Any) -> Path:
    base_dir = getattr(getattr(runtime, "config", None), "base_dir", None)
    if isinstance(base_dir, Path):
        return resolve_git_root(base_dir, base_dir)
    if isinstance(base_dir, str) and base_dir.strip():
        candidate = Path(base_dir).resolve()
        return resolve_git_root(candidate, candidate)
    return Path.cwd()

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
