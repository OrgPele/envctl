from __future__ import annotations

from pathlib import Path
from typing import Mapping

from envctl_engine.runtime.command_router import Route
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
from envctl_engine.runtime.engine_runtime_dashboard_truth import (
    dashboard_reconcile_for_snapshot as runtime_dashboard_reconcile_for_snapshot,
    dashboard_truth_refresh_seconds as runtime_dashboard_truth_refresh_seconds,
)
from envctl_engine.runtime.engine_runtime_env import (
    project_service_env as runtime_project_service_env,
    project_service_env_internal as runtime_project_service_env_internal,
    requirement_enabled_for_mode as runtime_requirement_enabled_for_mode,
    requirements_ready as runtime_requirements_ready,
    runtime_env_overrides as runtime_env_overrides,
    service_enabled_for_mode as runtime_service_enabled_for_mode,
    skipped_requirement as runtime_skipped_requirement,
    validate_mode_toggles as runtime_validate_mode_toggles,
)
from envctl_engine.runtime.engine_runtime_hooks import (
    invoke_envctl_hook as runtime_invoke_envctl_hook,
    requirements_result_from_hook_payload as runtime_requirements_result_from_hook_payload,
    run_supabase_reinit as runtime_run_supabase_reinit,
    services_from_hook_payload as runtime_services_from_hook_payload,
    startup_hook_contract_issue as runtime_startup_hook_contract_issue,
    supabase_auto_reinit_enabled as runtime_supabase_auto_reinit_enabled,
    supabase_fingerprint_path as runtime_supabase_fingerprint_path,
    supabase_reinit_required_message as runtime_supabase_reinit_required_message,
)
from envctl_engine.runtime.engine_runtime_misc_support import requirement_enabled as runtime_requirement_enabled
from envctl_engine.runtime.engine_runtime_service_policy import (
    service_listener_timeout as runtime_service_listener_timeout,
    service_rebound_max_delta as runtime_service_rebound_max_delta,
    service_startup_grace_seconds as runtime_service_startup_grace_seconds,
    service_startup_progress_timeout as runtime_service_startup_progress_timeout,
    service_truth_timeout as runtime_service_truth_timeout,
    service_within_startup_grace as runtime_service_within_startup_grace,
)
from envctl_engine.runtime.engine_runtime_service_truth import (
    command_result_error_text as runtime_command_result_error_text,
    detect_service_actual_port as runtime_detect_service_actual_port,
    service_listener_failure_detail as runtime_service_listener_failure_detail,
    service_truth_fallback_enabled as runtime_service_truth_fallback_enabled,
)
from envctl_engine.state.models import PortPlan, RequirementsResult, RunState, ServiceRecord
from envctl_engine.requirements.orchestrator import RequirementOutcome
from envctl_engine.shared.hooks import HookInvocationResult
from envctl_engine.startup.protocols import ProjectContextLike


class RuntimeServiceFacadeMixin:
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
        context: ProjectContextLike,
        *,
        requirements: RequirementsResult,
        route: Route | None = None,
        service_name: str | None = None,
    ) -> dict[str, str]:
        return runtime_project_service_env(
            self, context, requirements=requirements, route=route, service_name=service_name
        )

    def _project_service_env_internal(
        self,
        context: ProjectContextLike,
        *,
        requirements: RequirementsResult,
        route: Route | None = None,
    ) -> dict[str, str]:
        return runtime_project_service_env_internal(self, context, requirements=requirements, route=route)

    def _runtime_env_overrides(self, route: Route | None) -> dict[str, str]:
        return runtime_env_overrides(route)

    def _service_enabled_for_mode(self, mode: str, service_name: str) -> bool:
        return runtime_service_enabled_for_mode(self, mode, service_name)

    def _requirement_enabled_for_mode(self, mode: str, requirement_name: str, *, route: Route | None = None) -> bool:
        return runtime_requirement_enabled_for_mode(self, mode, requirement_name, route=route)

    def _invoke_envctl_hook(self, *, context: ProjectContextLike, hook_name: str) -> HookInvocationResult:
        return runtime_invoke_envctl_hook(self, context=context, hook_name=hook_name)

    def _startup_hook_contract_issue(self) -> str | None:
        return runtime_startup_hook_contract_issue(self)

    def _requirements_result_from_hook_payload(
        self,
        *,
        context: ProjectContextLike,
        mode: str,
        payload: Mapping[str, object],
    ) -> RequirementsResult:
        return runtime_requirements_result_from_hook_payload(self, context=context, mode=mode, payload=payload)

    def _services_from_hook_payload(
        self,
        *,
        context: ProjectContextLike,
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

    def _run_supabase_reinit(
        self, *, project_root: Path, project_name: str, db_port: int, public_port: int | None = None
    ) -> str | None:
        return runtime_run_supabase_reinit(
            self, project_root=project_root, project_name=project_name, db_port=db_port, public_port=public_port
        )

    @staticmethod
    def _command_result_error_text(*, result: object) -> str:
        return runtime_command_result_error_text(result=result)

    def _service_listener_failure_detail(self, *, log_path: str | None, pid: int | None) -> str | None:
        return runtime_service_listener_failure_detail(self, log_path=log_path, pid=pid)

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
        log_path: str | None = None,
    ) -> int | None:
        return runtime_detect_service_actual_port(
            self,
            pid=pid,
            requested_port=requested_port,
            service_name=service_name,
            debug_listener_group=debug_listener_group,
            debug_pid_wait_group=debug_pid_wait_group,
            log_path=log_path,
        )

    def _service_rebound_max_delta(self) -> int:
        return runtime_service_rebound_max_delta(self)

    def _service_listener_timeout(self) -> float:
        return runtime_service_listener_timeout(self)

    def _service_startup_progress_timeout(self) -> float:
        return runtime_service_startup_progress_timeout(self)

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
        cwd: str | Path | None = None,
    ) -> list[str]:
        return runtime_split_command(self, raw, port=port, replacements=replacements, cwd=cwd)

    def _command_env(self, *, port: int, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        return runtime_command_env(self, port=port, extra=extra)

    def _default_python_executable(self) -> str:
        return runtime_default_python_executable(self)

    @staticmethod
    def _command_exists(executable: str) -> bool:
        return runtime_command_exists(executable)
