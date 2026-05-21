from __future__ import annotations

import sys
from collections import OrderedDict
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable, Protocol

from envctl_engine.actions.actions_worktree import delete_worktree_path
from envctl_engine.planning.worktree_creation_commands import (
    run_worktree_add as _run_worktree_add_impl,
    worktree_branch_exists as _worktree_branch_exists_impl,
    worktree_branch_name as _worktree_branch_name_impl,
    worktree_start_point as _worktree_start_point_impl,
)
from envctl_engine.planning.worktree_identity import worktree_project_name as _worktree_project_name_impl
from envctl_engine.planning.worktree_creation_recovery import (
    recover_partial_worktree_creation as _recover_partial_worktree_creation_impl,
    setup_worktree_placeholder_fallback_enabled as _setup_worktree_placeholder_fallback_enabled_impl,
    worktree_add_failure as _worktree_add_failure_impl,
    worktree_target_created as _worktree_target_created_impl,
)
from envctl_engine.planning.worktree_git_hooks import (
    worktree_git_hooks_disabled as _worktree_git_hooks_disabled_impl,
    worktree_git_hooks_policy as _worktree_git_hooks_policy_impl,
)
from envctl_engine.planning.worktree_main_task import (
    move_plan_to_done as _move_plan_to_done_impl,
    next_available_iteration as _next_available_iteration_impl,
    seed_main_task_from_plan as _seed_main_task_from_plan_impl,
)
from envctl_engine.planning.worktree_plan_selection import (
    adjust_plan_counts_for_fresh_ai_launch as _adjust_plan_counts_for_fresh_ai_launch_impl,
    fresh_ai_launch_transport as _fresh_ai_launch_transport_impl,
    planning_keep_plan_enabled as _planning_keep_plan_enabled_impl,
    route_requests_fresh_ai_worktree as _route_requests_fresh_ai_worktree_impl,
)
from envctl_engine.planning.worktree_planning_menu import (
    run_planning_selection_menu as _run_planning_selection_menu_impl,
)
from envctl_engine.planning.worktree_project_catalog import (
    cleanup_empty_feature_root as _cleanup_empty_feature_root_impl,
    feature_project_candidates as _feature_project_candidates_impl,
    project_sort_key_for_feature as _project_sort_key_for_feature_impl,
)
from envctl_engine.planning.worktree_selection_memory import (
    initial_plan_selected_counts as _initial_plan_selected_counts_impl,
    load_plan_selection_memory as _load_plan_selection_memory_impl,
    plan_selection_memory_path as _plan_selection_memory_path_impl,
    save_plan_selection_memory as _save_plan_selection_memory_impl,
)
from envctl_engine.planning.worktree_shared_artifacts import (
    link_repo_local_shared_artifacts as _link_repo_local_shared_artifacts_impl,
)
from envctl_engine.planning.worktree_setup_entries import (
    apply_multi_setup_entry as _apply_multi_setup_entry_impl,
    apply_single_setup_entry as _apply_single_setup_entry_impl,
    coerce_setup_entries as _coerce_setup_entries_impl,
    resolve_included_setup_worktrees as _resolve_included_setup_worktrees_impl,
)
from envctl_engine.planning.worktree_sync_deletion import (
    delete_feature_worktrees as _delete_feature_worktrees_impl,
)
from envctl_engine.planning.worktree_code_intelligence import (
    prepare_worktree_code_intelligence as _prepare_worktree_code_intelligence_impl,
)
from envctl_engine.planning.worktree_provenance import (
    active_fresh_ai_worktree_protection_reason as _active_fresh_ai_worktree_protection_reason_impl,
    build_worktree_provenance as _build_worktree_provenance_impl,
    detect_default_branch as _detect_default_branch_impl,
    fresh_ai_launch_marker_is_fresh as _fresh_ai_launch_marker_is_fresh_impl,
    git_command_output as _git_command_output_impl,
    read_worktree_provenance as _read_worktree_provenance_impl,
    resolve_branch_ref as _resolve_branch_ref_impl,
    write_worktree_provenance as _write_worktree_provenance_impl,
)
from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanSelectionResult,
    PlanWorktreeSyncResult,
)
from envctl_engine.runtime.command_router import Route
from envctl_engine.planning import (
    discover_tree_projects,
    filter_projects_for_plan,
    list_planning_files,
    planning_existing_counts,
    planning_feature_name,
    predict_plan_projects,
    resolve_planning_files,
    select_projects_for_plan_files,
)
from envctl_engine.ui.path_links import render_path_fragment_for_terminal
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI
from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import SpinnerPolicy, emit_spinner_policy, resolve_spinner_policy
from envctl_engine.ui.textual.screens.planning_selector import select_planning_counts_textual


class ProjectContextLike(Protocol):
    name: str
    root: Path


def _worktree_spinner_policy(self: Any, *, op_id: str) -> SpinnerPolicy:
    policy = resolve_spinner_policy(getattr(self, "env", {}))
    emit_spinner_policy(
        getattr(self, "_emit", None),
        policy,
        context={"component": "worktree_planning", "op_id": op_id},
    )
    return policy


def _worktree_spinner_update(
    self: Any,
    *,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
    terminal_message: str | None = None,
) -> None:
    if enabled:
        active_spinner.update(terminal_message or message)
        self._emit(  # type: ignore[attr-defined]
            "ui.spinner.lifecycle",
            component="worktree_planning",
            op_id=op_id,
            state="update",
            message=message,
        )
        return
    print(terminal_message or message)


def _render_planning_path(
    self: Any,
    *,
    absolute_path: Path,
    display_text: str,
    interactive_tty: bool | None = None,
) -> str:
    return render_path_fragment_for_terminal(
        absolute_path,
        display_text=display_text,
        env=getattr(self, "env", {}),
        stream=sys.stdout,
        interactive_tty=interactive_tty,
    )


