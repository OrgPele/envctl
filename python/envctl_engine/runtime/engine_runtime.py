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
from envctl_engine.runtime.engine_runtime_state_truth import (
    reconcile_project_requirement_truth as runtime_reconcile_project_requirement_truth,
    reconcile_state_truth as runtime_reconcile_state_truth,
    requirement_truth_issues as runtime_requirement_truth_issues,
    state_fingerprint as runtime_state_fingerprint,
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
from envctl_engine.runtime.engine_runtime_action_facade import RuntimeActionFacadeMixin
from envctl_engine.runtime.engine_runtime_cli_facade import (
    RuntimeCliFacadeMixin,
    render_help_text as runtime_render_help_text,
)
from envctl_engine.runtime.engine_runtime_doctor_facade import RuntimeDoctorFacadeMixin
from envctl_engine.runtime.engine_runtime_debug_facade import RuntimeDebugFacadeMixin
from envctl_engine.runtime.engine_runtime_planning_facade import RuntimePlanningFacadeMixin
from envctl_engine.runtime.engine_runtime_service_facade import RuntimeServiceFacadeMixin
from envctl_engine.runtime.engine_runtime_startup_facade import RuntimeStartupFacadeMixin
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
from envctl_engine.ui.dashboard.rendering import (
    _dashboard_palette as domain_dashboard_palette,
    _dashboard_status_badge as domain_dashboard_status_badge,
    _print_dashboard_n8n_row as domain_print_dashboard_n8n_row,
    _print_dashboard_service_row as domain_print_dashboard_service_row,
    _print_dashboard_snapshot as domain_print_dashboard_snapshot,
    _print_dashboard_tests_row as domain_print_dashboard_tests_row,
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


class PythonEngineRuntime(
    RuntimePlanningFacadeMixin,
    RuntimeStartupFacadeMixin,
    RuntimeServiceFacadeMixin,
    RuntimeActionFacadeMixin,
    RuntimeCliFacadeMixin,
    RuntimeDoctorFacadeMixin,
    RuntimeDebugFacadeMixin,
):
    PARTIAL_COMMANDS: tuple[str, ...] = ()
    _project_context_factory = ProjectContext

    _RUNTIME_CONTEXT_ATTR_MAP: dict[str, str] = {
        "process_runner": "process_runtime",
        "port_planner": "port_allocator",
        "state_repository": "state_repository",
        "terminal_ui": "terminal_ui",
    }

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

    def _ensure_legacy_lock_view(self) -> None:
        runtime_ensure_legacy_lock_view(self)

    def add_emit_listener(self, listener: Callable[[str, dict[str, object]], None]) -> Callable[[], None]:
        return runtime_add_emit_listener(self, listener)

    def dispatch(self, route: Route) -> int:
        return runtime_dispatch(self, route)

    def _state_compat_mode(self) -> str:
        return runtime_state_compat_mode(self)

    def _release_port_session(self) -> None:
        runtime_release_port_session(self)

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
