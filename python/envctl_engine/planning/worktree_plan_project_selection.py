from __future__ import annotations

import sys
from collections import OrderedDict
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Protocol

from envctl_engine.planning import (
    filter_projects_for_plan,
    list_planning_files,
    predict_plan_projects,
    resolve_planning_files,
    select_projects_for_plan_files,
)
from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree, PlanSelectionResult, PlanWorktreeSyncResult
from envctl_engine.planning.worktree_plan_selection import (
    adjust_plan_counts_for_fresh_ai_launch,
    fresh_ai_launch_transport,
    route_requests_fresh_ai_worktree,
)
from envctl_engine.runtime.command_router import Route


class ProjectContextLike(Protocol):
    name: str
    root: Path


def _prediction_selection_result(
    *,
    raw_projects: list[tuple[str, Path]],
    plan_counts: OrderedDict[str, int],
    base_dir: Path,
    trees_dir_name: str,
    contexts_from_raw_projects: Callable[[list[tuple[str, Path]]], list[ProjectContextLike]],
) -> PlanSelectionResult:
    predictions = predict_plan_projects(
        projects=raw_projects,
        plan_counts=plan_counts,
        base_dir=base_dir,
        trees_dir_name=trees_dir_name,
    )
    predicted_raw_projects = [(prediction.name, Path(prediction.root)) for prediction in predictions]
    selected_contexts = contexts_from_raw_projects(predicted_raw_projects)
    created_worktrees = tuple(
        CreatedPlanWorktree(
            name=prediction.name,
            root=Path(prediction.root),
            plan_file=prediction.plan_file,
        )
        for prediction in predictions
        if prediction.action == "create"
    )
    return PlanSelectionResult(
        raw_projects=predicted_raw_projects,
        selected_contexts=selected_contexts,
        created_worktrees=created_worktrees,
    )


def _sync_error_result(sync_result: PlanWorktreeSyncResult) -> PlanSelectionResult:
    return PlanSelectionResult(
        raw_projects=list(sync_result.raw_projects),
        selected_contexts=[],
        created_worktrees=sync_result.created_worktrees,
        error=sync_result.error,
    )