def _worktree_spinner_start(
    self: Any,
    *,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
) -> None:
    if not enabled:
        import sys  # noqa: PLC0415
        print(f"  {message}", file=sys.stderr, flush=True)
        return
    active_spinner.start()
    self._emit(  # type: ignore[attr-defined]
        "ui.spinner.lifecycle",
        component="worktree_planning",
        op_id=op_id,
        state="start",
        message=message,
    )


def _worktree_spinner_finish(
    self: Any,
    *,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
) -> None:
    if not enabled:
        import sys  # noqa: PLC0415
        print(f"✓ {message}", file=sys.stderr, flush=True)
        return
    active_spinner.succeed(message)
    self._emit(  # type: ignore[attr-defined]
        "ui.spinner.lifecycle",
        component="worktree_planning",
        op_id=op_id,
        state="success",
        message=message,
    )


def _worktree_spinner_fail(
    self: Any,
    *,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
) -> None:
    if not enabled:
        import sys  # noqa: PLC0415
        print(f"✗ {message}", file=sys.stderr, flush=True)
        return
    active_spinner.fail(message)
    self._emit(  # type: ignore[attr-defined]
        "ui.spinner.lifecycle",
        component="worktree_planning",
        op_id=op_id,
        state="fail",
        message=message,
    )


def _worktree_spinner_stop(self: Any, *, enabled: bool, op_id: str) -> None:
    if not enabled:
        return
    self._emit(  # type: ignore[attr-defined]
        "ui.spinner.lifecycle",
        component="worktree_planning",
        op_id=op_id,
        state="stop",
    )


def _coerce_setup_entries(
    self: Any,
    *,
    route: Route,
    flag_name: str,
    value_name: str,
) -> list[tuple[str, str]]:
    return _coerce_setup_entries_impl(flags=route.flags, flag_name=flag_name, value_name=value_name)


def _create_single_worktree(self, *, feature: str, iteration: str) -> str | None:
    feature_root = self._preferred_tree_root_for_feature(feature)
    feature_root.mkdir(parents=True, exist_ok=True)
    target = feature_root / iteration
    result = _run_worktree_add(self, feature=feature, iteration=iteration, target=target, env=self._command_env(port=0))
    if getattr(result, "returncode", 1) != 0:
        if _recover_partial_worktree_creation(self, feature=feature, iteration=iteration, target=target, result=result):
            _link_repo_local_shared_artifacts(self, target=target)
            _prepare_worktree_code_intelligence(self, target=target)
            _write_worktree_provenance(self, target=target)
            return None
        error = self._worktree_add_failure(feature=feature, iteration=iteration, target=target, result=result)
        if error:
            return error
    else:
        _link_repo_local_shared_artifacts(self, target=target)
        _prepare_worktree_code_intelligence(self, target=target)
        _write_worktree_provenance(self, target=target)
    return None


def _apply_setup_worktree_selection(
    self: Any, route: Route, project_contexts: list[ProjectContextLike]
) -> list[ProjectContextLike]:
    if not self._setup_worktree_requested(route):
        return project_contexts
    if bool(route.flags.get("docker")):
        raise RuntimeError("setup-worktrees is not supported in Docker mode.")

    multi_entries = self._coerce_setup_entries(
        route=route,
        flag_name="setup_worktrees",
        value_name="count",
    )
    single_entries = self._coerce_setup_entries(
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
    policy = _worktree_spinner_policy(self, op_id="worktree.setup")
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
            self,
            enabled=enabled,
            active_spinner=active_spinner,
            op_id="worktree.setup",
            message="Setting up worktrees...",
        )
        try:
            for feature, count_raw in multi_entries:
                raw_projects, created_names = _apply_multi_setup_entry(
                    self,
                    feature=feature,
                    count_raw=count_raw,
                    raw_projects=raw_projects,
                    enabled=enabled,
                    active_spinner=active_spinner,
                    op_id="worktree.setup",
                )
                setup_features.append(feature)
                selected_names.update(created_names)

            for feature, iteration_raw in single_entries:
                raw_projects, selected_name = _apply_single_setup_entry(
                    self,
                    feature=feature,
                    iteration_raw=iteration_raw,
                    raw_projects=raw_projects,
                    setup_worktree_existing=setup_worktree_existing,
                    setup_worktree_recreate=setup_worktree_recreate,
                    enabled=enabled,
                    active_spinner=active_spinner,
                    op_id="worktree.setup",
                )
                setup_features.append(feature)
                selected_names.add(selected_name)

            if include_list:
                selected_names, missing = _resolve_included_setup_worktrees_impl(
                    raw_projects=raw_projects,
                    setup_features=setup_features,
                    selected_names=selected_names,
                    include_tokens=include_list,
                )
                if missing:
                    _worktree_spinner_update(
                        self,
                        enabled=enabled,
                        active_spinner=active_spinner,
                        op_id="worktree.setup",
                        message="Skipping non-existent additional worktrees: " + ",".join(missing) + ".",
                    )

            refreshed_contexts = self._contexts_from_raw_projects(raw_projects)
            if not selected_names:
                _worktree_spinner_finish(
                    self,
                    enabled=enabled,
                    active_spinner=active_spinner,
                    op_id="worktree.setup",
                    message="Worktree setup completed",
                )
                return refreshed_contexts
            selected_lower = {name.lower() for name in selected_names}
            filtered = [context for context in refreshed_contexts if context.name.lower() in selected_lower]
            if not filtered:
                raise RuntimeError("No worktrees selected to run.")
            _worktree_spinner_finish(
                self,
                enabled=enabled,
                active_spinner=active_spinner,
                op_id="worktree.setup",
                message="Worktree setup completed",
            )
            return filtered
        except Exception:
            _worktree_spinner_fail(
                self,
                enabled=enabled,
                active_spinner=active_spinner,
                op_id="worktree.setup",
                message="Worktree setup failed",
            )
            raise
        finally:
            _worktree_spinner_stop(self, enabled=enabled, op_id="worktree.setup")


