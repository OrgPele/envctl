from __future__ import annotations

# pyright: reportUnusedFunction=false

import json
import re
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Protocol

from envctl_engine.actions.actions_worktree import delete_worktree_path
from envctl_engine.planning.plan_agent_launch_support import (
    CreatedPlanWorktree,
    PlanSelectionResult,
    PlanWorktreeSyncResult,
)
from envctl_engine.runtime.command_router import Route
from envctl_engine.shared.parsing import parse_bool, parse_int
from envctl_engine.planning import (
    discover_tree_projects,
    filter_projects_for_plan,
    list_planning_files,
    planning_existing_counts,
    planning_feature_name,
    resolve_planning_files,
    select_projects_for_plan_files,
)
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI
from envctl_engine.ui.spinner import spinner, use_spinner_policy
from envctl_engine.ui.spinner_service import SpinnerPolicy, emit_spinner_policy, resolve_spinner_policy
from envctl_engine.ui.textual.screens.planning_selector import select_planning_counts_textual


class ProjectContextLike(Protocol):
    name: str
    root: Path


WORKTREE_PROVENANCE_SCHEMA_VERSION = 1
WORKTREE_PROVENANCE_PATH = Path(".envctl-state") / "worktree-provenance.json"


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
) -> None:
    if enabled:
        active_spinner.update(message)
        self._emit(  # type: ignore[attr-defined]
            "ui.spinner.lifecycle",
            component="worktree_planning",
            op_id=op_id,
            state="update",
            message=message,
        )
        return
    print(message)


def _worktree_spinner_start(
    self: Any,
    *,
    enabled: bool,
    active_spinner: Any,
    op_id: str,
    message: str,
) -> None:
    if not enabled:
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
    raw = route.flags.get(flag_name)
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise RuntimeError(f"Invalid {flag_name} flag payload.")
    entries: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise RuntimeError(f"Invalid {flag_name} flag payload.")
        feature = str(item.get("feature", "")).strip()
        value = str(item.get(value_name, "")).strip()
        if not feature:
            raise RuntimeError(f"Missing feature for {flag_name}.")
        if "/" in feature or feature in {".", ".."}:
            raise RuntimeError(f"Invalid feature name for {flag_name}: {feature}")
        if not value:
            raise RuntimeError(f"Missing {value_name} for {flag_name}.")
        entries.append((feature, value))
    return entries