def select_plan_projects(
    *,
    route: Route,
    project_contexts: list[ProjectContextLike],
    config: Any,
    env: Mapping[str, str],
    emit: Callable[..., None],
    contexts_from_raw_projects: Callable[[list[tuple[str, Path]]], list[ProjectContextLike]],
    duplicate_project_context_error: Callable[[list[ProjectContextLike]], str | None],
    planning_keep_plan_enabled: Callable[[Route], bool],
    prompt_planning_selection: Callable[..., dict[str, int] | None],
    sync_plan_worktrees_from_plan_counts: Callable[..., PlanWorktreeSyncResult],
    output: Callable[[str], None] = print,
) -> PlanSelectionResult:
    raw_projects = [(ctx.name, ctx.root) for ctx in project_contexts]
    planning_files = list_planning_files(config.planning_dir)
    selection_raw = ",".join(route.passthrough_args).strip()
    keep_plan = planning_keep_plan_enabled(route)

    if selection_raw:
        if planning_files:
            try:
                plan_counts = resolve_planning_files(
                    selection_raw=selection_raw,
                    planning_files=planning_files,
                    base_dir=config.base_dir,
                    planning_dir=config.planning_dir,
                    requested_cli=str(
                        env.get("ENVCTL_PLAN_AGENT_CLI") or config.raw.get("ENVCTL_PLAN_AGENT_CLI") or ""
                    ),
                )
                plan_counts = adjust_plan_counts_for_fresh_ai_launch(
                    raw_projects=raw_projects,
                    plan_counts=plan_counts,
                    route=route,
                )
                if bool(getattr(route, "flags", {}).get("dry_run")):
                    return _prediction_selection_result(
                        raw_projects=raw_projects,
                        plan_counts=plan_counts,
                        base_dir=config.base_dir,
                        trees_dir_name=config.trees_dir_name,
                        contexts_from_raw_projects=contexts_from_raw_projects,
                    )
            except ValueError as exc:
                emit("planning.selection.invalid", selection=selection_raw, error=str(exc))
                output(str(exc))
                return PlanSelectionResult(raw_projects=raw_projects, selected_contexts=[], error=str(exc))
            sync_result = sync_plan_worktrees_from_plan_counts(
                plan_counts=plan_counts,
                raw_projects=raw_projects,
                keep_plan=keep_plan,
                fresh_ai_launch=route_requests_fresh_ai_worktree(route),
                launch_transport=fresh_ai_launch_transport(route),
            )
            raw_projects = list(sync_result.raw_projects)
            if sync_result.error:
                output(sync_result.error)
                return _sync_error_result(sync_result)
            refreshed_contexts = contexts_from_raw_projects(raw_projects)
            duplicate_error = duplicate_project_context_error(refreshed_contexts)
            if duplicate_error:
                output(duplicate_error)
                return PlanSelectionResult(
                    raw_projects=raw_projects,
                    selected_contexts=[],
                    created_worktrees=sync_result.created_worktrees,
                    error=duplicate_error,
                )
            filtered = select_projects_for_plan_files(projects=raw_projects, plan_counts=plan_counts)
            if route_requests_fresh_ai_worktree(route) and sync_result.created_worktrees:
                created_names = {item.name for item in sync_result.created_worktrees}
                filtered = [project for project in filtered if project[0] in created_names]
            if filtered:
                emit(
                    "planning.selection.resolved",
                    selection=selection_raw,
                    selected=[name for name, _ in filtered],
                    plans=list(plan_counts.keys()),
                )
                selected_names = {name for name, _ in filtered}
                selected_contexts = [ctx for ctx in refreshed_contexts if ctx.name in selected_names]
                return PlanSelectionResult(
                    raw_projects=raw_projects,
                    selected_contexts=selected_contexts,
                    created_worktrees=sync_result.created_worktrees,
                )
            output("No tree paths found for selected planning file(s).")
            return PlanSelectionResult(
                raw_projects=raw_projects,
                selected_contexts=[],
                created_worktrees=sync_result.created_worktrees,
                error="No tree paths found for selected planning file(s).",
            )

        filtered = filter_projects_for_plan(
            raw_projects,
            route.passthrough_args,
            strict_no_match=config.plan_strict_selection,
        )
        if not filtered:
            output("No tree paths found for requested project filter(s): " + ", ".join(route.passthrough_args) + ".")
            return PlanSelectionResult(
                raw_projects=raw_projects,
                selected_contexts=[],
                error="No tree paths found for requested project filter(s).",
            )
        selected_names = {name for name, _ in filtered}
        selected_contexts = [ctx for ctx in project_contexts if ctx.name in selected_names]
        return PlanSelectionResult(raw_projects=raw_projects, selected_contexts=selected_contexts)

    if not planning_files:
        output(
            f"No planning files found in {config.planning_dir}. "
            "Pass explicit selectors (for example: envctl --plan feature-a) or use --trees."
        )
        return PlanSelectionResult(raw_projects=raw_projects, selected_contexts=[], error="No planning files found.")

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        output(
            "No TTY available for planning selection. "
            "Run 'envctl --list-trees --json' and retry with '--headless --plan <selector>'."
        )
        return PlanSelectionResult(raw_projects=raw_projects, selected_contexts=[], error="No TTY available.")

    dry_run = bool(getattr(route, "flags", {}).get("dry_run"))
    plan_counts = prompt_planning_selection(planning_files, raw_projects, persist_memory=not dry_run)
    if plan_counts is None:
        output("Planning selection cancelled.")
        return PlanSelectionResult(
            raw_projects=raw_projects,
            selected_contexts=[],
            error="Planning selection cancelled.",
        )
    if not plan_counts:
        output("No planning files selected.")
        return PlanSelectionResult(raw_projects=raw_projects, selected_contexts=[], error="No planning files selected.")

    positive_plan_counts: OrderedDict[str, int] = OrderedDict(
        (plan_file, int(count)) for plan_file, count in plan_counts.items() if int(count) > 0
    )
    if dry_run:
        return _prediction_selection_result(
            raw_projects=raw_projects,
            plan_counts=positive_plan_counts,
            base_dir=config.base_dir,
            trees_dir_name=config.trees_dir_name,
            contexts_from_raw_projects=contexts_from_raw_projects,
        )

    sync_result = sync_plan_worktrees_from_plan_counts(
        plan_counts=plan_counts,
        raw_projects=raw_projects,
        keep_plan=keep_plan,
        fresh_ai_launch=route_requests_fresh_ai_worktree(route),
        launch_transport=fresh_ai_launch_transport(route),
    )
    raw_projects = list(sync_result.raw_projects)
    if sync_result.error:
        output(sync_result.error)
        return _sync_error_result(sync_result)
    refreshed_contexts = contexts_from_raw_projects(raw_projects)
    duplicate_error = duplicate_project_context_error(refreshed_contexts)
    if duplicate_error:
        output(duplicate_error)
        return PlanSelectionResult(
            raw_projects=raw_projects,
            selected_contexts=[],
            created_worktrees=sync_result.created_worktrees,
            error=duplicate_error,
        )

    if not positive_plan_counts:
        output("Planning counts scaled to zero; no worktrees remain.")
        return PlanSelectionResult(
            raw_projects=raw_projects,
            selected_contexts=[],
            created_worktrees=sync_result.created_worktrees,
            error="Planning counts scaled to zero; no worktrees remain.",
        )

    filtered = select_projects_for_plan_files(projects=raw_projects, plan_counts=positive_plan_counts)
    if not filtered:
        output("No tree paths found for selected planning file(s).")
        return PlanSelectionResult(
            raw_projects=raw_projects,
            selected_contexts=[],
            created_worktrees=sync_result.created_worktrees,
            error="No tree paths found for selected planning file(s).",
        )

    emit(
        "planning.selection.resolved",
        selection="interactive",
        selected=[name for name, _ in filtered],
        plans=list(positive_plan_counts.keys()),
    )
    selected_names = {name for name, _ in filtered}
    selected_contexts = [ctx for ctx in refreshed_contexts if ctx.name in selected_names]
    return PlanSelectionResult(
        raw_projects=raw_projects,
        selected_contexts=selected_contexts,
        created_worktrees=sync_result.created_worktrees,
    )