def _apply_multi_setup_entry(
    self: Any,
    *,
    feature: str,
    count_raw: str,
    raw_projects: list[tuple[str, Path]],
    enabled: bool,
    active_spinner: Any,
    op_id: str,
) -> tuple[list[tuple[str, Path]], set[str]]:
    return _apply_multi_setup_entry_impl(
        feature=feature,
        count_raw=count_raw,
        raw_projects=raw_projects,
        feature_project_candidates=self._feature_project_candidates,
        update=lambda message: _worktree_spinner_update(
            self,
            enabled=enabled,
            active_spinner=active_spinner,
            op_id=op_id,
            message=message,
        ),
        create_feature_worktrees=self._create_feature_worktrees,
        discover_tree_projects=lambda: discover_tree_projects(self.config.base_dir, self.config.trees_dir_name),
    )


def _apply_single_setup_entry(
    self: Any,
    *,
    feature: str,
    iteration_raw: str,
    raw_projects: list[tuple[str, Path]],
    setup_worktree_existing: bool,
    setup_worktree_recreate: bool,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
) -> tuple[list[tuple[str, Path]], str]:
    return _apply_single_setup_entry_impl(
        feature=feature,
        iteration_raw=iteration_raw,
        raw_projects=raw_projects,
        preferred_tree_root_for_feature=self._preferred_tree_root_for_feature,
        trees_root_for_worktree=self._trees_root_for_worktree,
        delete_worktree=lambda **kwargs: (
            (result := delete_worktree_path(**kwargs)).success,
            result.message,
        ),
        create_single_worktree=self._create_single_worktree,
        discover_tree_projects=lambda: discover_tree_projects(self.config.base_dir, self.config.trees_dir_name),
        update=lambda message: _worktree_spinner_update(
            self,
            enabled=enabled,
            active_spinner=active_spinner,
            op_id=op_id,
            message=message,
        ),
        repo_root=self.config.base_dir,
        process_runner=self.process_runner,
        setup_worktree_existing=setup_worktree_existing,
        setup_worktree_recreate=setup_worktree_recreate,
    )


def _preferred_tree_root_for_feature(self, feature: str) -> Path:
    normalized = str(self.config.trees_dir_name).strip().rstrip("/")
    if not normalized:
        return self.config.base_dir / "trees" / feature
    flat_candidate = self.config.base_dir / f"{normalized}-{feature}"
    if flat_candidate.is_dir():
        return flat_candidate
    return self.config.base_dir / normalized / feature


def _trees_root_for_worktree(self, worktree_root: Path) -> Path:
    normalized = str(self.config.trees_dir_name).strip().rstrip("/")
    nested_root = self.config.base_dir / (normalized or "trees")
    flat_parent = nested_root.parent
    flat_prefix = f"{Path(normalized).name}-" if normalized else "trees-"
    resolved_target = worktree_root.resolve()
    resolved_nested = nested_root.resolve()
    if resolved_nested == resolved_target or resolved_nested in resolved_target.parents:
        return nested_root

    current = resolved_target
    while current != flat_parent and flat_parent in current.parents:
        if current.parent == flat_parent and current.name.startswith(flat_prefix):
            return current
        current = current.parent
    return nested_root


