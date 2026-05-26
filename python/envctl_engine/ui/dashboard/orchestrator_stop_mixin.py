from __future__ import annotations

from typing import Any, cast

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard.stop_scope_support import (
    apply_stop_resource_tokens,
    apply_stop_scope_selection,
    stop_dependencies_by_project,
    stop_project_order,
    stop_resource_items,
    stop_route_has_explicit_scope,
    stop_service_detail,
    stop_service_type,
    stop_services_by_project,
)
from envctl_engine.ui.selector_model import SelectorItem


def _selector_impl() -> Any:
    from envctl_engine.ui.dashboard import orchestrator

    return orchestrator._run_selector_with_impl


class DashboardStopScopeMixin:
    def _apply_stop_scope_selection(self, route: Route, state: RunState, rt: object) -> Route | None:
        return apply_stop_scope_selection(
            route,
            state,
            cast(Any, rt),
            stop_resource_items_fn=self._stop_resource_items,
            apply_stop_resource_tokens_fn=self._apply_stop_resource_tokens,
            selector_fn=_selector_impl(),
        )

    @staticmethod
    def _stop_route_has_explicit_scope(route: Route, runtime: Any) -> bool:
        return stop_route_has_explicit_scope(route, runtime)

    def _stop_resource_items(self, state: RunState, runtime: Any) -> list[SelectorItem]:
        return stop_resource_items(
            state,
            runtime,
            project_names_from_state_fn=self._project_names_from_state,
            stop_project_order_fn=self._stop_project_order,
            stop_services_by_project_fn=self._stop_services_by_project,
            stop_dependencies_by_project_fn=self._stop_dependencies_by_project,
            stop_service_detail_fn=self._stop_service_detail,
        )

    def _apply_stop_resource_tokens(self, route: Route, state: RunState, runtime: Any, values: list[str]) -> None:
        apply_stop_resource_tokens(route, state, runtime, values)

    def _stop_project_order(self, state: RunState, runtime: Any) -> list[str]:
        return stop_project_order(state, runtime, project_names_from_state_fn=self._project_names_from_state)

    @staticmethod
    def _stop_services_by_project(state: RunState, runtime: Any) -> dict[str, list[tuple[str, str]]]:
        return stop_services_by_project(state, runtime)

    @staticmethod
    def _stop_dependencies_by_project(state: RunState) -> dict[str, list[tuple[str, str]]]:
        return stop_dependencies_by_project(state)

    @staticmethod
    def _stop_service_type(service_name: str, service: object) -> str:
        return stop_service_type(service_name, service)

    @staticmethod
    def _stop_service_detail(service_name: str, service_type: str) -> str:
        return stop_service_detail(service_name, service_type)
