from __future__ import annotations

from typing import Any, cast

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard.failure_detail_support import (
    ensure_short_test_summary_path,
    failure_details_available,
    print_interactive_failure_details,
    print_migrate_result_details,
    print_project_action_failure_details,
    print_test_failure_details,
    summary_display_path,
)


class DashboardFailureDetailMixin:
    runtime: Any

    def _print_interactive_failure_details(self, route: Route, state: RunState, *, code: int) -> None:
        print_interactive_failure_details(
            route=route,
            state=state,
            code=code,
            runtime=self.runtime,
            test_failure_details_available_fn=self._failure_details_available,
            print_test_failure_details_fn=self._print_test_failure_details,
            print_project_action_failure_details_fn=self._print_project_action_failure_details,
        )

    def _failure_details_available(self, route: Route, state: RunState) -> bool:
        return failure_details_available(
            route,
            state,
            project_names_from_state_fn=lambda s: self._project_names_from_state(s, cast(Any, self.runtime)),
        )

    def _print_test_failure_details(self, route: Route, state: RunState) -> bool:
        return print_test_failure_details(
            route,
            state,
            runtime=self.runtime,
            project_names_from_state_fn=lambda s: self._project_names_from_state(s, cast(Any, self.runtime)),
        )

    @staticmethod
    def _summary_display_path(*, project_name: str, entry: dict[str, object]) -> str:
        return summary_display_path(project_name=project_name, entry=entry)

    @staticmethod
    def _ensure_short_test_summary_path(*, project_name: str, summary_path: str) -> str:
        return ensure_short_test_summary_path(project_name=project_name, summary_path=summary_path)

    def _print_project_action_failure_details(self, route: Route, state: RunState) -> bool:
        return print_project_action_failure_details(
            route,
            state,
            runtime=self.runtime,
            project_names_from_state_fn=lambda s: self._project_names_from_state(s, cast(Any, self.runtime)),
            project_name_list_fn=self._project_name_list,
        )

    def _print_migrate_result_details(self, route: Route, state: RunState) -> bool:
        return print_migrate_result_details(
            route,
            state,
            runtime=self.runtime,
            project_names_from_state_fn=lambda s: self._project_names_from_state(s, cast(Any, self.runtime)),
            project_name_list_fn=self._project_name_list,
        )
