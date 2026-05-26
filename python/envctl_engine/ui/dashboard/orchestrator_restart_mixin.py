from __future__ import annotations

from typing import Any, cast

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard.restart_selection_support import (
    apply_restart_resource_selection,
    apply_restart_resource_tokens,
    apply_restart_selection,
    dashboard_configured_missing_services_by_project,
    dashboard_project_configured_services,
    dashboard_stopped_services_by_project,
    has_dashboard_stopped_services,
    has_restartable_inactive_services,
    restart_project_order,
    restart_resource_items,
    restart_services_by_project,
)
from envctl_engine.ui.selector_model import SelectorItem


def _selector_impl() -> Any:
    from envctl_engine.ui.dashboard import orchestrator

    return orchestrator._run_selector_with_impl


class DashboardRestartSelectionMixin:
    def _apply_restart_selection(self, route: Route, state: RunState, rt: object) -> Route | None:
        runtime_any = cast(Any, rt)
        return apply_restart_selection(
            route,
            state,
            runtime_any,
            has_restartable_inactive_services_fn=self._has_restartable_inactive_services,
            stop_dependencies_by_project_fn=self._stop_dependencies_by_project,
            apply_restart_resource_selection_fn=self._apply_restart_resource_selection,
            select_dashboard_projects_fn=self._select_dashboard_projects,
            select_dashboard_service_types_fn=self._select_dashboard_service_types,
            service_names_for_projects_and_types_fn=self._service_names_for_projects_and_types,
            project_names_from_state_fn=self._project_names_from_state,
            project_name_list_fn=self._project_name_list,
            available_service_types_for_projects_fn=self._available_service_types_for_projects,
        )

    def _apply_restart_resource_selection(self, route: Route, state: RunState, runtime: Any) -> Route | None:
        return apply_restart_resource_selection(
            route,
            state,
            runtime,
            restart_resource_items_fn=self._restart_resource_items,
            apply_restart_resource_tokens_fn=self._apply_restart_resource_tokens,
            selector_fn=_selector_impl(),
        )

    def _restart_resource_items(self, state: RunState, runtime: Any) -> list[SelectorItem]:
        return restart_resource_items(
            state,
            runtime,
            restart_project_order_fn=self._restart_project_order,
            restart_services_by_project_fn=self._restart_services_by_project,
            stop_dependencies_by_project_fn=self._stop_dependencies_by_project,
            stop_service_detail_fn=self._stop_service_detail,
        )

    def _apply_restart_resource_tokens(self, route: Route, state: RunState, runtime: Any, values: list[str]) -> None:
        apply_restart_resource_tokens(route, state, runtime, values)

    @staticmethod
    def _has_dashboard_stopped_services(state: RunState) -> bool:
        return has_dashboard_stopped_services(
            state,
            dashboard_stopped_services_by_project_fn=dashboard_stopped_services_by_project,
        )

    @staticmethod
    def _has_restartable_inactive_services(state: RunState) -> bool:
        return has_restartable_inactive_services(
            state,
            dashboard_stopped_services_by_project_fn=dashboard_stopped_services_by_project,
            dashboard_configured_missing_services_by_project_fn=dashboard_configured_missing_services_by_project,
        )

    def _restart_project_order(self, state: RunState, runtime: Any) -> list[str]:
        return restart_project_order(
            state,
            runtime,
            stop_project_order_fn=self._stop_project_order,
            dashboard_stopped_services_by_project_fn=self._dashboard_stopped_services_by_project,
            dashboard_project_configured_services_fn=self._dashboard_project_configured_services,
        )

    def _restart_services_by_project(self, state: RunState, runtime: Any) -> dict[str, list[tuple[str, str, bool]]]:
        return restart_services_by_project(state, runtime)

    @staticmethod
    def _dashboard_stopped_services_by_project(state: RunState) -> dict[str, dict[str, str]]:
        return dashboard_stopped_services_by_project(state)

    @staticmethod
    def _dashboard_project_configured_services(state: RunState) -> dict[str, set[str]]:
        return dashboard_project_configured_services(state)

    @staticmethod
    def _dashboard_configured_missing_services_by_project(state: RunState) -> dict[str, set[str]]:
        return dashboard_configured_missing_services_by_project(state)
