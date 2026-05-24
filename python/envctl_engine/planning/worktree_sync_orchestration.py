from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from envctl_engine.planning import planning_feature_name
from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree, PlanWorktreeSyncResult
from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy


RawProject = tuple[str, Path]


def _spinner_update(
    *,
    emit: Callable[..., None] | None,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
    terminal_message: str | None = None,
) -> None:
    if enabled:
        active_spinner.update(terminal_message or message)
    if emit is not None:
        emit(
            "ui.spinner.lifecycle",
            component="worktree_planning",
            op_id=op_id,
            state="update",
            message=message,
        )


def _spinner_start(
    *,
    emit: Callable[..., None] | None,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
) -> None:
    if enabled:
        active_spinner.start()
    if emit is not None:
        emit(
            "ui.spinner.lifecycle",
            component="worktree_planning",
            op_id=op_id,
            state="start",
            message=message,
        )


def _spinner_finish(
    *,
    emit: Callable[..., None] | None,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
) -> None:
    if enabled:
        active_spinner.succeed(message)
    if emit is not None:
        emit(
            "ui.spinner.lifecycle",
            component="worktree_planning",
            op_id=op_id,
            state="success",
            message=message,
        )


def _spinner_fail(
    *,
    emit: Callable[..., None] | None,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
) -> None:
    if enabled:
        active_spinner.fail(message)
    if emit is not None:
        emit(
            "ui.spinner.lifecycle",
            component="worktree_planning",
            op_id=op_id,
            state="fail",
            message=message,
        )


def _spinner_stop(*, emit: Callable[..., None] | None, enabled: bool, op_id: str) -> None:
    if emit is not None:
        emit(
            "ui.spinner.lifecycle",
            component="worktree_planning",
            op_id=op_id,
            state="stop",
            enabled=enabled,
        )


def sync_plan_worktrees_from_plan_counts(
    *,
    plan_counts: Mapping[str, int],
    raw_projects: list[RawProject],
    keep_plan: bool,
    ensure_trees_root: Callable[[], None],
    env: Mapping[str, str],
    emit: Callable[..., None] | None,
    sync_single_plan_worktree_target: Callable[..., PlanWorktreeSyncResult],
    fresh_ai_launch: bool = False,
    launch_transport: str = "",
) -> PlanWorktreeSyncResult:
    projects = list(raw_projects)
    created_worktrees: list[CreatedPlanWorktree] = []
    removed_worktrees: list[str] = []
    archived_plan_files: list[str] = []
    ensure_trees_root()
    policy = resolve_spinner_policy(env)
    emit_spinner_policy(
        emit,
        policy,
        context={"component": "worktree_planning", "op_id": "worktree.sync"},
    )
    enabled = bool(policy.enabled)

    with (
        use_spinner_policy(policy),
        spinner(
            "Syncing planning worktrees...",
            enabled=enabled,
            start_immediately=False,
        ) as active_spinner,
    ):
        _spinner_start(
            emit=emit,
            enabled=enabled,
            active_spinner=active_spinner,
            op_id="worktree.sync",
            message="Syncing planning worktrees...",
        )
        try:
            for plan_file, desired_raw in plan_counts.items():
                target_result = sync_single_plan_worktree_target(
                    plan_file=plan_file,
                    desired_raw=desired_raw,
                    projects=projects,
                    keep_plan=keep_plan,
                    fresh_ai_launch=fresh_ai_launch,
                    launch_transport=launch_transport,
                    enabled=enabled,
                    active_spinner=active_spinner,
                    op_id="worktree.sync",
                )
                projects = list(target_result.raw_projects)
                created_worktrees.extend(target_result.created_worktrees)
                removed_worktrees.extend(target_result.removed_worktrees)
                archived_plan_files.extend(target_result.archived_plan_files)
                if target_result.error is not None:
                    return PlanWorktreeSyncResult(
                        raw_projects=projects,
                        created_worktrees=tuple(created_worktrees),
                        removed_worktrees=tuple(removed_worktrees),
                        archived_plan_files=tuple(archived_plan_files),
                        error=target_result.error,
                    )
            _spinner_finish(
                emit=emit,
                enabled=enabled,
                active_spinner=active_spinner,
                op_id="worktree.sync",
                message="Planning worktree sync completed",
            )
            return PlanWorktreeSyncResult(
                raw_projects=projects,
                created_worktrees=tuple(created_worktrees),
                removed_worktrees=tuple(removed_worktrees),
                archived_plan_files=tuple(archived_plan_files),
            )
        except Exception:
            _spinner_fail(
                emit=emit,
                enabled=enabled,
                active_spinner=active_spinner,
                op_id="worktree.sync",
                message="Planning worktree sync failed",
            )
            raise
        finally:
            _spinner_stop(emit=emit, enabled=enabled, op_id="worktree.sync")