def _select_plan_projects(
    self: Any, route: Route, project_contexts: list[ProjectContextLike]
) -> list[ProjectContextLike]:
    setattr(self, "_last_plan_selection_result", PlanSelectionResult(raw_projects=[], selected_contexts=[]))
    raw_projects = [(ctx.name, ctx.root) for ctx in project_contexts]
    planning_files = list_planning_files(self.config.planning_dir)
    selection_raw = ",".join(route.passthrough_args).strip()
    keep_plan = self._planning_keep_plan_enabled(route)

    if selection_raw:
        if planning_files:
            try:
                plan_counts = resolve_planning_files(
                    selection_raw=selection_raw,
                    planning_files=planning_files,
                    base_dir=self.config.base_dir,
                    planning_dir=self.config.planning_dir,
                    requested_cli=str(
                        self.env.get("ENVCTL_PLAN_AGENT_CLI")
                        or self.config.raw.get("ENVCTL_PLAN_AGENT_CLI")
                        or ""
                    ),
                )
                plan_counts = _adjust_plan_counts_for_fresh_ai_launch(
                    raw_projects=raw_projects,
                    plan_counts=plan_counts,
                    route=route,
                )
                if bool(getattr(route, "flags", {}).get("dry_run")):
                    predictions = predict_plan_projects(
                        projects=raw_projects,
                        plan_counts=plan_counts,
                        base_dir=self.config.base_dir,
                        trees_dir_name=self.config.trees_dir_name,
                    )
                    predicted_raw_projects = [(prediction.name, Path(prediction.root)) for prediction in predictions]
                    selected_contexts = self._contexts_from_raw_projects(predicted_raw_projects)
                    created_worktrees = tuple(
                        CreatedPlanWorktree(
                            name=prediction.name,
                            root=Path(prediction.root),
                            plan_file=prediction.plan_file,
                        )
                        for prediction in predictions
                        if prediction.action == "create"
                    )
                    setattr(
                        self,
                        "_last_plan_selection_result",
                        PlanSelectionResult(
                            raw_projects=predicted_raw_projects,
                            selected_contexts=selected_contexts,
                            created_worktrees=created_worktrees,
                        ),
                    )
                    return selected_contexts
            except ValueError as exc:
                self._emit("planning.selection.invalid", selection=selection_raw, error=str(exc))
                print(str(exc))
                setattr(
                    self,
                    "_last_plan_selection_result",
                    PlanSelectionResult(raw_projects=raw_projects, selected_contexts=[], error=str(exc)),
                )
                return []
            sync_result = self._sync_plan_worktrees_from_plan_counts(
                plan_counts=plan_counts,
                raw_projects=raw_projects,
                keep_plan=keep_plan,
                fresh_ai_launch=_route_requests_fresh_ai_worktree(route),
                launch_transport=_fresh_ai_launch_transport(route),
            )
            raw_projects = list(sync_result.raw_projects)
            if sync_result.error:
                print(sync_result.error)
                setattr(
                    self,
                    "_last_plan_selection_result",
                    PlanSelectionResult(
                        raw_projects=raw_projects,
                        selected_contexts=[],
                        created_worktrees=sync_result.created_worktrees,
                        error=sync_result.error,
                    ),
                )
                return []
            refreshed_contexts = self._contexts_from_raw_projects(raw_projects)
            duplicate_error = self._duplicate_project_context_error(refreshed_contexts)
            if duplicate_error:
                print(duplicate_error)
                setattr(
                    self,
                    "_last_plan_selection_result",
                    PlanSelectionResult(
                        raw_projects=raw_projects,
                        selected_contexts=[],
                        created_worktrees=sync_result.created_worktrees,
                        error=duplicate_error,
                    ),
                )
                return []
            filtered = select_projects_for_plan_files(projects=raw_projects, plan_counts=plan_counts)
            if _route_requests_fresh_ai_worktree(route) and sync_result.created_worktrees:
                created_names = {item.name for item in sync_result.created_worktrees}
                filtered = [project for project in filtered if project[0] in created_names]
            if filtered:
                self._emit(
                    "planning.selection.resolved",
                    selection=selection_raw,
                    selected=[name for name, _ in filtered],
                    plans=list(plan_counts.keys()),
                )
                selected_names = {name for name, _ in filtered}
                selected_contexts = [ctx for ctx in refreshed_contexts if ctx.name in selected_names]
                setattr(
                    self,
                    "_last_plan_selection_result",
                    PlanSelectionResult(
                        raw_projects=raw_projects,
                        selected_contexts=selected_contexts,
                        created_worktrees=sync_result.created_worktrees,
                    ),
                )
                return selected_contexts
            print("No tree paths found for selected planning file(s).")
            setattr(
                self,
                "_last_plan_selection_result",
                PlanSelectionResult(
                    raw_projects=raw_projects,
                    selected_contexts=[],
                    created_worktrees=sync_result.created_worktrees,
                    error="No tree paths found for selected planning file(s).",
                ),
            )
            return []

        filtered = filter_projects_for_plan(
            raw_projects,
            route.passthrough_args,
            strict_no_match=self.config.plan_strict_selection,
        )
        if not filtered:
            print("No tree paths found for requested project filter(s): " + ", ".join(route.passthrough_args) + ".")
            setattr(
                self,
                "_last_plan_selection_result",
                PlanSelectionResult(
                    raw_projects=raw_projects,
                    selected_contexts=[],
                    error="No tree paths found for requested project filter(s).",
                ),
            )
            return []
        selected_names = {name for name, _ in filtered}
        selected_contexts = [ctx for ctx in project_contexts if ctx.name in selected_names]
        setattr(
            self,
            "_last_plan_selection_result",
            PlanSelectionResult(raw_projects=raw_projects, selected_contexts=selected_contexts),
        )
        return selected_contexts

    if not planning_files:
        print(
            f"No planning files found in {self.config.planning_dir}. "
            "Pass explicit selectors (for example: envctl --plan feature-a) or use --trees."
        )
        setattr(
            self,
            "_last_plan_selection_result",
            PlanSelectionResult(raw_projects=raw_projects, selected_contexts=[], error="No planning files found."),
        )
        return []

    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(
            "No TTY available for planning selection. "
            "Run 'envctl --list-trees --json' and retry with '--headless --plan <selector>'."
        )
        setattr(
            self,
            "_last_plan_selection_result",
            PlanSelectionResult(raw_projects=raw_projects, selected_contexts=[], error="No TTY available."),
        )
        return []

    dry_run = bool(getattr(route, "flags", {}).get("dry_run"))
    plan_counts = self._prompt_planning_selection(planning_files, raw_projects, persist_memory=not dry_run)
    if plan_counts is None:
        print("Planning selection cancelled.")
        setattr(
            self,
            "_last_plan_selection_result",
            PlanSelectionResult(raw_projects=raw_projects, selected_contexts=[], error="Planning selection cancelled."),
        )
        return []
    if not plan_counts:
        print("No planning files selected.")
        setattr(
            self,
            "_last_plan_selection_result",
            PlanSelectionResult(raw_projects=raw_projects, selected_contexts=[], error="No planning files selected."),
        )
        return []

    positive_plan_counts: OrderedDict[str, int] = OrderedDict(
        (plan_file, int(count)) for plan_file, count in plan_counts.items() if int(count) > 0
    )
    if dry_run:
        predictions = predict_plan_projects(
            projects=raw_projects,
            plan_counts=positive_plan_counts,
            base_dir=self.config.base_dir,
            trees_dir_name=self.config.trees_dir_name,
        )
        predicted_raw_projects = [(prediction.name, Path(prediction.root)) for prediction in predictions]
        selected_contexts = self._contexts_from_raw_projects(predicted_raw_projects)
        created_worktrees = tuple(
            CreatedPlanWorktree(
                name=prediction.name,
                root=Path(prediction.root),
                plan_file=prediction.plan_file,
            )
            for prediction in predictions
            if prediction.action == "create"
        )
        setattr(
            self,
            "_last_plan_selection_result",
            PlanSelectionResult(
                raw_projects=predicted_raw_projects,
                selected_contexts=selected_contexts,
                created_worktrees=created_worktrees,
            ),
        )
        return selected_contexts

    sync_result = self._sync_plan_worktrees_from_plan_counts(
        plan_counts=plan_counts,
        raw_projects=raw_projects,
        keep_plan=keep_plan,
        fresh_ai_launch=_route_requests_fresh_ai_worktree(route),
        launch_transport=_fresh_ai_launch_transport(route),
    )
    raw_projects = list(sync_result.raw_projects)
    if sync_result.error:
        print(sync_result.error)
        setattr(
            self,
            "_last_plan_selection_result",
            PlanSelectionResult(
                raw_projects=raw_projects,
                selected_contexts=[],
                created_worktrees=sync_result.created_worktrees,
                error=sync_result.error,
            ),
        )
        return []
    refreshed_contexts = self._contexts_from_raw_projects(raw_projects)
    duplicate_error = self._duplicate_project_context_error(refreshed_contexts)
    if duplicate_error:
        print(duplicate_error)
        setattr(
            self,
            "_last_plan_selection_result",
            PlanSelectionResult(
                raw_projects=raw_projects,
                selected_contexts=[],
                created_worktrees=sync_result.created_worktrees,
                error=duplicate_error,
            ),
        )
        return []

    if not positive_plan_counts:
        print("Planning counts scaled to zero; no worktrees remain.")
        setattr(
            self,
            "_last_plan_selection_result",
            PlanSelectionResult(
                raw_projects=raw_projects,
                selected_contexts=[],
                created_worktrees=sync_result.created_worktrees,
                error="Planning counts scaled to zero; no worktrees remain.",
            ),
        )
        return []

    filtered = select_projects_for_plan_files(projects=raw_projects, plan_counts=positive_plan_counts)
    if not filtered:
        print("No tree paths found for selected planning file(s).")
        setattr(
            self,
            "_last_plan_selection_result",
            PlanSelectionResult(
                raw_projects=raw_projects,
                selected_contexts=[],
                created_worktrees=sync_result.created_worktrees,
                error="No tree paths found for selected planning file(s).",
            ),
        )
        return []

    self._emit(
        "planning.selection.resolved",
        selection="interactive",
        selected=[name for name, _ in filtered],
        plans=list(positive_plan_counts.keys()),
    )
    selected_names = {name for name, _ in filtered}
    selected_contexts = [ctx for ctx in refreshed_contexts if ctx.name in selected_names]
    setattr(
        self,
        "_last_plan_selection_result",
        PlanSelectionResult(
            raw_projects=raw_projects,
            selected_contexts=selected_contexts,
            created_worktrees=sync_result.created_worktrees,
        ),
    )
    return selected_contexts


