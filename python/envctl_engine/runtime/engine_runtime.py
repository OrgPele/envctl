from __future__ import annotations

import shutil as _shutil
import sys as _sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

from envctl_engine.runtime.engine_runtime_diagnostics import (
    lock_health_summary as runtime_lock_health_summary,
    parity_manifest_info as runtime_parity_manifest_info,
    parity_manifest_is_complete as runtime_parity_manifest_is_complete,
    pointer_status_summary as runtime_pointer_status_summary,
)
from envctl_engine.runtime.engine_runtime_debug_support import (
    debug_pack as runtime_debug_pack,
    debug_doctor_snapshot_text as runtime_debug_doctor_snapshot_text,
    debug_last as runtime_debug_last,
    debug_report as runtime_debug_report,
    latest_debug_scope_session as runtime_latest_debug_scope_session,
    latest_scope_session_id as runtime_latest_scope_session_id,
    scope_latest_run_id as runtime_scope_latest_run_id,
)
from envctl_engine.runtime.engine_runtime_misc_support import (
    batch_mode_requested as runtime_batch_mode_requested,
    build_process_probe_backend as runtime_build_process_probe_backend,
    is_truthy as runtime_is_truthy,
    listener_truth_enforced as runtime_listener_truth_enforced,
    probe_psutil_enabled as runtime_probe_psutil_enabled,
    recent_failure_messages as runtime_recent_failure_messages,
    release_port_session as runtime_release_port_session,
    requirement_bind_max_retries as runtime_requirement_bind_max_retries,
    route_has_explicit_mode as runtime_route_has_explicit_mode,
    should_enter_dashboard_interactive as runtime_should_enter_dashboard_interactive,
    should_enter_post_start_interactive as runtime_should_enter_post_start_interactive,
    should_enter_resume_interactive as runtime_should_enter_resume_interactive,
    state_compat_mode as runtime_state_compat_mode,
    tokens_set_mode as runtime_tokens_set_mode,
)
from envctl_engine.runtime.engine_runtime_event_support import (
    bind_debug_run_id as runtime_bind_debug_run_id,
    configure_debug_recorder as runtime_configure_debug_recorder,
    current_session_id as runtime_current_session_id,
    emit as runtime_emit,
    persist_events_snapshot as runtime_persist_events_snapshot,
)
from envctl_engine.runtime.engine_runtime_runtime_support import (
    conflict_count as runtime_conflict_count,
    error_report_path as runtime_error_report_path,
    lock_inventory as runtime_lock_inventory,
    new_run_id as runtime_new_run_id,
    normalize_log_line as runtime_normalize_log_line,
    probe_listener_support as runtime_probe_listener_support,
    run_dir_path as runtime_run_dir_path,
    run_state_path as runtime_run_state_path,
    runtime_map_path as runtime_runtime_map_path,
)
from envctl_engine.runtime.engine_runtime_lifecycle_support import (
    blast_worktree_before_delete as runtime_blast_worktree_before_delete,
    release_requirement_ports as runtime_release_requirement_ports,
    service_port as runtime_service_port,
    terminate_service_record as runtime_terminate_service_record,
    terminate_services_from_state as runtime_terminate_services_from_state,
    terminate_started_services as runtime_terminate_started_services,
)
from envctl_engine.runtime.engine_runtime_startup_support import (
    contexts_from_raw_projects as runtime_contexts_from_raw_projects,
    discover_projects as runtime_discover_projects,
    duplicate_project_context_error as runtime_duplicate_project_context_error,
    effective_start_mode as runtime_effective_start_mode,
    reserve_project_ports as runtime_reserve_project_ports,
    sanitize_legacy_resume_state as runtime_sanitize_legacy_resume_state,
    set_plan_port as runtime_set_plan_port,
    set_plan_port_from_component as runtime_set_plan_port_from_component,
    state_has_resumable_services as runtime_state_has_resumable_services,
    tree_parallel_startup_config as runtime_tree_parallel_startup_config,
)
from envctl_engine.runtime.engine_runtime_artifacts import (
    print_summary as runtime_print_summary,
    write_artifacts as runtime_write_artifacts,
    write_runtime_readiness_report as runtime_write_runtime_readiness_report,
)
from envctl_engine.runtime.engine_runtime_env import (
    runtime_env_overrides as runtime_env_overrides,
)
from envctl_engine.runtime.engine_runtime_service_truth import (
    assert_project_services_post_start_truth as runtime_assert_project_services_post_start_truth,
    listener_pids_for_port as runtime_listener_pids_for_port,
    rebind_stale_service_pid as runtime_rebind_stale_service_pid,
    refresh_service_listener_pids as runtime_refresh_service_listener_pids,
    service_truth_discovery as runtime_service_truth_discovery,
    service_truth_status as runtime_service_truth_status,
    clear_service_listener_pids as runtime_clear_service_listener_pids,
)
from envctl_engine.runtime.engine_runtime_state_support import (
    load_state_artifact as runtime_load_state_artifact,
    on_port_event as runtime_on_port_event,
    run_state_to_json as runtime_run_state_to_json,
    state_action as runtime_state_action,
    state_has_synthetic_services as runtime_state_has_synthetic_services,
    state_lookup_strict_mode_match as runtime_state_lookup_strict_mode_match,
)
from envctl_engine.runtime.engine_runtime_state_lookup import (
    state_matches_scope as runtime_state_matches_scope,
    try_load_existing_state as runtime_try_load_existing_state,
)
from envctl_engine.runtime.engine_runtime_state_truth import (
    reconcile_project_requirement_truth as runtime_reconcile_project_requirement_truth,
    reconcile_state_truth as runtime_reconcile_state_truth,
    requirement_truth_issues as runtime_requirement_truth_issues,
    state_fingerprint as runtime_state_fingerprint,
)
from envctl_engine.runtime.engine_runtime_action_support import (
    action_env as runtime_action_env,
    action_extra_env as runtime_action_extra_env,
    action_replacements as runtime_action_replacements,
    project_name_from_service as runtime_project_name_from_service,
    resolve_action_targets as runtime_resolve_action_targets,
    run_action_command as runtime_run_action_command,
    run_analyze_action as runtime_run_analyze_action,
    run_commit_action as runtime_run_commit_action,
    run_delete_worktree_action as runtime_run_delete_worktree_action,
    run_migrate_action as runtime_run_migrate_action,
    run_pr_action as runtime_run_pr_action,
    run_project_action as runtime_run_project_action,
    run_test_action as runtime_run_test_action,
    selectors_from_passthrough as runtime_selectors_from_passthrough,
)
from envctl_engine.runtime.engine_runtime_cli_support import (
    migrate_hooks as runtime_migrate_hooks,
    print_help as runtime_print_help,
    render_help_text as runtime_render_help_text,
    run_config as runtime_run_config,
    unsupported_command as runtime_unsupported_command,
)
from envctl_engine.runtime.engine_runtime_doctor_support import (
    doctor as runtime_doctor,
    doctor_readiness_gates as runtime_doctor_readiness_gates,
    doctor_should_check_tests as runtime_doctor_should_check_tests,
    enforce_runtime_readiness_contract as runtime_enforce_runtime_readiness_contract,
    evaluate_runtime_shipability as runtime_evaluate_runtime_shipability,
)
from envctl_engine.runtime.engine_runtime_bookkeeping_support import (
    add_emit_listener as runtime_add_emit_listener,
    consume_project_startup_warnings as runtime_consume_project_startup_warnings,
    ensure_legacy_lock_view as runtime_ensure_legacy_lock_view,
    record_project_startup_warning as runtime_record_project_startup_warning,
    reset_project_startup_warnings as runtime_reset_project_startup_warnings,
)
from envctl_engine.runtime.engine_runtime_dispatch import dispatch as runtime_dispatch
from envctl_engine.runtime.engine_runtime_construction import initialize_runtime_construction
from envctl_engine.runtime.engine_runtime_service_facade import RuntimeServiceFacadeMixin
from envctl_engine.runtime.engine_runtime_ui_bridge import (
    can_interactive_tty as bridge_can_interactive_tty,
    dashboard as bridge_dashboard,
    flush_pending_interactive_input as bridge_flush_pending_interactive_input,
    parse_interactive_command as bridge_parse_interactive_command,
    read_interactive_command_line as bridge_read_interactive_command_line,
    recover_single_letter_command_from_escape_fragment as bridge_recover_single_letter_command_from_escape_fragment,
    run_interactive_command as bridge_run_interactive_command,
    run_interactive_dashboard_loop as bridge_run_interactive_dashboard_loop,
    sanitize_interactive_input as bridge_sanitize_interactive_input,
    select_grouped_targets as bridge_select_grouped_targets,
    select_project_targets as bridge_select_project_targets,
)
from envctl_engine.runtime.command_router import (
    MODE_FALSE_TOKENS,
    MODE_MAIN_TOKENS,
    MODE_TREE_TOKENS,
    Route,
)
from envctl_engine.config import EngineConfig
from envctl_engine.state.models import PortPlan, RequirementsResult, RunState, ServiceRecord as ServiceRecord
from envctl_engine.state.runtime_map import build_runtime_map as build_runtime_map
from envctl_engine.shared.process_probe import (
    ProbeBackend,
    PsutilProbeBackend as _PsutilProbeBackend,
    psutil_available as psutil_available,
)
from envctl_engine.startup.session import ProjectStartupResult
from envctl_engine.ui.dashboard.rendering import (
    _dashboard_palette as domain_dashboard_palette,
    _dashboard_status_badge as domain_dashboard_status_badge,
    _print_dashboard_n8n_row as domain_print_dashboard_n8n_row,
    _print_dashboard_service_row as domain_print_dashboard_service_row,
    _print_dashboard_snapshot as domain_print_dashboard_snapshot,
    _print_dashboard_tests_row as domain_print_dashboard_tests_row,
)
from envctl_engine.startup.requirements_startup_domain import (
    _requirement_listener_timeout_seconds as domain_requirement_listener_timeout_seconds,
    _start_requirement_component as domain_start_requirement_component,
    _start_requirement_with_native_adapter as domain_start_requirement_with_native_adapter,
    _wait_for_requirement_listener as domain_wait_for_requirement_listener,
)
from envctl_engine.startup.service_bootstrap_domain import (
    _backend_async_driver_mismatch_error as domain_backend_async_driver_mismatch_error,
    _backend_bootstrap_strict as domain_backend_bootstrap_strict,
    _backend_has_migrations as domain_backend_has_migrations,
    _backend_migration_retry_env_for_async_driver_mismatch as domain_backend_migration_retry_env_for_async_driver_mismatch,  # noqa: E501
    _env_assignment_key as domain_env_assignment_key,
    _override_env_path as domain_override_env_path,
    _prepare_backend_runtime as domain_prepare_backend_runtime,
    _prepare_frontend_runtime as domain_prepare_frontend_runtime,
    _read_env_file_safe as domain_read_env_file_safe,
    _resolve_backend_env_file as domain_resolve_backend_env_file,
    _resolve_frontend_env_file as domain_resolve_frontend_env_file,
    _run_frontend_bootstrap_command as domain_run_frontend_bootstrap_command,
    _rewrite_database_url_to_asyncpg as domain_rewrite_database_url_to_asyncpg,
    _run_backend_bootstrap_command as domain_run_backend_bootstrap_command,
    _run_backend_migration_step as domain_run_backend_migration_step,
    _service_env_from_file as domain_service_env_from_file,
    _skip_local_db_env as domain_skip_local_db_env,
    _sync_backend_env_file as domain_sync_backend_env_file,
)
from envctl_engine.planning.worktree_domain import (
    _cleanup_empty_feature_root as domain_cleanup_empty_feature_root,
    _coerce_setup_entries as domain_coerce_setup_entries,
    _create_feature_worktrees as domain_create_feature_worktrees,
    _create_single_worktree as domain_create_single_worktree,
    _decode_planning_menu_escape as domain_decode_planning_menu_escape,
    _delete_feature_worktrees as domain_delete_feature_worktrees,
    _feature_project_candidates as domain_feature_project_candidates,
    _move_plan_to_done as domain_move_plan_to_done,
    _next_available_iteration as domain_next_available_iteration,
    _planning_menu_apply_key as domain_planning_menu_apply_key,
    _planning_done_root as domain_planning_done_root,
    _planning_root as domain_planning_root,
    _plan_selection_memory_path as domain_plan_selection_memory_path,
    _preferred_tree_root_for_feature as domain_preferred_tree_root_for_feature,
    _project_sort_key_for_feature as domain_project_sort_key_for_feature,
    _read_planning_menu_escape_sequence as domain_read_planning_menu_escape_sequence,
    _read_planning_menu_key as domain_read_planning_menu_key,
    _render_planning_selection_menu as domain_render_planning_selection_menu,
    _resolve_planning_selection_target as domain_resolve_planning_selection_target,
    _setup_worktree_placeholder_fallback_enabled as domain_setup_worktree_placeholder_fallback_enabled,
    _terminal_size as domain_terminal_size,
    _to_terminal_lines as domain_to_terminal_lines,
    _trees_root_for_worktree as domain_trees_root_for_worktree,
    _truncate_text as domain_truncate_text,
    _worktree_add_failure as domain_worktree_add_failure,
    _setup_worktree_requested as domain_setup_worktree_requested,
)

