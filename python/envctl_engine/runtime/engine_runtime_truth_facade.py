from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from envctl_engine.runtime.engine_runtime_service_truth import (
    assert_project_services_post_start_truth as runtime_assert_project_services_post_start_truth,
    clear_service_listener_pids as runtime_clear_service_listener_pids,
    listener_pids_for_port as runtime_listener_pids_for_port,
    rebind_stale_service_pid as runtime_rebind_stale_service_pid,
    refresh_service_listener_pids as runtime_refresh_service_listener_pids,
    service_truth_discovery as runtime_service_truth_discovery,
    service_truth_status as runtime_service_truth_status,
)
from envctl_engine.runtime.engine_runtime_state_support import (
    on_port_event as runtime_on_port_event,
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
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RequirementsResult, RunState


class RuntimeTruthFacadeMixin:
    def _state_lookup_strict_mode_match(self, route: Route) -> bool:
        return runtime_state_lookup_strict_mode_match(self, route)

    def _state_action(self, route: Route) -> int:
        return runtime_state_action(self, route)

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
        context: Any,
        services: Mapping[str, object],
    ) -> None:
        runtime_assert_project_services_post_start_truth(self, context=context, services=services)

    @staticmethod
    def _state_has_synthetic_services(state: RunState) -> bool:
        return runtime_state_has_synthetic_services(state)

    def _on_port_event(self, event_name: str, payload: dict[str, object]) -> None:
        runtime_on_port_event(self, event_name, payload)
