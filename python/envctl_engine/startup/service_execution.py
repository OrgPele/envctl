from __future__ import annotations

from envctl_engine.startup.protocols import ProjectContextLike, StartupOrchestratorLike
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RequirementsResult, ServiceRecord
from envctl_engine.startup.service_attach_execution import ServiceAttachRunner
from envctl_engine.startup.service_execution_environment import (
    configured_service_types_for_mode,
    make_service_dependency_emitter,
    make_service_retry_emitter,
    project_env_for_service,
    project_service_log_path,
    project_service_log_paths,
    resolve_service_workdirs,
)
from envctl_engine.startup.service_execution_policy import (
    _project_backend_cors_origin,
    additional_service_enabled_for_context,
    apply_service_env_overlays,
    backend_listener_expected_for_mode,
    coerce_env_mapping,
    ordered_service_layers,
    resolve_command_env_builder,
    resolve_project_service_env,
    resolve_service_env_overlay_builder,
    service_attach_parallel_enabled,
    service_prep_parallel_enabled,
)
from envctl_engine.startup.service_execution_records import (
    LaunchedServiceRuntime,
    PreparedServiceLaunch,
    finalize_launched_service_records,
)
from envctl_engine.startup.service_launch_diagnostics import record_runtime_launch_diagnostics
from envctl_engine.startup.service_project_execution import (
    NO_LOCAL_APP_SYSTEM_WARNING,
    start_project_services_impl,
)


def start_project_services(
    orchestrator: StartupOrchestratorLike,
    context: ProjectContextLike,
    *,
    requirements: RequirementsResult,
    run_id: str,
    route: Route | None = None,
) -> dict[str, ServiceRecord]:
    return start_project_services_impl(
        orchestrator,
        context,
        requirements=requirements,
        run_id=run_id,
        route=route,
    )


__all__ = [
    "LaunchedServiceRuntime",
    "NO_LOCAL_APP_SYSTEM_WARNING",
    "PreparedServiceLaunch",
    "ServiceAttachRunner",
    "_project_backend_cors_origin",
    "additional_service_enabled_for_context",
    "apply_service_env_overlays",
    "backend_listener_expected_for_mode",
    "coerce_env_mapping",
    "configured_service_types_for_mode",
    "finalize_launched_service_records",
    "make_service_dependency_emitter",
    "make_service_retry_emitter",
    "ordered_service_layers",
    "project_env_for_service",
    "project_service_log_path",
    "project_service_log_paths",
    "record_runtime_launch_diagnostics",
    "resolve_command_env_builder",
    "resolve_project_service_env",
    "resolve_service_env_overlay_builder",
    "resolve_service_workdirs",
    "service_attach_parallel_enabled",
    "service_prep_parallel_enabled",
    "start_project_services",
]