def _prompt_planning_selection(
    self: Any,
    planning_files: list[str],
    raw_projects: list[tuple[str, Path]],
    *,
    persist_memory: bool = True,
) -> dict[str, int]:
    existing_counts = planning_existing_counts(projects=raw_projects, planning_files=planning_files)
    selected_counts = self._initial_plan_selected_counts(
        planning_files=planning_files,
        existing_counts=existing_counts,
    )
    chosen = self._run_planning_selection_menu(
        planning_files=planning_files,
        selected_counts=selected_counts,
        existing_counts=existing_counts,
    )
    if chosen and persist_memory:
        self._save_plan_selection_memory(chosen)
    return chosen


def _route_requests_fresh_ai_worktree(route: Route) -> bool:
    return _route_requests_fresh_ai_worktree_impl(route)


def _fresh_ai_launch_transport(route: Route) -> str:
    return _fresh_ai_launch_transport_impl(route)


def _adjust_plan_counts_for_fresh_ai_launch(
    *,
    raw_projects: list[tuple[str, Path]],
    plan_counts: OrderedDict[str, int],
    route: Route,
) -> OrderedDict[str, int]:
    return _adjust_plan_counts_for_fresh_ai_launch_impl(
        raw_projects=raw_projects,
        plan_counts=plan_counts,
        route=route,
    )


def _initial_plan_selected_counts(
    self: Any,
    *,
    planning_files: list[str],
    existing_counts: dict[str, int],
) -> dict[str, int]:
    remembered = self._load_plan_selection_memory()
    return _initial_plan_selected_counts_impl(
        planning_files=planning_files,
        existing_counts=existing_counts,
        remembered_counts=remembered,
    )


def _run_planning_selection_menu(
    self: Any,
    *,
    planning_files: list[str],
    selected_counts: dict[str, int],
    existing_counts: dict[str, int],
) -> dict[str, int] | None:
    return _run_planning_selection_menu_impl(
        planning_files=planning_files,
        selected_counts=selected_counts,
        existing_counts=existing_counts,
        flush_pending_interactive_input=self._flush_pending_interactive_input,
        emit=getattr(self, "_emit", None),
        select_planning_counts=select_planning_counts_textual,
    )


def _render_planning_selection_menu(
    self: Any,
    *,
    planning_files: list[str],
    selected_counts: dict[str, int],
    existing_counts: dict[str, int],
    cursor: int,
    message: str,
    terminal_width: int | None = None,
    terminal_height: int | None = None,
) -> str:
    return self.terminal_ui.planning_menu.render(
        planning_files=planning_files,
        selected_counts=selected_counts,
        existing_counts=existing_counts,
        cursor=cursor,
        message=message,
        terminal_width=terminal_width,
        terminal_height=terminal_height,
    )


def _terminal_size(self: Any) -> tuple[int, int]:
    return self.terminal_ui.planning_menu.terminal_size()


def _truncate_text(value: str, max_len: int) -> str:
    return RuntimeTerminalUI().planning_menu.truncate_text(value, max_len)


def _to_terminal_lines(frame: str) -> str:
    return RuntimeTerminalUI().planning_menu.to_terminal_lines(frame)


def _read_planning_menu_key(self: Any, *, fd: int, selector: Callable[..., object]) -> str:
    return self.terminal_ui.planning_menu.read_key(fd=fd, selector=selector)


def _read_planning_menu_escape_sequence(
    *,
    fd: int,
    selector: Callable[..., object],
    timeout: float,
    max_bytes: int,
) -> bytes:
    return RuntimeTerminalUI().planning_menu.read_escape_sequence(
        fd=fd,
        selector=selector,
        timeout=timeout,
        max_bytes=max_bytes,
    )


def _decode_planning_menu_escape(sequence: bytes) -> str | None:
    return RuntimeTerminalUI().planning_menu.decode_escape(sequence)


