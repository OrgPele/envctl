from __future__ import annotations

from typing import Callable, Mapping

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.startup.resume_progress import ResumeProjectSpinnerGroup as _ResumeProjectSpinnerGroup
from envctl_engine.startup.resume_restore_execution import (
    ResumeRestoreDependencies,
    ResumeRestoreRunner,
)
from envctl_engine.startup.resume_restore_results import (
    format_project_timing_line as _format_project_timing_line,  # noqa: F401
    mark_restore_failure_requirements as _mark_restore_failure_requirements,  # noqa: F401
)
from envctl_engine.startup.resume_restore_policy import (
    _configured_restore_service_types as _configured_restore_service_types,
    _port_allocator as _port_allocator,
    _requirements_reuse_decision as _requirements_reuse_decision,
    _reserve_application_service_ports as _reserve_application_service_ports,
    _restore_parallel_config as _restore_parallel_config,
    _restore_timing_enabled as _restore_timing_enabled,
    _resume_terminate_aggressive as _resume_terminate_aggressive,
    _route_for_partial_service_restore as _route_for_partial_service_restore,
    _service_types_for_names as _service_types_for_names,
    _state_repository as _state_repository,
    apply_ports_to_context as apply_ports_to_context,
    context_for_project as context_for_project,
    project_root as project_root,
)
from envctl_engine.ui.spinner import spinner, spinner_enabled, use_spinner_policy
from envctl_engine.ui.spinner_service import emit_spinner_policy, resolve_spinner_policy


def restore_missing(
    orchestrator,
    state: RunState,
    missing_services: list[str],
    *,
    route: Route | None = None,
    spinner_factory: Callable[..., object] = spinner,
    spinner_enabled_fn: Callable[[Mapping[str, str] | None], bool] = spinner_enabled,
    use_spinner_policy_fn: Callable[[object], object] = use_spinner_policy,
    emit_spinner_policy_fn: Callable[..., None] = emit_spinner_policy,
    resolve_spinner_policy_fn: Callable[[Mapping[str, str] | None], object] = resolve_spinner_policy,
    project_spinner_group_cls: type[_ResumeProjectSpinnerGroup] = _ResumeProjectSpinnerGroup,
) -> list[str]:
    return ResumeRestoreRunner(
        orchestrator=orchestrator,
        state=state,
        missing_services=missing_services,
        route=route,
        dependencies=ResumeRestoreDependencies(
            spinner_factory=spinner_factory,
            spinner_enabled_fn=spinner_enabled_fn,
            use_spinner_policy_fn=use_spinner_policy_fn,
            emit_spinner_policy_fn=emit_spinner_policy_fn,
            resolve_spinner_policy_fn=resolve_spinner_policy_fn,
            project_spinner_group_cls=project_spinner_group_cls,
        ),
    ).execute()
