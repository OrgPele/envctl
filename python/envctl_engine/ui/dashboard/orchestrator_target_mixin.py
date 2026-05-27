from __future__ import annotations

from typing import Any

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard import project_target_support
from envctl_engine.ui.dashboard import target_selection_support


class DashboardTargetSelectionMixin:
    def _apply_interactive_target_selection(self, route: Route, state: RunState, rt: object) -> Route | None:
        return target_selection_support.apply_interactive_target_selection(self, route, state, rt)

    def _apply_commit_selection(self, route: Route, state: RunState, rt: object) -> Route | None:
        return project_target_support.apply_commit_selection(self, route, state, rt)

    @staticmethod
    def _dashboard_owned_target_selection_commands() -> set[str]:
        return project_target_support.dashboard_owned_target_selection_commands()

    @staticmethod
    def _dashboard_owned_project_selection_commands() -> set[str]:
        return project_target_support.dashboard_owned_project_selection_commands()

    def _apply_project_target_selection(self, route: Route, state: RunState, rt: object) -> Route | None:
        return project_target_support.apply_project_target_selection(self, route, state, rt)

    def _default_interactive_targets(self, route: Route, state: RunState, rt: object) -> Route:
        return target_selection_support.default_interactive_targets(route, state, rt)

    @staticmethod
    def _route_has_explicit_target(route: Route, runtime: object) -> bool:
        return target_selection_support.route_has_explicit_target(route, runtime)

    @staticmethod
    def _restart_service_types_from_service_names(service_names: list[str]) -> list[str]:
        return target_selection_support.restart_service_types_from_service_names(service_names)

    @staticmethod
    def _service_types_from_service_names(service_names: list[str]) -> set[str]:
        return target_selection_support.service_types_from_service_names(service_names)

    @staticmethod
    def _project_names_from_state(state: RunState, rt: object) -> list[object]:
        return target_selection_support.dashboard_project_names_from_state(state, rt)

    @staticmethod
    def _project_name_list(projects: list[object]) -> list[str]:
        return target_selection_support.project_name_list(projects)

    def _select_dashboard_projects(
        self,
        *,
        command: str,
        state: RunState,
        projects: list[object],
        runtime: Any,
    ) -> list[str] | None:
        return target_selection_support.select_dashboard_projects(
            self,
            command=command,
            state=state,
            projects=projects,
            runtime=runtime,
        )

    @staticmethod
    def _dashboard_preselected_projects(
        *,
        state: RunState,
        projects: list[object],
        runtime: Any,
    ) -> list[str]:
        from envctl_engine.ui.dashboard import orchestrator

        return target_selection_support.dashboard_preselected_projects(
            state=state,
            projects=projects,
            runtime=runtime,
            tree_preselected_projects_fn=orchestrator._tree_preselected_projects_from_state_impl,
        )

    def _select_dashboard_service_types(
        self,
        *,
        command: str,
        state: RunState,
        selected_projects: list[str],
        runtime: Any,
    ) -> list[str] | None:
        return target_selection_support.select_dashboard_service_types(
            self,
            command=command,
            state=state,
            selected_projects=selected_projects,
            runtime=runtime,
        )

    def _select_dashboard_test_scope(
        self,
        *,
        state: RunState,
        selected_projects: list[str],
        runtime: Any,
    ) -> list[str] | None:
        return target_selection_support.select_dashboard_test_scope(
            self,
            state=state,
            selected_projects=selected_projects,
            runtime=runtime,
        )

    @staticmethod
    def _all_tests_scope_available(
        state: RunState,
        runtime: Any,
        *,
        project_names: list[str],
    ) -> bool:
        return target_selection_support.all_tests_scope_available(state, runtime, project_names=project_names)

    @staticmethod
    def _failed_test_scope_available(state: RunState, *, project_names: list[str]) -> bool:
        return target_selection_support.failed_test_scope_available(state, project_names=project_names)

    @staticmethod
    def _available_service_types_for_projects(
        state: RunState,
        runtime: Any,
        *,
        project_names: list[str],
    ) -> list[str]:
        return target_selection_support.available_service_types_for_projects(
            state,
            runtime,
            project_names=project_names,
        )

    @staticmethod
    def _service_names_for_projects_and_types(
        state: RunState,
        runtime: Any,
        *,
        project_names: list[str],
        service_types: list[str],
    ) -> list[str]:
        return target_selection_support.service_names_for_projects_and_types(
            state,
            runtime,
            project_names=project_names,
            service_types=service_types,
        )

    @staticmethod
    def _worktree_prompt(command: str) -> str:
        return target_selection_support.worktree_prompt(command)

    @staticmethod
    def _service_prompt(command: str) -> str:
        return target_selection_support.service_prompt(command)
