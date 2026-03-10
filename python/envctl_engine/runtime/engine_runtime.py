from __future__ import annotations

import uuid
import threading
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

from envctl_engine.actions.actions_worktree import delete_worktree_path
from envctl_engine.actions.action_command_orchestrator import ActionCommandOrchestrator
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator
from envctl_engine.debug.doctor_orchestrator import DoctorOrchestrator
from envctl_engine.runtime.engine_runtime_diagnostics import (
    lock_health_summary as runtime_lock_health_summary,
    parity_manifest_info as runtime_parity_manifest_info,
    parity_manifest_is_complete as runtime_parity_manifest_is_complete,
    pointer_status_summary as runtime_pointer_status_summary,
    read_parity_manifest as runtime_read_parity_manifest,
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
    print_logs as runtime_print_logs,
    probe_psutil_enabled as runtime_probe_psutil_enabled,
    recent_failure_messages as runtime_recent_failure_messages,
    release_port_session as runtime_release_port_session,
    requirement_bind_max_retries as runtime_requirement_bind_max_retries,
    requirement_enabled as runtime_requirement_enabled,
    route_has_explicit_mode as runtime_route_has_explicit_mode,
    should_enter_dashboard_interactive as runtime_should_enter_dashboard_interactive,
    should_enter_post_start_interactive as runtime_should_enter_post_start_interactive,
    should_enter_resume_interactive as runtime_should_enter_resume_interactive,
    state_compat_mode as runtime_state_compat_mode,
    status_color as runtime_status_color,
    tokens_set_mode as runtime_tokens_set_mode,
)
from envctl_engine.runtime.engine_runtime_event_support import (
    auto_debug_pack as runtime_auto_debug_pack,
    bind_debug_run_id as runtime_bind_debug_run_id,
    configure_debug_recorder as runtime_configure_debug_recorder,
    current_session_id as runtime_current_session_id,
    debug_mode_from_route as runtime_debug_mode_from_route,
    debug_output_root as runtime_debug_output_root,
    debug_recorder_config as runtime_debug_recorder_config,
    debug_should_auto_pack as runtime_debug_should_auto_pack,
    debug_trace_id_mode as runtime_debug_trace_id_mode,
    emit as runtime_emit,
    event_trace_id as runtime_event_trace_id,
    persist_events_snapshot as runtime_persist_events_snapshot,
    sanitize_emit_payload as runtime_sanitize_emit_payload,
)
from envctl_engine.runtime.engine_runtime_runtime_support import (
    conflict_count as runtime_conflict_count,
    error_report_path as runtime_error_report_path,
    lock_inventory as runtime_lock_inventory,
    new_run_id as runtime_new_run_id,
    normalize_log_line as runtime_normalize_log_line,
    ports_manifest_path as runtime_ports_manifest_path,
    probe_listener_support as runtime_probe_listener_support,
    run_dir_path as runtime_run_dir_path,
    run_state_path as runtime_run_state_path,
    runtime_map_path as runtime_runtime_map_path,
)
from envctl_engine.runtime.engine_runtime_lifecycle_support import (
    blast_worktree_before_delete as runtime_blast_worktree_before_delete,
    release_requirement_ports as runtime_release_requirement_ports,
    requirement_key_for_project as runtime_requirement_key_for_project,
    service_port as runtime_service_port,
    terminate_service_record as runtime_terminate_service_record,
    terminate_services_from_state as runtime_terminate_services_from_state,
    terminate_started_services as runtime_terminate_started_services,
)
from envctl_engine.runtime.engine_runtime_startup_support import (
    auto_resume_start_enabled as runtime_auto_resume_start_enabled,
    contexts_from_raw_projects as runtime_contexts_from_raw_projects,
    discover_projects as runtime_discover_projects,
    duplicate_project_context_error as runtime_duplicate_project_context_error,
    effective_start_mode as runtime_effective_start_mode,
    load_auto_resume_state as runtime_load_auto_resume_state,
    reserve_project_ports as runtime_reserve_project_ports,
    sanitize_legacy_resume_state as runtime_sanitize_legacy_resume_state,
    set_plan_port as runtime_set_plan_port,
    set_plan_port_from_component as runtime_set_plan_port_from_component,
    state_has_resumable_services as runtime_state_has_resumable_services,
    tree_parallel_startup_config as runtime_tree_parallel_startup_config,
)
from envctl_engine.runtime.engine_runtime_dashboard_truth import (
    dashboard_reconcile_for_snapshot as runtime_dashboard_reconcile_for_snapshot,
    dashboard_truth_refresh_seconds as runtime_dashboard_truth_refresh_seconds,
)
from envctl_engine.runtime.engine_runtime_artifacts import (
    print_summary as runtime_print_summary,
    write_artifacts as runtime_write_artifacts,
    write_runtime_readiness_report as runtime_write_runtime_readiness_report,
)
from envctl_engine.runtime.engine_runtime_commands import (
    command_env as runtime_command_env,
    command_exists as runtime_command_exists,
    command_override_value as runtime_command_override_value,
    default_python_executable as runtime_default_python_executable,
    requirement_command as runtime_requirement_command,
    requirement_command_resolved as runtime_requirement_command_resolved,
    requirement_command_source as runtime_requirement_command_source,
    service_command_source as runtime_service_command_source,
    service_start_command as runtime_service_start_command,
    service_start_command_resolved as runtime_service_start_command_resolved,
    split_command as runtime_split_command,
)
from envctl_engine.runtime.engine_runtime_env import (
    effective_main_requirement_flags as runtime_effective_main_requirement_flags,
    main_requirements_mode as runtime_main_requirements_mode,
    project_service_env as runtime_project_service_env,
    requirement_enabled_for_mode as runtime_requirement_enabled_for_mode,
    requirements_ready as runtime_requirements_ready,
    service_enabled_for_mode as runtime_service_enabled_for_mode,
    runtime_env_overrides as runtime_env_overrides,
    skipped_requirement as runtime_skipped_requirement,
    validate_mode_toggles as runtime_validate_mode_toggles,
)
from envctl_engine.runtime.engine_runtime_hooks import (
    hook_bridge_enabled as runtime_hook_bridge_enabled,
    invoke_envctl_hook as runtime_invoke_envctl_hook,
    requirements_result_from_hook_payload as runtime_requirements_result_from_hook_payload,
    startup_hook_contract_issue as runtime_startup_hook_contract_issue,
    run_supabase_reinit as runtime_run_supabase_reinit,
    services_from_hook_payload as runtime_services_from_hook_payload,
    supabase_auto_reinit_enabled as runtime_supabase_auto_reinit_enabled,
    supabase_fingerprint_path as runtime_supabase_fingerprint_path,
    supabase_reinit_required_message as runtime_supabase_reinit_required_message,
)
from envctl_engine.runtime.engine_runtime_service_truth import (
    assert_project_services_post_start_truth as runtime_assert_project_services_post_start_truth,
    command_result_error_text as runtime_command_result_error_text,
    detect_service_actual_port as runtime_detect_service_actual_port,
    listener_pids_for_port as runtime_listener_pids_for_port,
    process_tree_probe_supported as runtime_process_tree_probe_supported,
    rebind_stale_service_pid as runtime_rebind_stale_service_pid,
    refresh_service_listener_pids as runtime_refresh_service_listener_pids,
    service_listener_failure_detail as runtime_service_listener_failure_detail,
    service_truth_discovery as runtime_service_truth_discovery,
    service_truth_fallback_enabled as runtime_service_truth_fallback_enabled,
    service_truth_status as runtime_service_truth_status,
    tail_log_error_line as runtime_tail_log_error_line,
    wait_for_service_listener as runtime_wait_for_service_listener,
    clear_service_listener_pids as runtime_clear_service_listener_pids,
)
from envctl_engine.runtime.engine_runtime_service_policy import (
    service_listener_timeout as runtime_service_listener_timeout,
    service_rebound_max_delta as runtime_service_rebound_max_delta,
    service_startup_grace_seconds as runtime_service_startup_grace_seconds,
    service_truth_timeout as runtime_service_truth_timeout,
    service_within_startup_grace as runtime_service_within_startup_grace,
)
from envctl_engine.runtime.engine_runtime_state_support import (
    load_state_artifact as runtime_load_state_artifact,
    on_port_event as runtime_on_port_event,
    run_state_to_json as runtime_run_state_to_json,
    state_has_synthetic_services as runtime_state_has_synthetic_services,
)
from envctl_engine.runtime.engine_runtime_state_lookup import (
    state_matches_scope as runtime_state_matches_scope,
    try_load_existing_state as runtime_try_load_existing_state,
)
from envctl_engine.runtime.engine_runtime_state_truth import (
    reconcile_project_requirement_truth as runtime_reconcile_project_requirement_truth,
    reconcile_requirements_truth as runtime_reconcile_requirements_truth,
    reconcile_state_truth as runtime_reconcile_state_truth,
    requirement_component_port as runtime_requirement_component_port,
    requirement_runtime_status as runtime_requirement_runtime_status,
    requirement_truth_issues as runtime_requirement_truth_issues,
    state_fingerprint as runtime_state_fingerprint,
)
from envctl_engine.runtime.engine_runtime_dispatch import dispatch_command as runtime_dispatch_command
from envctl_engine.runtime.engine_runtime_ui_bridge import (
    current_ui_backend as bridge_current_ui_backend,
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
from envctl_engine.runtime.hook_migration_support import run_hook_migration as runtime_run_hook_migration
from envctl_engine.runtime.command_resolution import CommandResolutionError, resolve_requirement_start_command, resolve_service_start_command
from envctl_engine.runtime.command_router import MODE_FALSE_TOKENS, MODE_MAIN_TOKENS, MODE_TREE_TOKENS, Route, list_supported_commands, parse_route
from envctl_engine.config.command_support import run_config_command
from envctl_engine.config import EngineConfig
from envctl_engine.shared.hooks import HookInvocationResult
from envctl_engine.runtime.lifecycle_cleanup_orchestrator import LifecycleCleanupOrchestrator
from envctl_engine.state.models import PortPlan, RequirementsResult, RunState, ServiceRecord
from envctl_engine.shared.ports import PortPlanner
from envctl_engine.planning import (
    discover_tree_projects,
    filter_projects_for_plan,
    list_planning_files,
    planning_existing_counts,
    planning_feature_name,
    resolve_planning_files,
    select_projects_for_plan_files,
)
from envctl_engine.shared.process_probe import ProcessProbe, ProbeBackend, PsutilProbeBackend, psutil_available
from envctl_engine.shared.parsing import parse_float_or_none
from envctl_engine.shared.process_runner import ProcessRunner
from envctl_engine.requirements.orchestrator import FailureClass, RequirementOutcome, RequirementsOrchestrator
from envctl_engine.requirements.common import build_container_name, container_exists, run_docker, run_result_error
from envctl_engine.requirements.n8n import start_n8n_container
from envctl_engine.requirements.postgres import start_postgres_container
from envctl_engine.requirements.redis import start_redis_container
from envctl_engine.requirements.supabase import (
    evaluate_supabase_reliability_contract,
    read_fingerprint as read_supabase_fingerprint,
    start_supabase_stack,
    write_fingerprint as write_supabase_fingerprint,
)
from envctl_engine.shell.release_gate import evaluate_shipability
from envctl_engine.startup.resume_orchestrator import ResumeOrchestrator
from envctl_engine.runtime.runtime_context import RuntimeContext
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.runtime.service_manager import ServiceManager
from envctl_engine.startup.startup_orchestrator import StartupOrchestrator
from envctl_engine.state.action_orchestrator import StateActionOrchestrator
from envctl_engine.state import dump_state, load_legacy_shell_state, load_state, load_state_from_pointer
from envctl_engine.state.repository import RuntimeStateRepository
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI
from envctl_engine.ui.debug_flight_recorder import DebugFlightRecorder, DebugRecorderConfig
from envctl_engine.ui.backend import build_interactive_backend
from envctl_engine.ui.backend_resolver import resolve_ui_backend
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
    _backend_migration_retry_env_for_async_driver_mismatch as domain_backend_migration_retry_env_for_async_driver_mismatch,
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
    _apply_setup_worktree_selection as domain_apply_setup_worktree_selection,
    _cleanup_empty_feature_root as domain_cleanup_empty_feature_root,
    _coerce_setup_entries as domain_coerce_setup_entries,
    _create_feature_worktrees as domain_create_feature_worktrees,
    _create_single_worktree as domain_create_single_worktree,
    _decode_planning_menu_escape as domain_decode_planning_menu_escape,
    _delete_feature_worktrees as domain_delete_feature_worktrees,
    _feature_project_candidates as domain_feature_project_candidates,
    _initial_plan_selected_counts as domain_initial_plan_selected_counts,
    _load_plan_selection_memory as domain_load_plan_selection_memory,
    _move_plan_to_done as domain_move_plan_to_done,
    _next_available_iteration as domain_next_available_iteration,
    _planning_keep_plan_enabled as domain_planning_keep_plan_enabled,
    _planning_menu_apply_key as domain_planning_menu_apply_key,
    _planning_done_root as domain_planning_done_root,
    _planning_root as domain_planning_root,
    _plan_selection_memory_path as domain_plan_selection_memory_path,
    _preferred_tree_root_for_feature as domain_preferred_tree_root_for_feature,
    _project_sort_key_for_feature as domain_project_sort_key_for_feature,
    _prompt_planning_selection as domain_prompt_planning_selection,
    _read_planning_menu_escape_sequence as domain_read_planning_menu_escape_sequence,
    _read_planning_menu_key as domain_read_planning_menu_key,
    _render_planning_selection_menu as domain_render_planning_selection_menu,
    _resolve_planning_selection_target as domain_resolve_planning_selection_target,
    _run_planning_selection_menu as domain_run_planning_selection_menu,
    _save_plan_selection_memory as domain_save_plan_selection_memory,
    _select_plan_projects as domain_select_plan_projects,
    _setup_worktree_placeholder_fallback_enabled as domain_setup_worktree_placeholder_fallback_enabled,
    _sync_plan_worktrees_from_plan_counts as domain_sync_plan_worktrees_from_plan_counts,
    _terminal_size as domain_terminal_size,
    _to_terminal_lines as domain_to_terminal_lines,
    _trees_root_for_worktree as domain_trees_root_for_worktree,
    _truncate_text as domain_truncate_text,
    _worktree_add_failure as domain_worktree_add_failure,
    _setup_worktree_requested as domain_setup_worktree_requested,
)
from envctl_engine.planning.worktree_orchestrator import PlanningWorktreeOrchestrator