def _planning_menu_apply_key(
    self: Any,
    *,
    key: str,
    cursor: int,
    planning_files: list[str],
    selected_counts: dict[str, int],
    existing_counts: dict[str, int],
) -> tuple[int, str, str]:
    return self.terminal_ui.planning_menu.apply_key(
        key=key,
        cursor=cursor,
        planning_files=planning_files,
        selected_counts=selected_counts,
        existing_counts=existing_counts,
    )


def _resolve_planning_selection_target(
    self: Any,
    *,
    target_token: str,
    planning_files: list[str],
) -> str:
    token = target_token.strip()
    if not token:
        raise ValueError("Missing planning selection target.")
    if token.isdigit():
        index = int(token)
        if 1 <= index <= len(planning_files):
            return planning_files[index - 1]
        raise ValueError(f"Invalid plan index: {token}")

    normalized = token.replace("\\", "/").lstrip("./")
    planning_raw = str(self.config.planning_dir).replace("\\", "/").rstrip("/")
    base_raw = str(self.config.base_dir).replace("\\", "/").rstrip("/")
    if normalized.startswith(f"{planning_raw}/"):
        normalized = normalized[len(planning_raw) + 1 :]
    if normalized.startswith(f"{base_raw}/"):
        normalized = normalized[len(base_raw) + 1 :]
    planning_rel = ""
    try:
        planning_rel = str(self.config.planning_dir.relative_to(self.config.base_dir)).replace("\\", "/").rstrip("/")
    except ValueError:
        planning_rel = ""
    if planning_rel and normalized.startswith(f"{planning_rel}/"):
        normalized = normalized[len(planning_rel) + 1 :]
    if not normalized.endswith(".md"):
        normalized = f"{normalized}.md"

    if normalized in planning_files:
        return normalized
    basename_matches = [plan for plan in planning_files if Path(plan).name == Path(normalized).name]
    if len(basename_matches) == 1:
        return basename_matches[0]
    if len(basename_matches) > 1:
        raise ValueError(f"Planning file name '{target_token}' is ambiguous. Use folder/name.")
    raise ValueError(f"Planning file not found: {target_token}")


def _plan_selection_memory_path(self: Any) -> Path:
    return _plan_selection_memory_path_impl(runtime_root=self.runtime_root)


def _planning_root(self: Any) -> Path:
    return self.config.planning_dir


def _planning_done_root(self: Any) -> Path:
    return self._planning_root().parent / "done"


def _load_plan_selection_memory(self: Any) -> dict[str, int]:
    return _load_plan_selection_memory_impl(
        runtime_root=self.runtime_root,
        runtime_legacy_root=self.runtime_legacy_root,
    )


def _save_plan_selection_memory(self: Any, selected_counts: dict[str, int]) -> None:
    _save_plan_selection_memory_impl(
        runtime_root=self.runtime_root,
        runtime_legacy_root=self.runtime_legacy_root,
        selected_counts=selected_counts,
    )


def _planning_keep_plan_enabled(self: Any, route: Route) -> bool:
    return _planning_keep_plan_enabled_impl(route=route, env=self.env, config_raw=self.config.raw)


