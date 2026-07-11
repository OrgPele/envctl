from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Mapping, cast

from envctl_engine.runtime.engine_runtime_artifacts import (
    print_summary as runtime_print_summary,
    write_artifacts as runtime_write_artifacts,
    write_runtime_readiness_report as runtime_write_runtime_readiness_report,
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
from envctl_engine.runtime.engine_runtime_state_lookup import (
    state_matches_scope as runtime_state_matches_scope,
    try_load_existing_state as runtime_try_load_existing_state,
)
from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.runtime_readiness import RuntimeReadinessResult
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
    _rewrite_database_url_to_asyncpg as domain_rewrite_database_url_to_asyncpg,
    _run_backend_bootstrap_command as domain_run_backend_bootstrap_command,
    _run_backend_migration_step as domain_run_backend_migration_step,
    _run_frontend_bootstrap_command as domain_run_frontend_bootstrap_command,
    _service_env_from_file as domain_service_env_from_file,
    _skip_local_db_env as domain_skip_local_db_env,
    _sync_backend_env_file as domain_sync_backend_env_file,
)
from envctl_engine.state.models import PortPlan, RequirementsResult, RunState


def _startup_orchestrator(runtime: Any) -> Any:
    return getattr(runtime, "startup_orchestrator")


def _resume_orchestrator(runtime: Any) -> Any:
    return getattr(runtime, "resume_orchestrator")


def _project_context_factory(runtime: Any) -> Any:
    return getattr(runtime, "_project_context_factory")


class RuntimeStartupFacadeMixin:
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

    def _start(self, route: Route) -> int:
        return _startup_orchestrator(self).execute(route)

    def _effective_start_mode(self, route: Route) -> str:
        return runtime_effective_start_mode(self, route)

    def _state_has_resumable_services(self, state: RunState) -> bool:
        return runtime_state_has_resumable_services(self, state)

    def _start_project_context(
        self,
        *,
        context: Any,
        mode: str,
        route: Route,
        run_id: str,
    ) -> Any:
        return _startup_orchestrator(self).start_project_context(
            context=context,
            mode=mode,
            route=route,
            run_id=run_id,
        )

    def _tree_parallel_startup_config(self, *, mode: str, route: Route, project_count: int) -> tuple[bool, int]:
        return runtime_tree_parallel_startup_config(self, mode=mode, route=route, project_count=project_count)

    def _contexts_from_raw_projects(self, raw_projects: list[tuple[str, Path]]) -> list[Any]:
        return runtime_contexts_from_raw_projects(
            self,
            raw_projects,
            context_factory=_project_context_factory(self),
        )

    @staticmethod
    def _duplicate_project_context_error(contexts: list[Any]) -> str | None:
        return runtime_duplicate_project_context_error(contexts)

    def _resume(self, route: Route) -> int:
        return _resume_orchestrator(self).execute(route)

    def _sanitize_legacy_resume_state(self, state: RunState) -> None:
        runtime_sanitize_legacy_resume_state(self, state)

    def _resume_restore_missing(
        self,
        state: RunState,
        missing_services: list[str],
        *,
        route: Route | None = None,
    ) -> list[str]:
        return _resume_orchestrator(self).restore_missing(state, missing_services, route=route)

    def _resume_context_for_project(self, state: RunState, project: str) -> Any | None:
        return _resume_orchestrator(self).context_for_project(state, project)

    def _resume_project_root(self, state: RunState, project: str) -> Path | None:
        return _resume_orchestrator(self).project_root(state, project)

    def _apply_resume_ports_to_context(self, context: Any, state: RunState) -> None:
        _resume_orchestrator(self).apply_ports_to_context(context, state)

    def _set_plan_port_from_component(self, plan: PortPlan, component: Mapping[str, object]) -> None:
        runtime_set_plan_port_from_component(plan, component)

    @staticmethod
    def _set_plan_port(plan: PortPlan, port: int) -> None:
        runtime_set_plan_port(plan, port)

    def _discover_projects(self, *, mode: str) -> list[Any]:
        return runtime_discover_projects(self, mode=mode, context_factory=_project_context_factory(self))

    def _reserve_project_ports(self, context: Any, route: Route | None = None) -> None:
        runtime_reserve_project_ports(self, context, route=route)

    def _start_requirements_for_project(
        self,
        context: Any,
        *,
        mode: str,
        route: Route | None = None,
    ) -> RequirementsResult:
        return _startup_orchestrator(self).start_requirements_for_project(
            context,
            mode=mode,
            route=route,
        )

    def _start_project_services(
        self,
        context: Any,
        *,
        requirements: RequirementsResult,
        run_id: str,
        route: Route | None = None,
    ) -> dict[str, object]:
        return _startup_orchestrator(self).start_project_services(
            context,
            requirements=requirements,
            run_id=run_id,
            route=route,
        )

    def _write_artifacts(self, state: RunState, contexts: list[Any], *, errors: list[str]) -> None:
        runtime_write_artifacts(self, state, contexts, errors=errors)

    def _write_runtime_readiness_report(
        self,
        *,
        run_dir: Path | None = None,
        readiness_result: RuntimeReadinessResult | None = None,
    ) -> None:
        runtime_write_runtime_readiness_report(self, run_dir=run_dir, readiness_result=readiness_result)

    def _try_load_existing_state(
        self,
        *,
        mode: str | None = None,
        strict_mode_match: bool = False,
        project_names: Sequence[str] | None = None,
    ) -> RunState | None:
        return cast(
            RunState | None,
            runtime_try_load_existing_state(
                self,
                mode=mode,
                strict_mode_match=strict_mode_match,
                project_names=project_names,
            ),
        )

    def _state_matches_scope(self, state: RunState) -> bool:
        return runtime_state_matches_scope(self, state)

    def _print_summary(self, state: RunState, contexts: list[Any]) -> None:
        runtime_print_summary(self, state, contexts)
