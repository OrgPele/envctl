from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from envctl_engine.planning.protocols import ProjectContextLike
from envctl_engine.runtime.command_router import Route
from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import SpinnerPolicy, emit_spinner_policy, resolve_spinner_policy


RawProject = tuple[str, Path]


def _worktree_spinner_policy(*, env: Mapping[str, str], emit: Callable[..., None] | None, op_id: str) -> SpinnerPolicy:
    policy = resolve_spinner_policy(env)
    emit_spinner_policy(
        emit,
        policy,
        context={"component": "worktree_planning", "op_id": op_id},
    )
    return policy


def _worktree_spinner_update(
    *,
    emit: Callable[..., None] | None,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
) -> None:
    if enabled:
        active_spinner.update(message)
    if emit is not None:
        emit(
            "ui.spinner.lifecycle",
            component="worktree_planning",
            op_id=op_id,
            state="update",
            message=message,
        )


def _worktree_spinner_start(
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


def _worktree_spinner_finish(
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


def _worktree_spinner_fail(
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


def _worktree_spinner_stop(*, emit: Callable[..., None] | None, enabled: bool, op_id: str) -> None:
    if emit is not None:
        emit(
            "ui.spinner.lifecycle",
            component="worktree_planning",
            op_id=op_id,
            state="stop",
            enabled=enabled,
        )


def apply_setup_worktree_selection(
    *,
    route: Route,
    project_contexts: list[ProjectContextLike],
    setup_worktree_requested: Callable[[Route], bool],
    env: Mapping[str, str],
    emit: Callable[..., None] | None,
    coerce_setup_entries: Callable[..., list[tuple[str, str]]],
    apply_multi_setup_entry: Callable[..., tuple[list[RawProject], set[str]]],
    apply_single_setup_entry: Callable[..., tuple[list[RawProject], str]],
    resolve_included_setup_worktrees: Callable[..., tuple[set[str], list[str]]],
    contexts_from_raw_projects: Callable[[list[RawProject]], list[ProjectContextLike]],
) -> list[ProjectContextLike]:
    if not setup_worktree_requested(route):
        return project_contexts
    if bool(route.flags.get("docker")):
        raise RuntimeError("setup-worktrees is not supported in Docker mode.")

    multi_entries = coerce_setup_entries(
        route=route,
        flag_name="setup_worktrees",
        value_name="count",
    )
    single_entries = coerce_setup_entries(
        route=route,
        flag_name="setup_worktree",
        value_name="iteration",
    )
    include_tokens = route.flags.get("include_existing_worktrees")
    include_list: list[str] = []
    if isinstance(include_tokens, list):
        include_list = [str(token).strip() for token in include_tokens if str(token).strip()]

    setup_worktree_existing = bool(route.flags.get("setup_worktree_existing"))
    setup_worktree_recreate = bool(route.flags.get("setup_worktree_recreate"))
    if setup_worktree_existing and setup_worktree_recreate:
        raise RuntimeError("Use only one of --setup-worktree-existing or --setup-worktree-recreate.")

    raw_projects = [(context.name, context.root) for context in project_contexts]
    selected_names: set[str] = set()
    setup_features: list[str] = []
    op_id = "worktree.setup"
    policy = _worktree_spinner_policy(env=env, emit=emit, op_id=op_id)
    enabled = bool(policy.enabled)

    with (
        use_spinner_policy(policy),
        spinner(
            "Setting up worktrees...",
            enabled=enabled,
            start_immediately=False,
        ) as active_spinner,
    ):
        _worktree_spinner_start(
            emit=emit,
            enabled=enabled,
            active_spinner=active_spinner,
            op_id=op_id,
            message="Setting up worktrees...",
        )
        try:
            for feature, count_raw in multi_entries:
                raw_projects, created_names = apply_multi_setup_entry(
                    feature=feature,
                    count_raw=count_raw,
                    raw_projects=raw_projects,
                    enabled=enabled,
                    active_spinner=active_spinner,
                    op_id=op_id,
                )
                setup_features.append(feature)
                selected_names.update(created_names)

            for feature, iteration_raw in single_entries:
                raw_projects, selected_name = apply_single_setup_entry(
                    feature=feature,
                    iteration_raw=iteration_raw,
                    raw_projects=raw_projects,
                    setup_worktree_existing=setup_worktree_existing,
                    setup_worktree_recreate=setup_worktree_recreate,
                    enabled=enabled,
                    active_spinner=active_spinner,
                    op_id=op_id,
                )
                setup_features.append(feature)
                selected_names.add(selected_name)

            if include_list:
                selected_names, missing = resolve_included_setup_worktrees(
                    raw_projects=raw_projects,
                    setup_features=setup_features,
                    selected_names=selected_names,
                    include_tokens=include_list,
                )
                if missing:
                    _worktree_spinner_update(
                        emit=emit,
                        enabled=enabled,
                        active_spinner=active_spinner,
                        op_id=op_id,
                        message="Skipping non-existent additional worktrees: " + ",".join(missing) + ".",
                    )

            refreshed_contexts = contexts_from_raw_projects(raw_projects)
            if not selected_names:
                _worktree_spinner_finish(
                    emit=emit,
                    enabled=enabled,
                    active_spinner=active_spinner,
                    op_id=op_id,
                    message="Worktree setup completed",
                )
                return refreshed_contexts
            selected_lower = {name.lower() for name in selected_names}
            filtered = [context for context in refreshed_contexts if context.name.lower() in selected_lower]
            if not filtered:
                raise RuntimeError("No worktrees selected to run.")
            _worktree_spinner_finish(
                emit=emit,
                enabled=enabled,
                active_spinner=active_spinner,
                op_id=op_id,
                message="Worktree setup completed",
            )
            return filtered
        except Exception:
            _worktree_spinner_fail(
                emit=emit,
                enabled=enabled,
                active_spinner=active_spinner,
                op_id=op_id,
                message="Worktree setup failed",
            )
            raise
        finally:
            _worktree_spinner_stop(emit=emit, enabled=enabled, op_id=op_id)