def sync_single_plan_worktree_target(
    *,
    plan_file: str,
    desired_raw: int,
    projects: list[RawProject],
    keep_plan: bool,
    feature_project_candidates: Callable[..., list[RawProject]],
    create_feature_worktrees_result: Callable[..., PlanWorktreeSyncResult],
    discover_tree_projects: Callable[[], list[RawProject]],
    delete_feature_worktrees: Callable[..., str | None],
    cleanup_empty_feature_root: Callable[..., None],
    move_plan_to_done: Callable[[str], None],
    render_planning_path: Callable[..., str],
    update: Callable[..., None],
    output: Callable[[str], None],
    enabled: bool = False,
    active_spinner: Any = None,
    op_id: str = "worktree.sync",
    fresh_ai_launch: bool = False,
    launch_transport: str = "",
) -> PlanWorktreeSyncResult:
    desired = max(0, int(desired_raw))
    feature = planning_feature_name(plan_file)
    candidates = feature_project_candidates(projects=projects, feature=feature)
    existing = len(candidates)
    created_worktrees: tuple[CreatedPlanWorktree, ...] = ()
    removed_worktrees: tuple[str, ...] = ()
    archived_plan_files: tuple[str, ...] = ()

    if desired > existing:
        create_count = desired - existing
        rendered_plan_path = render_planning_path(
            plan_file=plan_file,
            interactive_tty=(True if enabled else None),
        )
        update(
            enabled=enabled,
            active_spinner=active_spinner,
            op_id=op_id,
            message=f"Setting up {create_count} worktree(s) for {plan_file} -> {feature}...",
            terminal_message=(
                f"Setting up {create_count} worktree(s) for "
                f"{rendered_plan_path} -> {feature}..."
            ),
        )
        create_result = create_feature_worktrees_result(
            feature=feature,
            count=create_count,
            plan_file=plan_file,
            created_for_fresh_ai_launch=fresh_ai_launch,
            launch_transport=launch_transport,
        )
        if create_result.error:
            return PlanWorktreeSyncResult(raw_projects=projects, error=create_result.error)
        created_worktrees = create_result.created_worktrees
        projects = discover_tree_projects()
        candidates = feature_project_candidates(projects=projects, feature=feature)
        existing = len(candidates)

    if desired < existing:
        remove_count = existing - desired
        rendered_plan_path = render_planning_path(
            plan_file=plan_file,
            interactive_tty=(True if enabled else None),
        )
        update(
            enabled=enabled,
            active_spinner=active_spinner,
            op_id=op_id,
            message=(
                f"Selected count for {plan_file} ({desired}) is below existing ({existing}); "
                f"removing {remove_count} worktree(s)."
            ),
            terminal_message=(
                f"Selected count for "
                f"{rendered_plan_path} "
                f"({desired}) is below existing ({existing}); removing {remove_count} worktree(s)."
            ),
        )
        remove_error = delete_feature_worktrees(
            feature=feature,
            candidates=candidates,
            remove_count=remove_count,
        )
        if remove_error:
            return PlanWorktreeSyncResult(
                raw_projects=projects,
                created_worktrees=created_worktrees,
                error=remove_error,
            )
        projects = discover_tree_projects()
        current_names = {name for name, _root in projects}
        removed_worktrees = tuple(name for name, _root in candidates if name not in current_names)
        output(
            f"Blasted and deleted {len(removed_worktrees)} worktree(s) for "
            f"{rendered_plan_path}."
        )
        if desired == 0:
            cleanup_empty_feature_root(feature=feature)
            projects = discover_tree_projects()

    remaining_feature_worktrees = feature_project_candidates(projects=projects, feature=feature)
    if desired == 0 and existing > 0 and not keep_plan and not remaining_feature_worktrees:
        move_plan_to_done(plan_file)
        archived_plan_files = (plan_file,)
    return PlanWorktreeSyncResult(
        raw_projects=projects,
        created_worktrees=created_worktrees,
        removed_worktrees=removed_worktrees,
        archived_plan_files=archived_plan_files,
    )