def _sync_plan_worktrees_from_plan_counts(
    self: Any,
    *,
    plan_counts: Mapping[str, int],
    raw_projects: list[tuple[str, Path]],
    keep_plan: bool,
    fresh_ai_launch: bool = False,
    launch_transport: str = "",
) -> PlanWorktreeSyncResult:
    projects = list(raw_projects)
    created_worktrees: list[CreatedPlanWorktree] = []
    removed_worktrees: list[str] = []
    archived_plan_files: list[str] = []
    trees_root = self.config.base_dir / self.config.trees_dir_name
    trees_root.mkdir(parents=True, exist_ok=True)
    policy = _worktree_spinner_policy(self, op_id="worktree.sync")
    enabled = bool(policy.enabled)

    with (
        use_spinner_policy(policy),
        spinner(
            "Syncing planning worktrees...",
            enabled=enabled,
            start_immediately=False,
        ) as active_spinner,
    ):
        _worktree_spinner_start(
            self,
            enabled=enabled,
            active_spinner=active_spinner,
            op_id="worktree.sync",
            message="Syncing planning worktrees...",
        )
        try:
            for plan_file, desired_raw in plan_counts.items():
                target_result = _sync_single_plan_worktree_target(
                    self,
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
            _worktree_spinner_finish(
                self,
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
            _worktree_spinner_fail(
                self,
                enabled=enabled,
                active_spinner=active_spinner,
                op_id="worktree.sync",
                message="Planning worktree sync failed",
            )
            raise
        finally:
            _worktree_spinner_stop(self, enabled=enabled, op_id="worktree.sync")


def _sync_single_plan_worktree_target(
    self: Any,
    *,
    plan_file: str,
    desired_raw: int,
    projects: list[tuple[str, Path]],
    keep_plan: bool,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    fresh_ai_launch: bool = False,
    launch_transport: str = "",
) -> PlanWorktreeSyncResult:
    desired = max(0, int(desired_raw))
    feature = planning_feature_name(plan_file)
    candidates = self._feature_project_candidates(projects=projects, feature=feature)
    existing = len(candidates)
    created_worktrees: tuple[CreatedPlanWorktree, ...] = ()
    removed_worktrees: tuple[str, ...] = ()
    archived_plan_files: tuple[str, ...] = ()

    if desired > existing:
        create_count = desired - existing
        rendered_plan_path = _render_planning_path(
            self,
            absolute_path=self._planning_root() / plan_file,
            display_text=plan_file,
            interactive_tty=(True if enabled else None),
        )
        _worktree_spinner_update(
            self,
            enabled=enabled,
            active_spinner=active_spinner,
            op_id=op_id,
            message=f"Setting up {create_count} worktree(s) for {plan_file} -> {feature}...",
            terminal_message=(
                f"Setting up {create_count} worktree(s) for "
                f"{rendered_plan_path} -> {feature}..."
            ),
        )
        create_result = _create_feature_worktrees_result(
            self,
            feature=feature,
            count=create_count,
            plan_file=plan_file,
            created_for_fresh_ai_launch=fresh_ai_launch,
            launch_transport=launch_transport,
        )
        if create_result.error:
            return PlanWorktreeSyncResult(raw_projects=projects, error=create_result.error)
        created_worktrees = create_result.created_worktrees
        projects = discover_tree_projects(self.config.base_dir, self.config.trees_dir_name)
        candidates = self._feature_project_candidates(projects=projects, feature=feature)
        existing = len(candidates)

    if desired < existing:
        remove_count = existing - desired
        rendered_plan_path = _render_planning_path(
            self,
            absolute_path=self._planning_root() / plan_file,
            display_text=plan_file,
            interactive_tty=(True if enabled else None),
        )
        _worktree_spinner_update(
            self,
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
        remove_error = self._delete_feature_worktrees(
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
        projects = discover_tree_projects(self.config.base_dir, self.config.trees_dir_name)
        current_names = {name for name, _root in projects}
        removed_worktrees = tuple(name for name, _root in candidates if name not in current_names)
        print(
            f"Blasted and deleted {len(removed_worktrees)} worktree(s) for "
            f"{rendered_plan_path}."
        )
        if desired == 0:
            self._cleanup_empty_feature_root(feature=feature)
            projects = discover_tree_projects(self.config.base_dir, self.config.trees_dir_name)

    remaining_feature_worktrees = self._feature_project_candidates(projects=projects, feature=feature)
    if desired == 0 and existing > 0 and not keep_plan and not remaining_feature_worktrees:
        self._move_plan_to_done(plan_file)
        archived_plan_files = (plan_file,)
    return PlanWorktreeSyncResult(
        raw_projects=projects,
        created_worktrees=created_worktrees,
        removed_worktrees=removed_worktrees,
        archived_plan_files=archived_plan_files,
    )


def _create_feature_worktrees(self: Any, *, feature: str, count: int, plan_file: str) -> str | None:
    return _create_feature_worktrees_result(self, feature=feature, count=count, plan_file=plan_file).error


def _create_feature_worktrees_result(
    self: Any,
    *,
    feature: str,
    count: int,
    plan_file: str,
    created_for_fresh_ai_launch: bool = False,
    launch_transport: str = "",
) -> PlanWorktreeSyncResult:
    if count <= 0:
        return PlanWorktreeSyncResult(raw_projects=[])
    feature_root = self._preferred_tree_root_for_feature(feature)
    feature_root.mkdir(parents=True, exist_ok=True)
    existing_iters = {int(path.name) for path in feature_root.iterdir() if path.is_dir() and path.name.isdigit()}
    plan_path = self._planning_root() / plan_file
    setup_env = self._command_env(port=0, extra={"PLAN_FILE": str(plan_path)})
    created_worktrees: list[CreatedPlanWorktree] = []
    requested_cli = str(
        self.env.get("ENVCTL_PLAN_AGENT_CLI") or self.config.raw.get("ENVCTL_PLAN_AGENT_CLI") or ""
    ).strip().lower()
    cli_sequence = (["codex", "opencode"] if requested_cli == "both" and count == 2 else [""] * count)

    for index in range(count):
        iteration = self._next_available_iteration(existing_iters)
        target = feature_root / str(iteration)
        result = _run_worktree_add(self, feature=feature, iteration=str(iteration), target=target, env=setup_env)
        if getattr(result, "returncode", 1) != 0:
            if _recover_partial_worktree_creation(
                self,
                feature=feature,
                iteration=str(iteration),
                target=target,
                result=result,
            ):
                _write_worktree_provenance(
                    self,
                    target=target,
                    plan_file=plan_file,
                    created_for_fresh_ai_launch=created_for_fresh_ai_launch,
                    launch_transport=launch_transport,
                )
                _prepare_worktree_code_intelligence(self, target=target)
            else:
                error = self._worktree_add_failure(
                    feature=feature,
                    iteration=str(iteration),
                    target=target,
                    result=result,
                )
                if error:
                    return PlanWorktreeSyncResult(
                        raw_projects=[],
                        created_worktrees=tuple(created_worktrees),
                        error=error,
                    )
        else:
            _write_worktree_provenance(
                self,
                target=target,
                plan_file=plan_file,
                created_for_fresh_ai_launch=created_for_fresh_ai_launch,
                launch_transport=launch_transport,
            )
            _prepare_worktree_code_intelligence(self, target=target)
        _seed_main_task_from_plan(target=target, plan_path=plan_path)
        worktree_cli = cli_sequence[index] if index < len(cli_sequence) else ""
        created_worktrees.append(
            CreatedPlanWorktree(
                name=_worktree_project_name_impl(feature=feature, iteration=iteration),
                root=target.resolve(),
                plan_file=plan_file,
                cli=worktree_cli,
            )
        )
        existing_iters.add(iteration)
    return PlanWorktreeSyncResult(raw_projects=[], created_worktrees=tuple(created_worktrees))


def _worktree_add_failure(self: Any, *, feature: str, iteration: str, target: Path, result: object) -> str | None:
    return _worktree_add_failure_impl(
        feature=feature,
        iteration=iteration,
        target=target,
        result=result,
        placeholder_fallback_enabled=self._setup_worktree_placeholder_fallback_enabled(),
        command_result_error_text=lambda command_result: self._command_result_error_text(result=command_result),
        link_repo_local_shared_artifacts=lambda linked_target: _link_repo_local_shared_artifacts(
            self,
            target=linked_target,
        ),
        emit=self._emit,
    )


def _recover_partial_worktree_creation(
    self: Any,
    *,
    feature: str,
    iteration: str,
    target: Path,
    result: object,
) -> bool:
    return _recover_partial_worktree_creation_impl(
        git_hooks_disabled=_worktree_git_hooks_disabled(self),
        target=target,
        feature=feature,
        iteration=iteration,
        result=result,
        command_result_error_text=lambda command_result: self._command_result_error_text(result=command_result),
        emit=self._emit,
    )


def _worktree_target_created(target: Path) -> bool:
    return _worktree_target_created_impl(target)


def _run_worktree_add(self: Any, *, feature: str, iteration: str, target: Path, env: Mapping[str, str]) -> object:
    return _run_worktree_add_impl(
        repo_root=self.config.base_dir,
        feature=feature,
        iteration=iteration,
        target=target,
        env=env,
        git_hooks_disabled=_worktree_git_hooks_disabled(self),
        branch_exists=lambda branch_name: _worktree_branch_exists(self, branch_name=branch_name),
        start_point=lambda: _worktree_start_point(self),
        run=self.process_runner.run,
    )


def _worktree_branch_name(*, feature: str, iteration: str) -> str:
    return _worktree_branch_name_impl(feature=feature, iteration=iteration)


def _worktree_branch_exists(self: Any, *, branch_name: str) -> bool:
    return _worktree_branch_exists_impl(
        branch_name=branch_name,
        git_command_output=lambda args: _git_command_output(self, args),
    )


def _worktree_start_point(self: Any) -> str | None:
    return _worktree_start_point_impl(
        provenance=_build_worktree_provenance(self) or {},
        git_command_output=lambda args: _git_command_output(self, args),
    )


def _setup_worktree_placeholder_fallback_enabled(self: Any) -> bool:
    return _setup_worktree_placeholder_fallback_enabled_impl(env=self.env, config_raw=self.config.raw)


def _worktree_git_hooks_policy(self: Any) -> str:
    return _worktree_git_hooks_policy_impl(self)


def _worktree_git_hooks_disabled(self: Any) -> bool:
    return _worktree_git_hooks_disabled_impl(self)


def _write_worktree_provenance(
    self: Any,
    *,
    target: Path,
    plan_file: str | None = None,
    created_for_fresh_ai_launch: bool = False,
    launch_transport: str = "",
) -> None:
    _write_worktree_provenance_impl(
        self,
        target=target,
        plan_file=plan_file,
        created_for_fresh_ai_launch=created_for_fresh_ai_launch,
        launch_transport=launch_transport,
    )


def _link_repo_local_shared_artifacts(self: Any, *, target: Path) -> None:
    _link_repo_local_shared_artifacts_impl(repo_root=self.config.base_dir, target=target)


def _prepare_worktree_code_intelligence(self: Any, *, target: Path) -> None:
    _prepare_worktree_code_intelligence_impl(
        self,
        target=target,
        trees_root_for_worktree=_trees_root_for_worktree,
    )


def _build_worktree_provenance(
    self: Any,
    *,
    plan_file: str | None = None,
    created_for_fresh_ai_launch: bool = False,
    launch_transport: str = "",
) -> dict[str, object] | None:
    return _build_worktree_provenance_impl(
        self,
        plan_file=plan_file,
        created_for_fresh_ai_launch=created_for_fresh_ai_launch,
        launch_transport=launch_transport,
    )


def _resolve_branch_ref(self: Any, *, source_branch: str) -> str:
    return _resolve_branch_ref_impl(self, source_branch=source_branch)


def _detect_default_branch(self: Any) -> str:
    return _detect_default_branch_impl(self)


def _git_command_output(self: Any, args: list[str]) -> str:
    return _git_command_output_impl(self, args)


def _seed_main_task_from_plan(*, target: Path, plan_path: Path) -> None:
    _seed_main_task_from_plan_impl(target=target, plan_path=plan_path)


def _delete_feature_worktrees(
    self: Any,
    *,
    feature: str,
    candidates: list[tuple[str, Path]],
    remove_count: int,
) -> str | None:
    return _delete_feature_worktrees_impl(
        feature=feature,
        candidates=candidates,
        remove_count=remove_count,
        project_sort_key_for_feature=self._project_sort_key_for_feature,
        active_protection_reason=lambda *, name, root: _active_fresh_ai_worktree_protection_reason(
            self,
            name=name,
            root=root,
        ),
        blast_worktree_before_delete=getattr(self, "_blast_worktree_before_delete", None),
        delete_worktree=delete_worktree_path,
        repo_root=self.config.base_dir,
        trees_root_for_worktree=self._trees_root_for_worktree,
        process_runner=self.process_runner,
        emit=self._emit,
    )


def _active_fresh_ai_worktree_protection_reason(self: Any, *, name: str, root: Path) -> str:
    return _active_fresh_ai_worktree_protection_reason_impl(self, name=name, root=root)


def _fresh_ai_launch_marker_is_fresh(recorded_at: str) -> bool:
    return _fresh_ai_launch_marker_is_fresh_impl(recorded_at)


def _read_worktree_provenance(root: Path) -> dict[str, object]:
    return _read_worktree_provenance_impl(root)


def _cleanup_empty_feature_root(self: Any, *, feature: str) -> None:
    _cleanup_empty_feature_root_impl(
        preferred_tree_root_for_feature=self._preferred_tree_root_for_feature,
        feature=feature,
    )


def _move_plan_to_done(self: Any, plan_file: str) -> None:
    _move_plan_to_done_impl(
        plan_file=plan_file,
        planning_root=self._planning_root(),
        planning_done_root=self._planning_done_root(),
        render_path=lambda *, absolute_path, display_text: _render_planning_path(
            self,
            absolute_path=absolute_path,
            display_text=display_text,
        ),
        emit_message=print,
    )


def _feature_project_candidates(
    self: Any,
    *,
    projects: list[tuple[str, Path]],
    feature: str,
) -> list[tuple[str, Path]]:
    return _feature_project_candidates_impl(projects=projects, feature=feature)


def _project_sort_key_for_feature(project_name: str, feature: str) -> tuple[int, object]:
    return _project_sort_key_for_feature_impl(project_name, feature)


def _next_available_iteration(existing_iters: set[int]) -> int:
    return _next_available_iteration_impl(existing_iters)


def _setup_worktree_requested(route: Route) -> bool:
    return bool(route.flags.get("setup_worktrees")) or bool(route.flags.get("setup_worktree"))