shutil = _shutil
sys = _sys
PsutilProbeBackend = _PsutilProbeBackend


def _render_help_text(route: Route | None) -> str:
    return runtime_render_help_text(route)


@dataclass(slots=True)
class ProjectContext:
    name: str
    root: Path
    ports: dict[str, PortPlan]


EXPLICIT_MODE_TOKENS = {token.lower() for token in MODE_TREE_TOKENS.union(MODE_MAIN_TOKENS).union(MODE_FALSE_TOKENS)}


class PythonEngineRuntime(RuntimeServiceFacadeMixin):
    PARTIAL_COMMANDS: tuple[str, ...] = ()

    _RUNTIME_CONTEXT_ATTR_MAP: dict[str, str] = {
        "process_runner": "process_runtime",
        "port_planner": "port_allocator",
        "state_repository": "state_repository",
        "terminal_ui": "terminal_ui",
    }

    _coerce_setup_entries = domain_coerce_setup_entries
    _create_single_worktree = domain_create_single_worktree
    _preferred_tree_root_for_feature = domain_preferred_tree_root_for_feature
    _trees_root_for_worktree = domain_trees_root_for_worktree
    _render_planning_selection_menu = domain_render_planning_selection_menu
    _terminal_size = domain_terminal_size
    _truncate_text = staticmethod(domain_truncate_text)
    _to_terminal_lines = staticmethod(domain_to_terminal_lines)
    _read_planning_menu_key = domain_read_planning_menu_key
    _read_planning_menu_escape_sequence = staticmethod(domain_read_planning_menu_escape_sequence)
    _decode_planning_menu_escape = staticmethod(domain_decode_planning_menu_escape)
    _planning_menu_apply_key = domain_planning_menu_apply_key
    _resolve_planning_selection_target = domain_resolve_planning_selection_target
    _planning_root = domain_planning_root
    _planning_done_root = domain_planning_done_root
    _plan_selection_memory_path = domain_plan_selection_memory_path
    _create_feature_worktrees = domain_create_feature_worktrees
    _worktree_add_failure = domain_worktree_add_failure
    _setup_worktree_placeholder_fallback_enabled = domain_setup_worktree_placeholder_fallback_enabled
    _delete_feature_worktrees = domain_delete_feature_worktrees
    _cleanup_empty_feature_root = domain_cleanup_empty_feature_root
    _move_plan_to_done = domain_move_plan_to_done
    _feature_project_candidates = domain_feature_project_candidates
    _project_sort_key_for_feature = staticmethod(domain_project_sort_key_for_feature)
    _next_available_iteration = staticmethod(domain_next_available_iteration)
    _setup_worktree_requested = staticmethod(domain_setup_worktree_requested)

    _start_requirement_component = domain_start_requirement_component
    _wait_for_requirement_listener = domain_wait_for_requirement_listener
    _requirement_listener_timeout_seconds = domain_requirement_listener_timeout_seconds
    _start_requirement_with_native_adapter = domain_start_requirement_with_native_adapter

    _prepare_backend_runtime = domain_prepare_backend_runtime
    _prepare_frontend_runtime = domain_prepare_frontend_runtime
    _service_env_from_file = domain_service_env_from_file
    _resolve_backend_env_file = domain_resolve_backend_env_file
    _resolve_frontend_env_file = domain_resolve_frontend_env_file
    _override_env_path = staticmethod(domain_override_env_path)
    _skip_local_db_env = domain_skip_local_db_env
    _run_backend_bootstrap_command = domain_run_backend_bootstrap_command
    _run_frontend_bootstrap_command = domain_run_frontend_bootstrap_command
    _run_backend_migration_step = domain_run_backend_migration_step
    _backend_migration_retry_env_for_async_driver_mismatch = (
        domain_backend_migration_retry_env_for_async_driver_mismatch
    )
    _backend_async_driver_mismatch_error = staticmethod(domain_backend_async_driver_mismatch_error)
    _rewrite_database_url_to_asyncpg = staticmethod(domain_rewrite_database_url_to_asyncpg)
    _read_env_file_safe = staticmethod(domain_read_env_file_safe)
    _sync_backend_env_file = domain_sync_backend_env_file
    _env_assignment_key = staticmethod(domain_env_assignment_key)
    _backend_bootstrap_strict = domain_backend_bootstrap_strict
    _backend_has_migrations = staticmethod(domain_backend_has_migrations)

    _print_dashboard_snapshot = domain_print_dashboard_snapshot
    _print_dashboard_service_row = domain_print_dashboard_service_row
    _print_dashboard_n8n_row = domain_print_dashboard_n8n_row
    _print_dashboard_tests_row = domain_print_dashboard_tests_row
    _dashboard_status_badge = staticmethod(domain_dashboard_status_badge)
    _dashboard_palette = domain_dashboard_palette

    def __setattr__(self, name: str, value: object) -> None:
        object.__setattr__(self, name, value)
        context_attr = self._RUNTIME_CONTEXT_ATTR_MAP.get(name)
        if context_attr is None:
            return
        runtime_context = self.__dict__.get("runtime_context")
        if runtime_context is not None:
            object.__setattr__(runtime_context, context_attr, value)

    def __init__(self, config: EngineConfig, *, env: dict[str, str] | None = None) -> None:
        initialize_runtime_construction(self, config, env=env)

    def _apply_setup_worktree_selection(
        self, route: Route, project_contexts: list[ProjectContext]
    ) -> list[ProjectContext]:
        return self.planning_worktree_orchestrator.apply_setup_worktree_selection(route, project_contexts)

    def _select_plan_projects(self, route: Route, project_contexts: list[ProjectContext]) -> list[ProjectContext]:
        return self.planning_worktree_orchestrator.select_plan_projects(route, project_contexts)

    def _prompt_planning_selection(
        self,
        planning_files: list[str],
        raw_projects: list[tuple[str, Path]],
    ) -> dict[str, int]:
        return self.planning_worktree_orchestrator.prompt_planning_selection(planning_files, raw_projects)

    def _initial_plan_selected_counts(
        self,
        *,
        planning_files: list[str],
        existing_counts: dict[str, int],
    ) -> dict[str, int]:
        return self.planning_worktree_orchestrator.initial_plan_selected_counts(
            planning_files=planning_files,
            existing_counts=existing_counts,
        )

    def _run_planning_selection_menu(
        self,
        *,
        planning_files: list[str],
        selected_counts: dict[str, int],
        existing_counts: dict[str, int],
    ) -> dict[str, int] | None:
        return self.planning_worktree_orchestrator.run_planning_selection_menu(
            planning_files=planning_files,
            selected_counts=selected_counts,
            existing_counts=existing_counts,
        )

    def _load_plan_selection_memory(self) -> dict[str, int]:
        return self.planning_worktree_orchestrator.load_plan_selection_memory()

    def _save_plan_selection_memory(self, selected_counts: dict[str, int]) -> None:
        self.planning_worktree_orchestrator.save_plan_selection_memory(selected_counts)

    def _planning_keep_plan_enabled(self, route: Route) -> bool:
        return self.planning_worktree_orchestrator.planning_keep_plan_enabled(route)

    def _sync_plan_worktrees_from_plan_counts(
        self,
        *,
        plan_counts: dict[str, int],
        raw_projects: list[tuple[str, Path]],
        keep_plan: bool,
    ) -> tuple[list[tuple[str, Path]], str | None]:
        return self.planning_worktree_orchestrator.sync_plan_worktrees_from_plan_counts(
            plan_counts=plan_counts,
            raw_projects=raw_projects,
            keep_plan=keep_plan,
        )

    def _ensure_legacy_lock_view(self) -> None:
        runtime_ensure_legacy_lock_view(self)

    def add_emit_listener(self, listener: Callable[[str, dict[str, object]], None]) -> Callable[[], None]:
        return runtime_add_emit_listener(self, listener)

    def dispatch(self, route: Route) -> int:
        return runtime_dispatch(self, route)

    def _start(self, route: Route) -> int:
        return self.startup_orchestrator.execute(route)

    def _effective_start_mode(self, route: Route) -> str:
        return runtime_effective_start_mode(self, route)

    def _state_has_resumable_services(self, state: RunState) -> bool:
        return runtime_state_has_resumable_services(self, state)

    def _start_project_context(
        self,
        *,
        context: ProjectContext,
        mode: str,
        route: Route,
        run_id: str,
    ) -> ProjectStartupResult:
        return self.startup_orchestrator.start_project_context(
            context=context,
            mode=mode,
            route=route,
            run_id=run_id,
        )

    def _tree_parallel_startup_config(self, *, mode: str, route: Route, project_count: int) -> tuple[bool, int]:
        return runtime_tree_parallel_startup_config(self, mode=mode, route=route, project_count=project_count)

    def _state_compat_mode(self) -> str:
        return runtime_state_compat_mode(self)

    def _release_port_session(self) -> None:
        runtime_release_port_session(self)

    def _contexts_from_raw_projects(self, raw_projects: list[tuple[str, Path]]) -> list[ProjectContext]:
        return runtime_contexts_from_raw_projects(self, raw_projects, context_factory=ProjectContext)  # type: ignore[return-value]

    @staticmethod
    def _duplicate_project_context_error(contexts: list[ProjectContext]) -> str | None:
        return runtime_duplicate_project_context_error(contexts)

    def _resume(self, route: Route) -> int:
        return self.resume_orchestrator.execute(route)

    def _sanitize_legacy_resume_state(self, state: RunState) -> None:
        runtime_sanitize_legacy_resume_state(self, state)

    def _resume_restore_missing(
        self,
        state: RunState,
        missing_services: list[str],
        *,
        route: Route | None = None,
    ) -> list[str]:
        return self.resume_orchestrator.restore_missing(state, missing_services, route=route)

    def _resume_context_for_project(self, state: RunState, project: str) -> ProjectContext | None:
        context = self.resume_orchestrator.context_for_project(state, project)
        if context is None:
            return None
        return context  # type: ignore[return-value]

    def _resume_project_root(self, state: RunState, project: str) -> Path | None:
        return self.resume_orchestrator.project_root(state, project)

    def _apply_resume_ports_to_context(self, context: ProjectContext, state: RunState) -> None:
        self.resume_orchestrator.apply_ports_to_context(context, state)

    def _set_plan_port_from_component(self, plan: PortPlan, component: Mapping[str, object]) -> None:
        runtime_set_plan_port_from_component(plan, component)

    @staticmethod
    def _set_plan_port(plan: PortPlan, port: int) -> None:
        runtime_set_plan_port(plan, port)

    def _discover_projects(self, *, mode: str) -> list[ProjectContext]:
        return runtime_discover_projects(self, mode=mode, context_factory=ProjectContext)  # type: ignore[return-value]

    def _reserve_project_ports(self, context: ProjectContext, route: Route | None = None) -> None:
        runtime_reserve_project_ports(self, context, route=route)

    def _start_requirements_for_project(
        self,
        context: ProjectContext,
        *,
        mode: str,
        route: Route | None = None,
    ) -> RequirementsResult:
        return self.startup_orchestrator.start_requirements_for_project(
            context,
            mode=mode,
            route=route,
        )

    def _start_project_services(
        self,
        context: ProjectContext,
        *,
        requirements: RequirementsResult,
        run_id: str,
        route: Route | None = None,
    ) -> dict[str, object]:
        return self.startup_orchestrator.start_project_services(
            context,
            requirements=requirements,
            run_id=run_id,
            route=route,
        )

    def _write_artifacts(self, state: RunState, contexts: list[ProjectContext], *, errors: list[str]) -> None:
        runtime_write_artifacts(self, state, contexts, errors=errors)

    def _write_runtime_readiness_report(
        self,
        *,
        run_dir: Path | None = None,
        readiness_result: object | None = None,
    ) -> None:
        runtime_write_runtime_readiness_report(self, run_dir=run_dir, readiness_result=readiness_result)

    def _try_load_existing_state(self, *, mode: str | None = None, strict_mode_match: bool = False) -> RunState | None:
        return runtime_try_load_existing_state(self, mode=mode, strict_mode_match=strict_mode_match)

    def _state_matches_scope(self, state: RunState) -> bool:
        return runtime_state_matches_scope(self, state)

    def _print_summary(self, state: RunState, contexts: list[ProjectContext]) -> None:
        runtime_print_summary(self, state, contexts)

    def _print_help(self, route: Route | None = None) -> None:
        runtime_print_help(route)

    def _config(self, route: Route) -> int:
        return runtime_run_config(self, route)

    def _migrate_hooks(self, route: Route) -> int:
        return runtime_migrate_hooks(self, route)

    def _doctor(self) -> int:
        return runtime_doctor(self)

    def _debug_pack(self, route: Route) -> int:
        return runtime_debug_pack(self, route)

    def _latest_debug_scope_session(self) -> tuple[str, Path, str] | None:
        return runtime_latest_debug_scope_session(self)

    @staticmethod
    def _latest_scope_session_id(scope_dir: Path) -> str | None:
        return runtime_latest_scope_session_id(scope_dir)

    @staticmethod
    def _scope_latest_run_id(scope_dir: Path) -> str | None:
        return runtime_scope_latest_run_id(scope_dir)

    def _debug_doctor_snapshot_text(self) -> str:
        return runtime_debug_doctor_snapshot_text(self)

    def _debug_last(self, route: Route) -> int:
        return runtime_debug_last(self, route)

    def _debug_report(self, route: Route) -> int:
        return runtime_debug_report(self, route)

    def _doctor_readiness_gates(self) -> dict[str, bool]:
        return runtime_doctor_readiness_gates(self)

    def _evaluate_shipability(
        self,
        *,
        enforce_runtime_readiness_contract: bool = True,
    ) -> object:
        return runtime_evaluate_runtime_shipability(
            self,
            enforce_runtime_readiness_contract=enforce_runtime_readiness_contract,
        )

    def _doctor_should_check_tests(self) -> bool:
        return runtime_doctor_should_check_tests(self)

    def _enforce_runtime_readiness_contract(self, *, scope: str, strict_required: bool | None = None) -> bool:
        return runtime_enforce_runtime_readiness_contract(self, scope=scope, strict_required=strict_required)

    def _parity_manifest_is_complete(self) -> bool:
        return runtime_parity_manifest_is_complete(self)

    def _parity_manifest_info(self) -> dict[str, str]:
        return runtime_parity_manifest_info(self)

    def _lock_health_summary(self) -> str:
        return runtime_lock_health_summary(self)

    def _pointer_status_summary(self) -> str:
        return runtime_pointer_status_summary(self)

    def _dashboard(self, route: Route) -> int:
        return bridge_dashboard(self, route)

    def _run_interactive_dashboard_loop(self, state: RunState) -> int:
        return bridge_run_interactive_dashboard_loop(self, state)

    def _run_interactive_command(self, raw: str, state: RunState) -> tuple[bool, RunState]:
        return bridge_run_interactive_command(self, raw, state)

    @staticmethod
    def _sanitize_interactive_input(raw: str) -> str:
        return bridge_sanitize_interactive_input(raw)

    @staticmethod
    def _recover_single_letter_command_from_escape_fragment(raw: str) -> str:
        return bridge_recover_single_letter_command_from_escape_fragment(raw)

    @staticmethod
    def _parse_interactive_command(raw: str) -> list[str] | None:
        return bridge_parse_interactive_command(raw)

    @staticmethod
    def _flush_pending_interactive_input() -> None:
        bridge_flush_pending_interactive_input()

    def _read_interactive_command_line(self, prompt: str) -> str:
        return bridge_read_interactive_command_line(self, prompt)

    def _select_project_targets(
        self,
        *,
        prompt: str,
        projects: list[object],
        allow_all: bool,
        allow_untested: bool,
        multi: bool,
        initial_project_names: list[str] | None = None,
        exclusive_project_name: str | None = None,
    ):
        return bridge_select_project_targets(
            self,
            prompt=prompt,
            projects=projects,
            allow_all=allow_all,
            allow_untested=allow_untested,
            multi=multi,
            initial_project_names=initial_project_names,
            exclusive_project_name=exclusive_project_name,
        )

    def _select_grouped_targets(
        self,
        *,
        prompt: str,
        projects: list[object],
        services: list[str],
        allow_all: bool,
        multi: bool,
    ):
        return bridge_select_grouped_targets(
            self,
            prompt=prompt,
            projects=projects,
            services=services,
            allow_all=allow_all,
            multi=multi,
        )

    @staticmethod
    def _can_interactive_tty() -> bool:
        return bridge_can_interactive_tty()

    def _build_process_probe_backend(self) -> ProbeBackend:
        return runtime_build_process_probe_backend(self)

    def _probe_psutil_enabled(self) -> bool:
        return runtime_probe_psutil_enabled(self)

    @staticmethod
    def _tokens_set_mode(tokens: Iterable[str]) -> bool:
        return runtime_tokens_set_mode(tokens)

    def _should_enter_post_start_interactive(self, route: Route) -> bool:
        return runtime_should_enter_post_start_interactive(self, route)

    def _should_enter_dashboard_interactive(self, route: Route) -> bool:
        return runtime_should_enter_dashboard_interactive(self, route)

    def _should_enter_resume_interactive(self, route: Route) -> bool:
        return runtime_should_enter_resume_interactive(self, route)

    def _batch_mode_requested(self, route: Route) -> bool:
        return runtime_batch_mode_requested(self, route)

    @staticmethod
    def _is_truthy(value: str | None) -> bool:
        return runtime_is_truthy(value)

    @staticmethod
    def _route_has_explicit_mode(route: Route) -> bool:
        return runtime_route_has_explicit_mode(route, explicit_mode_tokens=EXPLICIT_MODE_TOKENS)

    def _state_lookup_strict_mode_match(self, route: Route) -> bool:
        return runtime_state_lookup_strict_mode_match(self, route)

    def _state_action(self, route: Route) -> int:
        return runtime_state_action(self, route)

    def _recent_failure_messages(self, *, max_items: int = 5) -> list[str]:
        return runtime_recent_failure_messages(self, max_items=max_items)

    def _print_logs(
        self,
        state: RunState,
        *,
        tail: int,
        follow: bool = False,
        duration_seconds: float | None = None,
        no_color: bool = False,
    ) -> None:
        from envctl_engine.runtime.engine_runtime_misc_support import print_logs as runtime_print_logs

        runtime_print_logs(
            self,
            state,
            tail=tail,
            follow=follow,
            duration_seconds=duration_seconds,
            no_color=no_color,
        )

    def _reconcile_state_truth(self, state: RunState) -> list[str]:
        return runtime_reconcile_state_truth(self, state)

    @staticmethod
    def _state_fingerprint(state: RunState) -> str:
        return runtime_state_fingerprint(state)

    def _reconcile_project_requirement_truth(
        self,
        project: str,
        requirements: RequirementsResult,
        *,
        project_root: Path | None = None,
    ) -> list[dict[str, object]]:
        return runtime_reconcile_project_requirement_truth(
            self,
            project,
            requirements,
            project_root=project_root,
        )

    def _requirement_truth_issues(self, state: RunState) -> list[dict[str, object]]:
        return runtime_requirement_truth_issues(self, state)

    def _service_truth_status(self, service: object) -> str:
        return runtime_service_truth_status(self, service)

    def _rebind_stale_service_pid(self, service: object, *, previous_pid: int | None) -> bool:
        return runtime_rebind_stale_service_pid(self, service, previous_pid=previous_pid)

    def _listener_pids_for_port(self, port: int) -> list[int]:
        return runtime_listener_pids_for_port(self, port)

    def _service_truth_discovery(self, service: object, port: int) -> int | None:
        return runtime_service_truth_discovery(self, service, port)

    def _refresh_service_listener_pids(self, service: object, *, port: int) -> None:
        runtime_refresh_service_listener_pids(self, service, port=port)

    @staticmethod
    def _clear_service_listener_pids(service: object) -> None:
        runtime_clear_service_listener_pids(service)

    def _assert_project_services_post_start_truth(
        self,
        *,
        context: ProjectContext,
        services: Mapping[str, object],
    ) -> None:
        runtime_assert_project_services_post_start_truth(self, context=context, services=services)

    def _run_action_command(self, route: Route) -> int:
        return runtime_run_action_command(self, route)

    def _resolve_action_targets(self, route: Route, *, trees_only: bool) -> tuple[list[ProjectContext], str | None]:
        targets, error = runtime_resolve_action_targets(self, route, trees_only=trees_only)
        return targets, error  # type: ignore[return-value]

    @staticmethod
    def _selectors_from_passthrough(passthrough_args: Iterable[str]) -> set[str]:
        return runtime_selectors_from_passthrough(passthrough_args)

    @staticmethod
    def _project_name_from_service(service_name: str) -> str:
        return runtime_project_name_from_service(service_name)

    def _run_test_action(self, route: Route, targets: list[ProjectContext]) -> int:
        return runtime_run_test_action(self, route, targets)

    def _run_pr_action(self, route: Route, targets: list[ProjectContext]) -> int:
        return runtime_run_pr_action(self, route, targets)

    def _run_commit_action(self, route: Route, targets: list[ProjectContext]) -> int:
        return runtime_run_commit_action(self, route, targets)

    def _run_analyze_action(self, route: Route, targets: list[ProjectContext]) -> int:
        return runtime_run_analyze_action(self, route, targets)

    def _run_migrate_action(self, route: Route, targets: list[ProjectContext]) -> int:
        return runtime_run_migrate_action(self, route, targets)

    def _run_project_action(
        self,
        route: Route,
        targets: list[ProjectContext],
        *,
        command_name: str,
        env_key: str,
        default_command: list[str] | None,
        default_cwd: Path,
        default_append_project_path: bool,
        extra_env: Mapping[str, str],
    ) -> int:
        return runtime_run_project_action(
            self,
            route,
            targets,
            command_name=command_name,
            env_key=env_key,
            default_command=default_command,
            default_cwd=default_cwd,
            default_append_project_path=default_append_project_path,
            extra_env=extra_env,
        )

    def _run_delete_worktree_action(self, route: Route) -> int:
        return runtime_run_delete_worktree_action(self, route)

    def _action_replacements(
        self,
        targets: list[ProjectContext],
        *,
        target: ProjectContext | None,
    ) -> dict[str, str]:
        return runtime_action_replacements(self, targets, target=target)

    def _action_env(
        self,
        command_name: str,
        targets: list[ProjectContext],
        *,
        target: ProjectContext | None,
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        return runtime_action_env(
            self,
            command_name,
            targets,
            target=target,
            extra=extra,
        )

    @staticmethod
    def _action_extra_env(route: Route) -> dict[str, str]:
        return runtime_action_extra_env(route)

    def _unsupported_command(self, command: str) -> int:
        return runtime_unsupported_command(command)

    def _clear_runtime_state(self, *, command: str, aggressive: bool = False, route: Route | None = None) -> None:
        self.lifecycle_cleanup_orchestrator.clear_runtime_state(
            command=command,
            aggressive=aggressive,
            route=route,
        )

    def _blast_all_print_and_kill_listener_maps(
        self,
        *,
        kill_pid_ports: dict[int, set[int]],
        docker_pid_ports: dict[int, set[int]],
    ) -> None:
        self.lifecycle_cleanup_orchestrator.blast_all_print_and_kill_listener_maps(
            kill_pid_ports=kill_pid_ports,
            docker_pid_ports=docker_pid_ports,
        )

    def _blast_all_port_range(self) -> list[int]:
        return self.lifecycle_cleanup_orchestrator.blast_all_port_range()

    def _blast_all_kill_orchestrator_processes(self) -> None:
        self.lifecycle_cleanup_orchestrator.blast_all_kill_orchestrator_processes()

    def _blast_all_docker_cleanup(self, *, route: Route | None) -> int:
        return self.lifecycle_cleanup_orchestrator.blast_all_docker_cleanup(route=route)

    def _terminate_started_services(self, services: dict[str, object]) -> None:
        runtime_terminate_started_services(self, services)

    def _terminate_services_from_state(
        self,
        state: RunState,
        *,
        selected_services: set[str] | None,
        aggressive: bool,
        verify_ownership: bool,
    ) -> None:
        runtime_terminate_services_from_state(
            self,
            state,
            selected_services=selected_services,
            aggressive=aggressive,
            verify_ownership=verify_ownership,
        )

    def _terminate_service_record(self, service: object, *, aggressive: bool, verify_ownership: bool) -> bool:
        return runtime_terminate_service_record(
            self,
            service,
            aggressive=aggressive,
            verify_ownership=verify_ownership,
        )

    @staticmethod
    def _service_port(service: object) -> int | None:
        return runtime_service_port(service)

    def _release_requirement_ports(self, requirements: RequirementsResult) -> None:
        runtime_release_requirement_ports(self, requirements)

    def _blast_worktree_before_delete(
        self,
        *,
        project_name: str,
        project_root: Path,
        source_command: str = "delete-worktree",
    ) -> list[str]:
        return runtime_blast_worktree_before_delete(
            self,
            project_name=project_name,
            project_root=project_root,
            source_command=source_command,
        )

    def _emit(self, event_name: str, **payload: object) -> None:
        runtime_emit(self, event_name, **payload)

    def _persist_events_snapshot(self) -> None:
        runtime_persist_events_snapshot(self)

    def _configure_debug_recorder(self, route: Route) -> None:
        runtime_configure_debug_recorder(self, route)

    def _current_session_id(self) -> str | None:
        return runtime_current_session_id(self)

    def _run_state_path(self) -> Path:
        return runtime_run_state_path(self)

    def _run_dir_path(self, run_id: str | None) -> Path:
        return runtime_run_dir_path(self, run_id)

    def _runtime_map_path(self) -> Path:
        return runtime_runtime_map_path(self)

    def _error_report_path(self) -> Path:
        return runtime_error_report_path(self)

    def _lock_inventory(self) -> list[str]:
        return runtime_lock_inventory(self)

    def _new_run_id(self) -> str:
        return runtime_new_run_id(self)

    def _bind_debug_run_id(self, run_id: str | None) -> None:
        runtime_bind_debug_run_id(self, run_id)

    def _reset_project_startup_warnings(self) -> None:
        runtime_reset_project_startup_warnings(self)

    def _record_project_startup_warning(self, project: str, message: str) -> None:
        runtime_record_project_startup_warning(self, project, message)

    def _consume_project_startup_warnings(self, project: str) -> list[str]:
        return runtime_consume_project_startup_warnings(self, project)

    def _conflict_count(self, suffix: str) -> int:
        return runtime_conflict_count(self, suffix)

    def _requirement_bind_max_retries(self) -> int:
        return runtime_requirement_bind_max_retries(self)

    def _listener_truth_enforced(self) -> bool:
        return runtime_listener_truth_enforced(self)

    @staticmethod
    def _probe_listener_support() -> bool:
        return runtime_probe_listener_support()

    @staticmethod
    def _normalize_log_line(line: str, *, no_color: bool) -> str:
        return runtime_normalize_log_line(line, no_color=no_color)

    @staticmethod
    def _state_has_synthetic_services(state: RunState) -> bool:
        return runtime_state_has_synthetic_services(state)

    def _on_port_event(self, event_name: str, payload: dict[str, object]) -> None:
        runtime_on_port_event(self, event_name, payload)


def dispatch_route(route: Route, config: EngineConfig, *, env: dict[str, str] | None = None) -> int:
    runtime = PythonEngineRuntime(config, env=env)
    return runtime.dispatch(route)


def load_state_artifact(path: Path) -> dict[str, object]:
    return runtime_load_state_artifact(path)


def run_state_to_json(state: RunState) -> str:
    return runtime_run_state_to_json(state)