def _create_single_worktree(self, *, feature: str, iteration: str) -> str | None:
    feature_root = self._preferred_tree_root_for_feature(feature)
    feature_root.mkdir(parents=True, exist_ok=True)
    target = feature_root / iteration
    result = _run_worktree_add(self, feature=feature, iteration=iteration, target=target, env=self._command_env(port=0))
    if getattr(result, "returncode", 1) != 0:
        error = self._worktree_add_failure(
            feature=feature,
            iteration=iteration,
            target=target,
            result=result,
        )
        if error:
            return error
    else:
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
                project_lookup = {name.lower(): name for name, _root in raw_projects}
                missing: list[str] = []
                for token in include_list:
                    direct = project_lookup.get(token.lower())
                    if direct is not None:
                        selected_names.add(direct)
                        continue
                    resolved = None
                    if token.isdigit():
                        for feature in setup_features:
                            candidate_name = f"{feature}-{token}"
                            candidate = project_lookup.get(candidate_name.lower())
                            if candidate is not None:
                                resolved = candidate
                                break
                    if resolved is not None:
                        selected_names.add(resolved)
                    else:
                        missing.append(token)
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
    count = parse_int(count_raw, -1)
    if count < 1:
        raise RuntimeError(f"Invalid count for --setup-worktrees {feature}: {count_raw}")
    before = {name for name, _root in self._feature_project_candidates(projects=raw_projects, feature=feature)}
    _worktree_spinner_update(
        self,
        enabled=enabled,
        active_spinner=active_spinner,
        op_id=op_id,
        message=f"Setting up {count} worktree(s) for {feature}...",
    )
    create_error = self._create_feature_worktrees(
        feature=feature,
        count=count,
        plan_file=f"_setup/{feature}.md",
    )
    if create_error:
        raise RuntimeError(create_error)
    raw_projects = discover_tree_projects(self.config.base_dir, self.config.trees_dir_name)
    candidates = self._feature_project_candidates(projects=raw_projects, feature=feature)
    after = {name for name, _root in candidates}
    created = after.difference(before)
    return raw_projects, (created or after)


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
    if not iteration_raw.isdigit() or int(iteration_raw) < 1:
        raise RuntimeError(f"Invalid iteration for --setup-worktree {feature}: {iteration_raw}")
    iteration = str(int(iteration_raw))
    feature_root = self._preferred_tree_root_for_feature(feature)
    target_root = feature_root / iteration
    _worktree_spinner_update(
        self,
        enabled=enabled,
        active_spinner=active_spinner,
        op_id=op_id,
        message=f"Ensuring worktree {feature}/{iteration}...",
    )
    if target_root.exists():
        if setup_worktree_recreate:
            result = delete_worktree_path(
                repo_root=self.config.base_dir,
                trees_root=self._trees_root_for_worktree(target_root),
                worktree_root=target_root,
                process_runner=self.process_runner,
            )
            if not result.success:
                raise RuntimeError(result.message)
        elif not setup_worktree_existing:
            raise RuntimeError(
                f"Worktree {feature}/{iteration} already exists. "
                "Use --setup-worktree-existing or --setup-worktree-recreate."
            )
    if not target_root.exists():
        create_error = self._create_single_worktree(feature=feature, iteration=iteration)
        if create_error:
            raise RuntimeError(create_error)
    refreshed_projects = discover_tree_projects(self.config.base_dir, self.config.trees_dir_name)
    return refreshed_projects, f"{feature}-{iteration}"


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
                )
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

    plan_counts = self._prompt_planning_selection(planning_files, raw_projects)
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

    sync_result = self._sync_plan_worktrees_from_plan_counts(
        plan_counts=plan_counts,
        raw_projects=raw_projects,
        keep_plan=keep_plan,
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

    positive_plan_counts = {plan_file: count for plan_file, count in plan_counts.items() if int(count) > 0}
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
    if chosen:
        self._save_plan_selection_memory(chosen)
    return chosen


def _initial_plan_selected_counts(
    self: Any,
    *,
    planning_files: list[str],
    existing_counts: dict[str, int],
) -> dict[str, int]:
    remembered = self._load_plan_selection_memory()
    selected_counts: dict[str, int] = {}
    for plan_file in planning_files:
        existing = int(existing_counts.get(plan_file, 0))
        remembered_value = int(remembered.get(plan_file, 0))
        selected_counts[plan_file] = existing if existing > 0 else max(remembered_value, 0)
    return selected_counts


def _run_planning_selection_menu(
    self: Any,
    *,
    planning_files: list[str],
    selected_counts: dict[str, int],
    existing_counts: dict[str, int],
) -> dict[str, int] | None:
    from envctl_engine.ui.terminal_session import _reset_terminal_escape_modes, normalize_standard_tty_state

    try:
        self._flush_pending_interactive_input()
        chosen = select_planning_counts_textual(
            planning_files=planning_files,
            selected_counts=selected_counts,
            existing_counts=existing_counts,
            emit=getattr(self, "_emit", None),
        )
        if chosen is None:
            return None
        return chosen
    except Exception:
        return {plan_file: count for plan_file, count in selected_counts.items() if count > 0}
    finally:
        emit = getattr(self, "_emit", None)
        normalize_standard_tty_state(emit=emit, component="planning.worktree_domain")
        _reset_terminal_escape_modes(emit=emit)


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
    return self.runtime_root / "planning_selection.json"


def _planning_root(self: Any) -> Path:
    return self.config.planning_dir


def _planning_done_root(self: Any) -> Path:
    return self._planning_root().parent / "done"


def _load_plan_selection_memory(self: Any) -> dict[str, int]:
    path = self._plan_selection_memory_path()
    legacy_path = self.runtime_legacy_root / "planning_selection.json"
    for candidate in (path, legacy_path):
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(payload, dict):
            continue
        remembered = payload.get("selected_counts", {})
        if not isinstance(remembered, dict):
            continue
        result: dict[str, int] = {}
        for key, value in remembered.items():
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                continue
            if parsed >= 0:
                result[str(key)] = parsed
        if result:
            return result
    return {}


def _save_plan_selection_memory(self: Any, selected_counts: dict[str, int]) -> None:
    path = self._plan_selection_memory_path()
    payload = {
        "selected_counts": dict(sorted({k: int(v) for k, v in selected_counts.items() if int(v) > 0}.items())),
        "saved_at": datetime.now(UTC).isoformat(),
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    path.write_text(text, encoding="utf-8")
    self.runtime_legacy_root.mkdir(parents=True, exist_ok=True)
    (self.runtime_legacy_root / "planning_selection.json").write_text(text, encoding="utf-8")


def _planning_keep_plan_enabled(self: Any, route: Route) -> bool:
    if bool(route.flags.get("keep_plan")):
        return True
    raw = self.env.get("PLANNING_KEEP_PLAN") or self.config.raw.get("PLANNING_KEEP_PLAN")
    return parse_bool(raw, False)


def _sync_plan_worktrees_from_plan_counts(
    self: Any,
    *,
    plan_counts: Mapping[str, int],
    raw_projects: list[tuple[str, Path]],
    keep_plan: bool,
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
        _worktree_spinner_update(
            self,
            enabled=enabled,
            active_spinner=active_spinner,
            op_id=op_id,
            message=f"Setting up {create_count} worktree(s) for {plan_file} -> {feature}...",
        )
        create_result = _create_feature_worktrees_result(
            self,
            feature=feature,
            count=create_count,
            plan_file=plan_file,
        )
        if create_result.error:
            return PlanWorktreeSyncResult(raw_projects=projects, error=create_result.error)
        created_worktrees = create_result.created_worktrees
        projects = discover_tree_projects(self.config.base_dir, self.config.trees_dir_name)
        candidates = self._feature_project_candidates(projects=projects, feature=feature)
        existing = len(candidates)

    if desired < existing:
        remove_count = existing - desired
        _worktree_spinner_update(
            self,
            enabled=enabled,
            active_spinner=active_spinner,
            op_id=op_id,
            message=(
                f"Selected count for {plan_file} ({desired}) is below existing ({existing}); "
                f"removing {remove_count} worktree(s)."
            ),
        )
        remove_error = self._delete_feature_worktrees(
            feature=feature,
            candidates=candidates,
            remove_count=remove_count,
        )
        if remove_error:
            return PlanWorktreeSyncResult(raw_projects=projects, created_worktrees=created_worktrees, error=remove_error)
        print(f"Blasted and deleted {remove_count} worktree(s) for {plan_file}.")
        removed_worktrees = tuple(name for name, _root in sorted(
            candidates,
            key=lambda item: self._project_sort_key_for_feature(item[0], feature),
            reverse=True,
        )[:remove_count])
        projects = discover_tree_projects(self.config.base_dir, self.config.trees_dir_name)
        if desired == 0:
            self._cleanup_empty_feature_root(feature=feature)
            projects = discover_tree_projects(self.config.base_dir, self.config.trees_dir_name)

    if desired == 0 and existing > 0 and not keep_plan:
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
) -> PlanWorktreeSyncResult:
    if count <= 0:
        return PlanWorktreeSyncResult(raw_projects=[])
    feature_root = self._preferred_tree_root_for_feature(feature)
    feature_root.mkdir(parents=True, exist_ok=True)
    existing_iters = {int(path.name) for path in feature_root.iterdir() if path.is_dir() and path.name.isdigit()}
    plan_path = self._planning_root() / plan_file
    setup_env = self._command_env(port=0, extra={"PLAN_FILE": str(plan_path)})
    created_worktrees: list[CreatedPlanWorktree] = []

    for _ in range(count):
        iteration = self._next_available_iteration(existing_iters)
        target = feature_root / str(iteration)
        result = _run_worktree_add(self, feature=feature, iteration=str(iteration), target=target, env=setup_env)
        if getattr(result, "returncode", 1) != 0:
            error = self._worktree_add_failure(
                feature=feature,
                iteration=str(iteration),
                target=target,
                result=result,
            )
            if error:
                return PlanWorktreeSyncResult(raw_projects=[], created_worktrees=tuple(created_worktrees), error=error)
        else:
            _write_worktree_provenance(self, target=target)
        _seed_main_task_from_plan(target=target, plan_path=plan_path)
        created_worktrees.append(
            CreatedPlanWorktree(name=f"{feature}-{iteration}", root=target.resolve(), plan_file=plan_file)
        )
        existing_iters.add(iteration)
    return PlanWorktreeSyncResult(raw_projects=[], created_worktrees=tuple(created_worktrees))


def _worktree_add_failure(self: Any, *, feature: str, iteration: str, target: Path, result: object) -> str | None:
    reason = self._command_result_error_text(result=result)
    if self._setup_worktree_placeholder_fallback_enabled():
        target.mkdir(parents=True, exist_ok=True)
        marker = target / ".envctl_worktree_placeholder"
        marker.write_text(
            (
                "envctl placeholder worktree created after git worktree add failure\n"
                f"feature={feature}\n"
                f"iteration={iteration}\n"
                f"error={reason}\n"
            ),
            encoding="utf-8",
        )
        self._emit(
            "setup.worktree.placeholder_fallback",
            feature=feature,
            iteration=iteration,
            target=str(target),
            reason=reason,
        )
        return None
    return f"failed creating worktree {feature}/{iteration}: {reason}"


def _run_worktree_add(self: Any, *, feature: str, iteration: str, target: Path, env: Mapping[str, str]) -> object:
    branch_name = _worktree_branch_name(feature=feature, iteration=iteration)
    start_point = _worktree_start_point(self)
    branch_flag = "-B" if _worktree_branch_exists(self, branch_name=branch_name) else "-b"
    command = [
        "git",
        "-C",
        str(self.config.base_dir),
        "worktree",
        "add",
        branch_flag,
        branch_name,
        str(target),
    ]
    if start_point:
        command.append(start_point)
    return self.process_runner.run(
        command,
        cwd=self.config.base_dir,
        env=env,
        timeout=120.0,
    )


def _worktree_branch_name(*, feature: str, iteration: str) -> str:
    return f"{feature}-{iteration}"


def _worktree_branch_exists(self: Any, *, branch_name: str) -> bool:
    normalized = branch_name.strip()
    if not normalized:
        return False
    return bool(_git_command_output(self, ["rev-parse", "--verify", f"refs/heads/{normalized}"]).strip())


def _worktree_start_point(self: Any) -> str | None:
    provenance = _build_worktree_provenance(self) or {}
    for key in ("source_ref", "source_branch"):
        candidate = str(provenance.get(key, "")).strip()
        if candidate and _git_command_output(self, ["rev-parse", "--verify", candidate]).strip():
            return candidate
    head_commit = _git_command_output(self, ["rev-parse", "HEAD"]).strip()
    return head_commit or None


def _setup_worktree_placeholder_fallback_enabled(self: Any) -> bool:
    raw = self.env.get("ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK") or self.config.raw.get(
        "ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK"
    )
    return parse_bool(raw, False)


def _write_worktree_provenance(self: Any, *, target: Path) -> None:
    provenance = _build_worktree_provenance(self)
    if provenance is None or not target.is_dir():
        return
    path = target / WORKTREE_PROVENANCE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    except OSError:
        return


def _build_worktree_provenance(self: Any) -> dict[str, object] | None:
    source_branch = _git_command_output(self, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if source_branch and source_branch != "HEAD":
        return _worktree_provenance_payload(self, source_branch=source_branch, resolution_reason="attached_branch")

    default_branch = _detect_default_branch(self)
    if not default_branch:
        return None
    return _worktree_provenance_payload(
        self,
        source_branch=default_branch,
        resolution_reason="default_branch_detached_head",
    )


def _worktree_provenance_payload(
    self: Any,
    *,
    source_branch: str,
    resolution_reason: str,
) -> dict[str, object]:
    source_ref = _resolve_branch_ref(self, source_branch=source_branch)
    return {
        "schema_version": WORKTREE_PROVENANCE_SCHEMA_VERSION,
        "source_branch": source_branch,
        "source_ref": source_ref or source_branch,
        "resolution_reason": resolution_reason,
        "created_from_repo": str(self.config.base_dir.resolve()),
        "recorded_at": datetime.now(tz=UTC).isoformat(),
    }


def _resolve_branch_ref(self: Any, *, source_branch: str) -> str:
    normalized = source_branch.strip()
    if not normalized:
        return ""
    for candidate in (f"origin/{normalized}", normalized):
        if _git_command_output(self, ["rev-parse", "--verify", candidate]).strip():
            return candidate
    return normalized


def _detect_default_branch(self: Any) -> str:
    ref = _git_command_output(self, ["symbolic-ref", "--short", "refs/remotes/origin/HEAD"]).strip()
    if ref.startswith("origin/"):
        return ref.split("origin/", 1)[1]
    for candidate in ("main", "master"):
        if _git_command_output(self, ["rev-parse", "--verify", candidate]).strip():
            return candidate
    return "main"


def _git_command_output(self: Any, args: list[str]) -> str:
    result = self.process_runner.run(
        ["git", "-C", str(self.config.base_dir), *args],
        cwd=self.config.base_dir,
        env=self._command_env(port=0),
        timeout=30.0,
    )
    if getattr(result, "returncode", 1) != 0:
        return ""
    return str(getattr(result, "stdout", ""))


def _seed_main_task_from_plan(*, target: Path, plan_path: Path) -> None:
    if not plan_path.is_file() or not target.is_dir():
        return
    try:
        plan_text = plan_path.read_text(encoding="utf-8")
    except OSError:
        return
    if not plan_text.strip():
        return
    main_task_path = target / "MAIN_TASK.md"
    try:
        main_task_path.write_text(plan_text if plan_text.endswith("\n") else f"{plan_text}\n", encoding="utf-8")
    except OSError:
        return


def _delete_feature_worktrees(
    self: Any,
    *,
    feature: str,
    candidates: list[tuple[str, Path]],
    remove_count: int,
) -> str | None:
    if remove_count <= 0:
        return None
    ordered = sorted(
        candidates,
        key=lambda item: self._project_sort_key_for_feature(item[0], feature),
        reverse=True,
    )
    for _name, root in ordered[:remove_count]:
        blast_cleanup = getattr(self, "_blast_worktree_before_delete", None)
        if callable(blast_cleanup):
            warnings = blast_cleanup(
                project_name=_name,
                project_root=root,
                source_command="blast-worktree",
            )
            for warning in warnings:
                self._emit(  # type: ignore[attr-defined]
                    "cleanup.worktree.warning",
                    project=_name,
                    warning=warning,
                    source_command="blast-worktree",
                )
        result = delete_worktree_path(
            repo_root=self.config.base_dir,
            trees_root=self._trees_root_for_worktree(root),
            worktree_root=root,
            process_runner=self.process_runner,
        )
        if not result.success:
            return result.message
    return None


def _cleanup_empty_feature_root(self: Any, *, feature: str) -> None:
    feature_root = self._preferred_tree_root_for_feature(feature)
    if not feature_root.is_dir():
        return
    try:
        next(feature_root.iterdir())
    except StopIteration:
        try:
            feature_root.rmdir()
        except OSError:
            return


def _move_plan_to_done(self: Any, plan_file: str) -> None:
    src = self._planning_root() / plan_file
    if not src.is_file():
        return
    rel_dir = Path(plan_file).parent
    if str(rel_dir) in {"", "."}:
        rel_dir = Path("_misc")
    done_dir = self._planning_done_root() / rel_dir
    done_dir.mkdir(parents=True, exist_ok=True)
    dest = done_dir / src.name
    if dest.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        dest = done_dir / f"{src.stem}-{stamp}{src.suffix}"
    src.replace(dest)
    relative_done = dest.relative_to(self._planning_done_root())
    print(f"Moved {plan_file} to done/{relative_done}.")


def _feature_project_candidates(
    self: Any,
    *,
    projects: list[tuple[str, Path]],
    feature: str,
) -> list[tuple[str, Path]]:
    lowered_feature = feature.lower()
    prefix = f"{lowered_feature}-"
    candidates = [
        project
        for project in projects
        if project[0].lower() == lowered_feature or project[0].lower().startswith(prefix)
    ]
    candidates.sort(key=lambda item: self._project_sort_key_for_feature(item[0], feature))
    return candidates


def _project_sort_key_for_feature(project_name: str, feature: str) -> tuple[int, object]:
    lowered = project_name.lower()
    feature_prefix = f"{feature.lower()}-"
    if lowered == feature.lower():
        return (0, 0)
    if not lowered.startswith(feature_prefix):
        return (3, lowered)
    suffix = lowered[len(feature_prefix) :]
    if suffix.isdigit():
        return (1, int(suffix))
    iter_match = re.fullmatch(r"iter[-_]?(\d+)", suffix)
    if iter_match:
        return (1, int(iter_match.group(1)))
    return (2, suffix)


def _next_available_iteration(existing_iters: set[int]) -> int:
    candidate = 1
    while candidate in existing_iters:
        candidate += 1
    return candidate


def _setup_worktree_requested(route: Route) -> bool:
    return bool(route.flags.get("setup_worktrees")) or bool(route.flags.get("setup_worktree"))