@dataclass(slots=True)
class ProjectContext:
    name: str
    root: Path
    ports: dict[str, PortPlan]


EXPLICIT_MODE_TOKENS = {token.lower() for token in MODE_TREE_TOKENS.union(MODE_MAIN_TOKENS).union(MODE_FALSE_TOKENS)}


class PythonEngineRuntime:
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
    _backend_migration_retry_env_for_async_driver_mismatch = domain_backend_migration_retry_env_for_async_driver_mismatch
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
        self.config = config
        self.env = dict(env or {})
        self.runtime_legacy_root = config.runtime_dir / "python-engine"
        self.runtime_root = config.runtime_scope_dir
        self.runtime_legacy_root.mkdir(parents=True, exist_ok=True)
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self._ensure_legacy_lock_view()
        self.port_planner = PortPlanner(
            backend_base=config.backend_port_base,
            frontend_base=config.frontend_port_base,
            spacing=config.port_spacing,
            db_base=config.db_port_base,
            redis_base=config.redis_port_base,
            n8n_base=config.n8n_port_base,
            lock_dir=str(self.runtime_root / "locks"),
            event_handler=self._on_port_event,
            availability_mode=config.port_availability_mode,
            preferred_port_strategy=self.env.get(
                "ENVCTL_PORT_PREFERRED_STRATEGY",
                config.raw.get("ENVCTL_PORT_PREFERRED_STRATEGY", "project_slot"),
            ),
            scope_key=config.runtime_scope_id,
        )
        self.requirements = RequirementsOrchestrator()
        self.services = ServiceManager()
        self.events: list[dict[str, object]] = []
        self._emit_lock = threading.Lock()
        self._emit_listeners: list[Callable[[str, dict[str, object]], None]] = []
        self._startup_warnings_lock = threading.Lock()
        self._startup_warnings_by_project: dict[str, list[str]] = {}
        self._debug_hash_salt = uuid.uuid4().hex
        self._debug_recorder: DebugFlightRecorder | None = None
        self._active_command_id: str | None = None
        self._last_debug_bundle_path: str | None = None
        self.process_runner = ProcessRunner(emit=self._emit)
        probe_backend_name = "psutil" if (self._probe_psutil_enabled() and psutil_available()) else "shell"
        probe_backend = self._build_process_probe_backend()
        self.process_probe = ProcessProbe(probe_backend)
        self._emit("probe.backend", backend=probe_backend_name)
        self.terminal_ui = RuntimeTerminalUI()
        self._dashboard_truth_cache_run_id: str | None = None
        self._dashboard_truth_cache_expires_at = 0.0
        self._dashboard_truth_cache_missing_services: list[str] = []
        self._listener_probe_supported = self._probe_listener_support()
        self._conflict_remaining: dict[str, int] = {
            "postgres": self._conflict_count("POSTGRES"),
            "redis": self._conflict_count("REDIS"),
            "supabase": self._conflict_count("SUPABASE"),
            "n8n": self._conflict_count("N8N"),
            "backend": self._conflict_count("BACKEND"),
            "frontend": self._conflict_count("FRONTEND"),
        }
        self.state_repository = RuntimeStateRepository(
            runtime_root=self.runtime_root,
            runtime_legacy_root=self.runtime_legacy_root,
            runtime_dir=self.config.runtime_dir,
            runtime_scope_id=self.config.runtime_scope_id,
            compat_mode=self._state_compat_mode(),
        )
        self.runtime_context = RuntimeContext(
            config=self.config,
            env=self.env,
            process_runtime=self.process_runner,
            port_allocator=self.port_planner,
            state_repository=self.state_repository,
            terminal_ui=self.terminal_ui,
            emit=self._emit,
        )
        self.planning_worktree_orchestrator = PlanningWorktreeOrchestrator(self)
        self.startup_orchestrator = StartupOrchestrator(self)
        self.resume_orchestrator = ResumeOrchestrator(self)
        self.doctor_orchestrator = DoctorOrchestrator(self)
        self.lifecycle_cleanup_orchestrator = LifecycleCleanupOrchestrator(self)
        self.dashboard_orchestrator = DashboardOrchestrator(self)
        self.state_action_orchestrator = StateActionOrchestrator(self)
        self.action_command_orchestrator = ActionCommandOrchestrator(self)
        self.ui_backend_resolution = resolve_ui_backend(self.env)
        self.ui_backend = build_interactive_backend(self.ui_backend_resolution)
        self._emit(
            "ui.backend.selected",
            backend=self.ui_backend_resolution.backend,
            requested_mode=self.ui_backend_resolution.requested_mode,
            interactive=self.ui_backend_resolution.interactive,
            reason=self.ui_backend_resolution.reason,
        )
        if not self.ui_backend_resolution.interactive:
            self._emit(
                "ui.fallback.non_interactive",
                reason=self.ui_backend_resolution.reason,
                backend=self.ui_backend_resolution.backend,
            )

    def _apply_setup_worktree_selection(self, route: Route, project_contexts: list[ProjectContext]) -> list[ProjectContext]:
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
        scoped_locks = self.runtime_root / "locks"
        scoped_locks.mkdir(parents=True, exist_ok=True)
        legacy_locks = self.runtime_legacy_root / "locks"
        if legacy_locks.exists():
            return
        try:
            legacy_locks.symlink_to(scoped_locks, target_is_directory=True)
        except OSError:
            legacy_locks.mkdir(parents=True, exist_ok=True)

    def add_emit_listener(self, listener: Callable[[str, dict[str, object]], None]) -> Callable[[], None]:
        self._emit_listeners.append(listener)

        def remove() -> None:
            try:
                self._emit_listeners.remove(listener)
            except ValueError:
                return

        return remove

    def dispatch(self, route: Route) -> int:
        self.process_probe = ProcessProbe(self._build_process_probe_backend())
        effective_mode = route.mode
        if route.command in {"start", "plan", "restart"}:
            effective_mode = self._effective_start_mode(route)

        self._configure_debug_recorder(route)

        self._emit(
            "engine.mode.selected",
            mode=route.mode,
            effective_mode=effective_mode,
            command=route.command,
        )
        self._emit(
            "command.route.selected",
            mode=route.mode,
            effective_mode=effective_mode,
            command=route.command,
        )
        return runtime_dispatch_command(self, route)

    def _start(self, route: Route) -> int:
        return self.startup_orchestrator.execute(route)


    def _effective_start_mode(self, route: Route) -> str:
        return runtime_effective_start_mode(self, route)

    @staticmethod
    def _auto_resume_start_enabled(route: Route) -> bool:
        return runtime_auto_resume_start_enabled(route)

    def _load_auto_resume_state(self, runtime_mode: str) -> RunState | None:
        return runtime_load_auto_resume_state(self, runtime_mode)

    def _state_has_resumable_services(self, state: RunState) -> bool:
        return runtime_state_has_resumable_services(self, state)

    def _start_project_context(
        self,
        *,
        context: ProjectContext,
        mode: str,
        route: Route,
        run_id: str,
    ) -> tuple[RequirementsResult, dict[str, object], list[str]]:
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

    def _resume_restore_enabled(self, route: Route) -> bool:
        return self.resume_orchestrator.restore_enabled(route)

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

    def _reserve_project_ports(self, context: ProjectContext) -> None:
        runtime_reserve_project_ports(self, context)

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
    def _print_help(self) -> None:
        print("envctl Python runtime")
        print("Commands: " + ", ".join(list_supported_commands()))
        print("Mode flags: --main, --tree, --trees, trees=true, main=true")
        print("Non-interactive: --headless (preferred), --batch (compatibility alias)")

    def _config(self, route: Route) -> int:
        return run_config_command(self, route)

    def _migrate_hooks(self, route: Route) -> int:
        return runtime_run_hook_migration(self, route)

    def _doctor(self) -> int:
        return self.doctor_orchestrator.execute()

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
        return self.doctor_orchestrator.readiness_gates()

    def _evaluate_shipability(
        self,
        *,
        enforce_runtime_readiness_contract: bool = True,
    ) -> object:
        return evaluate_shipability(
            repo_root=self.config.base_dir,
            check_tests=self._doctor_should_check_tests(),
            enforce_runtime_readiness_contract=enforce_runtime_readiness_contract,
        )

    def _doctor_should_check_tests(self) -> bool:
        return self.doctor_orchestrator.doctor_should_check_tests()

    def _enforce_runtime_readiness_contract(self, *, scope: str, strict_required: bool | None = None) -> bool:
        return self.doctor_orchestrator.enforce_runtime_readiness_contract(
            scope=scope,
            strict_required=strict_required,
        )

    def _parity_manifest_is_complete(self) -> bool:
        return runtime_parity_manifest_is_complete(self)

    def _parity_manifest_info(self) -> dict[str, str]:
        return runtime_parity_manifest_info(self)

    def _read_parity_manifest(self) -> dict[str, object] | None:
        return runtime_read_parity_manifest(self)

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
    ):
        return bridge_select_project_targets(
            self,
            prompt=prompt,
            projects=projects,
            allow_all=allow_all,
            allow_untested=allow_untested,
            multi=multi,
            initial_project_names=initial_project_names,
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

    def _current_ui_backend(self):
        return bridge_current_ui_backend(self)

    @staticmethod
    def _restore_terminal_after_input(*, fd: int, original_state: list[int] | None) -> None:
        """Restore terminal state after raw input handling."""
        from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI
        RuntimeTerminalUI.restore_terminal_after_input(fd=fd, original_state=original_state)

    @staticmethod
    def _can_interactive_tty() -> bool:
        """Check if interactive TTY is available."""
        from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI
        return RuntimeTerminalUI._can_interactive_tty()

    def _build_process_probe_backend(self) -> ProbeBackend:
        return runtime_build_process_probe_backend(self)

    def _probe_psutil_enabled(self) -> bool:
        return runtime_probe_psutil_enabled(self)

    @staticmethod
    def _tokens_set_mode(tokens: Iterable[str]) -> bool:
        return runtime_tokens_set_mode(tokens)

    @staticmethod
    def _status_color(status: str, *, green: str, yellow: str, red: str) -> str:
        return runtime_status_color(status, green=green, yellow=yellow, red=red)

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
        return self._route_has_explicit_mode(route)


    def _state_action(self, route: Route) -> int:
        return self.state_action_orchestrator.execute(route)

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

    def _reconcile_requirements_truth(self, state: RunState) -> list[dict[str, object]]:
        return runtime_reconcile_requirements_truth(self, state)

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

    def _requirement_runtime_status(
        self,
        *,
        component_name: str,
        component_data: dict[str, object],
        requirements: RequirementsResult,
    ) -> str:
        return runtime_requirement_runtime_status(
            self,
            component_name=component_name,
            component_data=component_data,
            requirements=requirements,
        )

    @staticmethod
    def _requirement_component_port(component_data: dict[str, object]) -> object:
        return runtime_requirement_component_port(component_data)

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
        return self.action_command_orchestrator.execute(route)

    def _resolve_action_targets(self, route: Route, *, trees_only: bool) -> tuple[list[ProjectContext], str | None]:
        return self.action_command_orchestrator.resolve_targets(route, trees_only=trees_only)

    @staticmethod
    def _selectors_from_passthrough(passthrough_args: Iterable[str]) -> set[str]:
        selectors: set[str] = set()
        for token in passthrough_args:
            if token.startswith("-"):
                continue
            parts = [part.strip().lower() for part in token.split(",")]
            selectors.update(part for part in parts if part)
        return selectors

    def _projects_for_services(self, service_targets: list[object]) -> list[str]:
        return self.action_command_orchestrator.projects_for_services(service_targets)

    @staticmethod
    def _project_name_from_service(service_name: str) -> str:
        text = service_name.strip()
        lowered = text.lower()
        if lowered.endswith(" backend"):
            return text[:-8].strip()
        if lowered.endswith(" frontend"):
            return text[:-9].strip()
        return ""

    def _run_test_action(self, route: Route, targets: list[ProjectContext]) -> int:
        return self.action_command_orchestrator.run_test_action(route, targets)

    def _run_pr_action(self, route: Route, targets: list[ProjectContext]) -> int:
        return self.action_command_orchestrator.run_pr_action(route, targets)

    def _run_commit_action(self, route: Route, targets: list[ProjectContext]) -> int:
        return self.action_command_orchestrator.run_commit_action(route, targets)

    def _run_analyze_action(self, route: Route, targets: list[ProjectContext]) -> int:
        return self.action_command_orchestrator.run_review_action(route, targets)

    def _run_migrate_action(self, route: Route, targets: list[ProjectContext]) -> int:
        return self.action_command_orchestrator.run_migrate_action(route, targets)

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
        return self.action_command_orchestrator.run_project_action(
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
        return self.action_command_orchestrator.run_delete_worktree_action(route)

    def _action_replacements(
        self,
        targets: list[ProjectContext],
        *,
        target: ProjectContext | None,
    ) -> dict[str, str]:
        return self.action_command_orchestrator.action_replacements(targets, target=target)

    def _action_env(
        self,
        command_name: str,
        targets: list[ProjectContext],
        *,
        target: ProjectContext | None,
        extra: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        return self.action_command_orchestrator.action_env(
            command_name,
            targets,
            target=target,
            extra=extra,
        )

    @staticmethod
    def _action_extra_env(route: Route) -> dict[str, str]:
        return ActionCommandOrchestrator.action_extra_env(route)

    def _unsupported_command(self, command: str) -> int:
        print(
            "Command is not yet fully implemented in the Python runtime: "
            f"{command}."
        )
        return 1

    def _stop(self, route: Route) -> int:
        return self.lifecycle_cleanup_orchestrator.execute(route)

    def _clear_runtime_state(self, *, command: str, aggressive: bool = False, route: Route | None = None) -> None:
        self.lifecycle_cleanup_orchestrator.clear_runtime_state(
            command=command,
            aggressive=aggressive,
            route=route,
        )

    def _blast_all_ecosystem_cleanup(self, *, route: Route | None) -> None:
        self.lifecycle_cleanup_orchestrator.blast_all_ecosystem_cleanup(route=route)

    @staticmethod
    def _blast_all_process_patterns() -> tuple[str, ...]:
        return LifecycleCleanupOrchestrator.blast_all_process_patterns()

    def _blast_all_sweep_ports(self) -> None:
        self.lifecycle_cleanup_orchestrator.blast_all_sweep_ports()

    def _blast_all_sweep_ports_batched(self) -> bool:
        return self.lifecycle_cleanup_orchestrator.blast_all_sweep_ports_batched()

    def _blast_all_sweep_ports_by_port(self) -> None:
        self.lifecycle_cleanup_orchestrator.blast_all_sweep_ports_by_port()

    def _blast_all_handle_listener_pid_map(self, pid_port_map: dict[int, set[int]]) -> None:
        self.lifecycle_cleanup_orchestrator.blast_all_handle_listener_pid_map(pid_port_map)

    def _blast_all_process_command(self, pid: int) -> str:
        return self.lifecycle_cleanup_orchestrator.blast_all_process_command(pid)

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

    def _parse_blast_all_lsof_listeners(self, stdout: str) -> dict[int, set[int]] | None:
        return self.lifecycle_cleanup_orchestrator.parse_blast_all_lsof_listeners(stdout)

    def _blast_all_port_range(self) -> list[int]:
        return self.lifecycle_cleanup_orchestrator.blast_all_port_range()

    def _blast_all_scan_span(self, *, default: int, minimum: int) -> int:
        return self.lifecycle_cleanup_orchestrator.blast_all_scan_span(default=default, minimum=minimum)

    def _blast_all_kill_orchestrator_processes(self) -> None:
        self.lifecycle_cleanup_orchestrator.blast_all_kill_orchestrator_processes()

    def _blast_all_kill_pid_tree(self, root_pid: int, *, skip_pids: set[int] | None = None) -> None:
        self.lifecycle_cleanup_orchestrator.blast_all_kill_pid_tree(root_pid, skip_pids=skip_pids)

    def _blast_all_process_tree_kill_order(self, root_pid: int) -> list[int]:
        return self.lifecycle_cleanup_orchestrator.blast_all_process_tree_kill_order(root_pid)

    @staticmethod
    def _blast_all_is_orchestrator_process(command_text: str) -> bool:
        return LifecycleCleanupOrchestrator.blast_all_is_orchestrator_process(command_text)

    @staticmethod
    def _looks_like_docker_process(command_text: str) -> bool:
        return LifecycleCleanupOrchestrator.looks_like_docker_process(command_text)

    def _blast_all_docker_cleanup(self, *, route: Route | None) -> int:
        return self.lifecycle_cleanup_orchestrator.blast_all_docker_cleanup(route=route)

    @staticmethod
    def _blast_all_matches_container(*, image: str, name: str) -> bool:
        return LifecycleCleanupOrchestrator.blast_all_matches_container(image=image, name=name)

    def _blast_all_volume_policy(self, route: Route | None) -> tuple[bool, bool]:
        return self.lifecycle_cleanup_orchestrator.blast_all_volume_policy(route)

    def _blast_all_is_main_container(self, name: str) -> bool:
        return self.lifecycle_cleanup_orchestrator.blast_all_is_main_container(name)

    def _blast_all_main_container_names(self) -> tuple[str, str]:
        return self.lifecycle_cleanup_orchestrator.blast_all_main_container_names()

    def _blast_all_main_supabase_project_name(self) -> str:
        return self.lifecycle_cleanup_orchestrator.blast_all_main_supabase_project_name()

    def _collect_container_volume_candidates(self, cid: str, volume_candidates: list[str]) -> None:
        self.lifecycle_cleanup_orchestrator.collect_container_volume_candidates(cid, volume_candidates)

    def _blast_all_purge_legacy_state_artifacts(self) -> None:
        self.lifecycle_cleanup_orchestrator.blast_all_purge_legacy_state_artifacts()

    @staticmethod
    def _prompt_yes_no(prompt: str) -> bool:
        return LifecycleCleanupOrchestrator.prompt_yes_no(prompt)

    def _run_best_effort_command(
        self,
        cmd: list[str],
        *,
        timeout: float | None = None,
    ) -> tuple[int, str, str]:
        return self.lifecycle_cleanup_orchestrator.run_best_effort_command(cmd, timeout=timeout)

    def _blast_all_ecosystem_enabled(self) -> bool:
        return self.lifecycle_cleanup_orchestrator.blast_all_ecosystem_enabled()

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

    @staticmethod
    def _requirement_key_for_project(state: RunState, project_name: str) -> str | None:
        return runtime_requirement_key_for_project(state, project_name)

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

    def _sanitize_emit_payload(self, event_name: str, payload: dict[str, object]) -> dict[str, object]:
        return runtime_sanitize_emit_payload(self, event_name, payload)

    def _emit(self, event_name: str, **payload: object) -> None:
        runtime_emit(self, event_name, **payload)

    def _event_trace_id(self, *, event_name: str, payload: Mapping[str, object]) -> str:
        return runtime_event_trace_id(self, event_name=event_name, payload=payload)

    def _debug_trace_id_mode(self) -> str:
        return runtime_debug_trace_id_mode(self)

    def _auto_debug_pack(self, *, reason: str) -> None:
        runtime_auto_debug_pack(self, reason=reason)

    def _debug_should_auto_pack(self, *, reason: str) -> bool:
        return runtime_debug_should_auto_pack(self, reason=reason)

    def _persist_events_snapshot(self) -> None:
        runtime_persist_events_snapshot(self)

    def _configure_debug_recorder(self, route: Route) -> None:
        runtime_configure_debug_recorder(self, route)

    def _current_session_id(self) -> str | None:
        return runtime_current_session_id(self)

    def _debug_mode_from_route(self, route: Route) -> str:
        return runtime_debug_mode_from_route(self, route)

    def _debug_recorder_config(self, *, mode: str) -> DebugRecorderConfig:
        return runtime_debug_recorder_config(self, mode=mode)

    def _debug_output_root(self) -> Path | None:
        return runtime_debug_output_root(self)

    def _run_state_path(self) -> Path:
        return runtime_run_state_path(self)

    def _run_dir_path(self, run_id: str | None) -> Path:
        return runtime_run_dir_path(self, run_id)

    def _runtime_map_path(self) -> Path:
        return runtime_runtime_map_path(self)

    def _ports_manifest_path(self) -> Path:
        return runtime_ports_manifest_path(self)

    def _error_report_path(self) -> Path:
        return runtime_error_report_path(self)

    def _lock_inventory(self) -> list[str]:
        return runtime_lock_inventory(self)

    def _new_run_id(self) -> str:
        return runtime_new_run_id(self)

    def _bind_debug_run_id(self, run_id: str | None) -> None:
        runtime_bind_debug_run_id(self, run_id)

    def _reset_project_startup_warnings(self) -> None:
        with self._startup_warnings_lock:
            self._startup_warnings_by_project = {}

    def _record_project_startup_warning(self, project: str, message: str) -> None:
        project_name = str(project).strip()
        warning_text = str(message).strip()
        if not project_name or not warning_text:
            return
        with self._startup_warnings_lock:
            self._startup_warnings_by_project.setdefault(project_name, []).append(warning_text)

    def _consume_project_startup_warnings(self, project: str) -> list[str]:
        project_name = str(project).strip()
        if not project_name:
            return []
        with self._startup_warnings_lock:
            warnings = list(self._startup_warnings_by_project.pop(project_name, []))
        return warnings

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

    def _requirement_enabled(self, service_name: str, *, mode: str, route: Route | None = None) -> bool:
        return runtime_requirement_enabled(self, service_name, mode=mode, route=route)

    @staticmethod
    def _skipped_requirement(service_name: str, plan: PortPlan) -> RequirementOutcome:
        return runtime_skipped_requirement(service_name, plan)

    def _requirements_ready(self, result: RequirementsResult) -> bool:
        return runtime_requirements_ready(self, result)

    def _validate_mode_toggles(self, mode: str, *, route: Route | None = None) -> None:
        runtime_validate_mode_toggles(self, mode, route=route)

    def _project_service_env(
        self,
        context: ProjectContext,
        *,
        requirements: RequirementsResult,
        route: Route | None = None,
    ) -> dict[str, str]:
        return runtime_project_service_env(self, context, requirements=requirements, route=route)

    def _runtime_env_overrides(self, route: Route | None) -> dict[str, str]:
        return runtime_env_overrides(route)

    def _main_requirements_mode(self, route: Route | None) -> str | None:
        return runtime_main_requirements_mode(route)

    def _effective_main_requirement_flags(self, route: Route | None) -> dict[str, bool]:
        return runtime_effective_main_requirement_flags(self, route)

    def _service_enabled_for_mode(self, mode: str, service_name: str) -> bool:
        return runtime_service_enabled_for_mode(self, mode, service_name)

    def _requirement_enabled_for_mode(self, mode: str, requirement_name: str, *, route: Route | None = None) -> bool:
        return runtime_requirement_enabled_for_mode(self, mode, requirement_name, route=route)

    def _hook_bridge_enabled(self) -> bool:
        return runtime_hook_bridge_enabled(self)

    def _invoke_envctl_hook(self, *, context: ProjectContext, hook_name: str) -> HookInvocationResult:
        return runtime_invoke_envctl_hook(self, context=context, hook_name=hook_name)

    def _startup_hook_contract_issue(self) -> str | None:
        return runtime_startup_hook_contract_issue(self)

    def _requirements_result_from_hook_payload(
        self,
        *,
        context: ProjectContext,
        mode: str,
        payload: Mapping[str, object],
    ) -> RequirementsResult:
        return runtime_requirements_result_from_hook_payload(self, context=context, mode=mode, payload=payload)

    def _services_from_hook_payload(
        self,
        *,
        context: ProjectContext,
        payload: Mapping[str, object],
    ) -> dict[str, ServiceRecord]:
        return runtime_services_from_hook_payload(self, context=context, payload=payload)

    def _supabase_fingerprint_path(self, project_name: str) -> Path:
        return runtime_supabase_fingerprint_path(self, project_name)

    def _supabase_auto_reinit_enabled(self) -> bool:
        return runtime_supabase_auto_reinit_enabled(self)

    @staticmethod
    def _supabase_reinit_required_message() -> str:
        return runtime_supabase_reinit_required_message()

    def _run_supabase_reinit(self, *, project_root: Path, project_name: str, db_port: int) -> str | None:
        return runtime_run_supabase_reinit(self, project_root=project_root, project_name=project_name, db_port=db_port)

    @staticmethod
    def _command_result_error_text(*, result: object) -> str:
        return runtime_command_result_error_text(result=result)

    def _service_listener_failure_detail(self, *, log_path: str | None, pid: int | None) -> str | None:
        return runtime_service_listener_failure_detail(self, log_path=log_path, pid=pid)

    @staticmethod
    def _tail_log_error_line(log_path: str | None, *, max_chars: int = 240) -> str | None:
        return runtime_tail_log_error_line(log_path, max_chars=max_chars)

    def _wait_for_service_listener(self, pid: int, port: int, *, service_name: str) -> bool:
        return runtime_wait_for_service_listener(self, pid, port, service_name=service_name)

    def _process_tree_probe_supported(self) -> bool:
        return runtime_process_tree_probe_supported(self)

    def _service_truth_fallback_enabled(self) -> bool:
        return runtime_service_truth_fallback_enabled(self)

    def _detect_service_actual_port(
        self,
        *,
        pid: int | None,
        requested_port: int,
        service_name: str,
        debug_listener_group: str = "",
        debug_pid_wait_group: str = "",
    ) -> int | None:
        return runtime_detect_service_actual_port(
            self,
            pid=pid,
            requested_port=requested_port,
            service_name=service_name,
            debug_listener_group=debug_listener_group,
            debug_pid_wait_group=debug_pid_wait_group,
        )

    def _service_rebound_max_delta(self) -> int:
        return runtime_service_rebound_max_delta(self)

    def _service_listener_timeout(self) -> float:
        return runtime_service_listener_timeout(self)

    def _dashboard_truth_refresh_seconds(self) -> float:
        return runtime_dashboard_truth_refresh_seconds(self)

    def _dashboard_reconcile_for_snapshot(self, state: RunState) -> list[str]:
        return runtime_dashboard_reconcile_for_snapshot(self, state)

    def _service_truth_timeout(self) -> float:
        return runtime_service_truth_timeout(self)

    def _service_startup_grace_seconds(self) -> float:
        return runtime_service_startup_grace_seconds(self)

    def _service_within_startup_grace(self, service: object) -> bool:
        return runtime_service_within_startup_grace(self, service)

    def _requirement_command(
        self,
        *,
        service_name: str,
        port: int,
        project_root: Path | None = None,
    ) -> list[str]:
        return runtime_requirement_command(self, service_name=service_name, port=port, project_root=project_root)

    def _requirement_command_source(
        self,
        *,
        service_name: str,
        port: int,
        project_root: Path | None = None,
    ) -> str:
        return runtime_requirement_command_source(self, service_name=service_name, port=port, project_root=project_root)

    def _requirement_command_resolved(
        self,
        *,
        service_name: str,
        port: int,
        project_root: Path | None = None,
    ) -> tuple[list[str], str]:
        return runtime_requirement_command_resolved(
            self,
            service_name=service_name,
            port=port,
            project_root=project_root,
        )

    def _service_start_command(
        self,
        *,
        service_name: str,
        project_root: Path | None = None,
        port: int = 0,
    ) -> list[str]:
        return runtime_service_start_command(self, service_name=service_name, project_root=project_root, port=port)

    def _service_command_source(
        self,
        *,
        service_name: str,
        project_root: Path | None = None,
        port: int = 0,
    ) -> str:
        return runtime_service_command_source(self, service_name=service_name, project_root=project_root, port=port)

    def _service_start_command_resolved(
        self,
        *,
        service_name: str,
        project_root: Path | None = None,
        port: int = 0,
    ) -> tuple[list[str], str]:
        return runtime_service_start_command_resolved(
            self,
            service_name=service_name,
            project_root=project_root,
            port=port,
        )

    def _command_override_value(self, key: str) -> str | None:
        return runtime_command_override_value(self, key)

    def _split_command(
        self,
        raw: str,
        *,
        port: int | None = None,
        replacements: Mapping[str, str] | None = None,
    ) -> list[str]:
        return runtime_split_command(self, raw, port=port, replacements=replacements)

    def _command_env(self, *, port: int, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        return runtime_command_env(self, port=port, extra=extra)

    def _default_python_executable(self) -> str:
        return runtime_default_python_executable(self)

    @staticmethod
    def _command_exists(executable: str) -> bool:
        return runtime_command_exists(executable)

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
