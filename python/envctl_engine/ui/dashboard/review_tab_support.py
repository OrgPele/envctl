from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Literal

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.selector_model import SelectorItem


DirtyPrDecision = Literal["commit", "skip", "cancel"]
REVIEW_TAB_OPEN_TOKEN = "__REVIEW_TAB_OPEN__"
REVIEW_TAB_SKIP_TOKEN = "__REVIEW_TAB_SKIP__"
REVIEW_TAB_LAUNCH_FLAG = "dashboard_review_tab_launch"


def maybe_offer_review_tab_launch(
    owner: Any,
    route: Route,
    state: RunState,
    rt: object,
    *,
    launch_review_agent_terminal_fn: Callable[..., object],
    repo_root_from_runtime_fn: Callable[[Any], Path],
) -> None:
    runtime = rt
    if not bool(route.flags.get(REVIEW_TAB_LAUNCH_FLAG)):
        return
    target = owner._review_tab_target(route, state, runtime)
    if target is None:
        runtime._emit("dashboard.review_tab.skipped", command="review", reason="ineligible_target_scope")
        return
    project_name, project_root = target
    launch_review_agent_terminal_fn(
        runtime,
        repo_root=repo_root_from_runtime_fn(runtime),
        project_name=project_name,
        project_root=project_root,
        review_bundle_path=review_bundle_path(state, project_name=project_name),
    )


def apply_review_tab_launch_selection(
    owner: Any,
    route: Route,
    state: RunState,
    rt: object,
    *,
    review_agent_launch_readiness_fn: Callable[[Any], object],
) -> Route:
    runtime = rt
    route.flags = {key: value for key, value in route.flags.items() if key != REVIEW_TAB_LAUNCH_FLAG}
    target = owner._review_tab_target(route, state, runtime)
    runtime._emit(
        "dashboard.review_tab.evaluate",
        command="review",
        project_count=len(route.projects or []),
        eligible=target is not None,
    )
    if target is None:
        runtime._emit("dashboard.review_tab.skipped", command="review", reason="ineligible_target_scope")
        return route
    project_name, _project_root = target
    readiness = review_agent_launch_readiness_fn(runtime)
    if not readiness.ready:
        runtime._emit(
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
    runtime._emit("dashboard.review_tab.prompt", command="review", project=project_name, cli=readiness.cli)
    decision = owner._prompt_review_tab_menu(runtime, project_name=project_name)
    if decision != "commit":
        runtime._emit(
            "dashboard.review_tab.declined",
            command="review",
            project=project_name,
            cli=readiness.cli,
        )
        return route
    runtime._emit("dashboard.review_tab.accepted", command="review", project=project_name, cli=readiness.cli)
    route.flags = {**route.flags, REVIEW_TAB_LAUNCH_FLAG: True}
    return route


def review_tab_target(
    owner: Any,
    route: Route,
    state: RunState,
    runtime: Any,
    *,
    repo_root_from_runtime_fn: Callable[[Any], Path],
    project_roots_for_route_fn: Callable[[Any, Route, RunState, Any], dict[str, Path]],
    resolve_git_root_fn: Callable[[Path, Path], Path],
) -> tuple[str, Path] | None:
    _ = owner
    repo_root = repo_root_from_runtime_fn(runtime)
    project_roots = project_roots_for_route_fn(owner, route, state, runtime)
    distinct_targets: list[tuple[str, Path]] = []
    seen_git_roots: set[str] = set()
    for project_name in route.projects or []:
        project_root = project_roots.get(project_name)
        if project_root is None:
            continue
        git_root = resolve_git_root_fn(project_root, repo_root)
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


def prompt_review_tab_menu(
    runtime: Any,
    *,
    project_name: str,
    run_selector_fn: Callable[..., object],
    prompt_yes_no_dialog_fn: Callable[[Any], DirtyPrDecision],
) -> DirtyPrDecision:
    prompt = f"Open an origin-side AI review tab for {project_name}?"
    values = run_selector_fn(
        prompt=prompt,
        options=[
            SelectorItem(
                id="review-tab:open",
                label="Yes",
                kind="",
                token=REVIEW_TAB_OPEN_TOKEN,
                scope_signature=("review-tab:open",),
            ),
            SelectorItem(
                id="review-tab:skip",
                label="No",
                kind="",
                token=REVIEW_TAB_SKIP_TOKEN,
                scope_signature=("review-tab:skip",),
            ),
        ],
        multi=False,
        initial_tokens=[REVIEW_TAB_SKIP_TOKEN],
        emit=getattr(runtime, "_emit", None),
    )
    if not values:
        return "skip"
    chosen = str(values[0]).strip()
    if chosen == REVIEW_TAB_OPEN_TOKEN:
        return "commit"
    if chosen == REVIEW_TAB_SKIP_TOKEN:
        return "skip"
    return prompt_yes_no_dialog_fn(runtime)
