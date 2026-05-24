from __future__ import annotations

from types import SimpleNamespace
import unittest

from envctl_engine.dashboard_metadata import DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard import target_selection_support
from envctl_engine.ui.target_selector import TargetSelection


def _state(**kwargs: object) -> RunState:
    defaults: dict[str, object] = {"run_id": "r1", "mode": "dev", "services": {}, "metadata": {}}
    defaults.update(kwargs)
    return RunState(**defaults)  # type: ignore[arg-type]


class _Owner:
    def __init__(self) -> None:
        self.available_types: list[str] = []
        self.all_tests_available = False
        self.failed_scope_available = False
        self.projects = [SimpleNamespace(name="Main")]
        self.review_launch_routes: list[Route] = []

    @staticmethod
    def _apply_pr_selection(route: Route, _state: RunState, _runtime: object) -> Route | None:
        return route

    @staticmethod
    def _apply_commit_selection(route: Route, _state: RunState, _runtime: object) -> Route | None:
        return route

    @staticmethod
    def _dashboard_owned_target_selection_commands() -> set[str]:
        return {"test", "pr", "commit", "review", "migrate", "blast-worktree"}

    @staticmethod
    def _dashboard_owned_project_selection_commands() -> set[str]:
        return {"pr", "commit", "review", "migrate", "blast-worktree"}

    def _apply_project_target_selection(self, route: Route, _state: RunState, _runtime: object) -> Route | None:
        route.projects = ["Main"]
        return route

    def _apply_review_tab_launch_selection(self, route: Route, _state: RunState, _runtime: object) -> Route:
        self.review_launch_routes.append(route)
        route.flags = {**route.flags, "dashboard_review_tab_launch": True}
        return route

    @staticmethod
    def _route_has_explicit_target(route: Route, runtime: object) -> bool:
        return target_selection_support.route_has_explicit_target(route, runtime)

    def _project_names_from_state(self, _state: RunState, _runtime: object) -> list[object]:
        return list(self.projects)

    @staticmethod
    def _project_name_list(projects: list[object]) -> list[str]:
        return target_selection_support.project_name_list(projects)

    @staticmethod
    def _single_project_name(projects: list[object]) -> str:
        names = target_selection_support.project_name_list(projects)
        return names[0] if len(names) == 1 else ""

    @staticmethod
    def _dashboard_preselected_projects(
        *,
        state: RunState,
        projects: list[object],
        runtime: object,
    ) -> list[str]:
        return target_selection_support.dashboard_preselected_projects(
            state=state,
            projects=projects,
            runtime=runtime,
        )

    @staticmethod
    def _worktree_prompt(command: str) -> str:
        return target_selection_support.worktree_prompt(command)

    @staticmethod
    def _service_prompt(command: str) -> str:
        return target_selection_support.service_prompt(command)

    def _available_service_types_for_projects(
        self,
        _state: RunState,
        _runtime: object,
        *,
        project_names: list[str],
    ) -> list[str]:
        _ = project_names
        return list(self.available_types)

    def _all_tests_scope_available(
        self,
        _state: RunState,
        _runtime: object,
        *,
        project_names: list[str],
    ) -> bool:
        _ = project_names
        return self.all_tests_available

    def _failed_test_scope_available(self, _state: RunState, *, project_names: list[str]) -> bool:
        _ = project_names
        return self.failed_scope_available

    def _select_dashboard_test_scope(
        self,
        *,
        state: RunState,
        selected_projects: list[str],
        runtime: object,
    ) -> list[str] | None:
        return target_selection_support.select_dashboard_test_scope(
            self,
            state=state,
            selected_projects=selected_projects,
            runtime=runtime,
        )

    def _select_dashboard_projects(
        self,
        *,
        command: str,
        state: RunState,
        projects: list[object],
        runtime: object,
    ) -> list[str] | None:
        return target_selection_support.select_dashboard_projects(
            self,
            command=command,
            state=state,
            projects=projects,
            runtime=runtime,
        )

    def _select_dashboard_service_types(
        self,
        *,
        command: str,
        state: RunState,
        selected_projects: list[str],
        runtime: object,
    ) -> list[str] | None:
        return target_selection_support.select_dashboard_service_types(
            self,
            command=command,
            state=state,
            selected_projects=selected_projects,
            runtime=runtime,
        )

    @staticmethod
    def _service_names_for_projects_and_types(
        state: RunState,
        runtime: object,
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
    def _no_target_selected_message(command: str) -> str:
        return target_selection_support.no_target_selected_message(command)


class _Runtime:
    def __init__(self, selection: list[str] | None = None) -> None:
        self.events: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.selection = selection or []
        self.next_selections: list[TargetSelection] = []
        self.selection_calls: list[dict[str, object]] = []

    def _emit(self, *args: object, **kwargs: object) -> None:
        self.events.append((args, kwargs))

    def _select_project_targets(self, **kwargs: object) -> SimpleNamespace:
        self.selection_calls.append(kwargs)
        if self.next_selections:
            return self.next_selections.pop(0)
        return SimpleNamespace(cancelled=False, project_names=list(self.selection))

    @staticmethod
    def _project_name_from_service(service_name: str) -> str:
        return service_name.split()[0]


class DashboardTargetSelectionSupportTests(unittest.TestCase):
    def test_select_dashboard_projects_defaults_single_project_without_selector(self) -> None:
        runtime = _Runtime()
        owner = _Owner()

        result = target_selection_support.select_dashboard_projects(
            owner,
            command="restart",
            state=_state(),
            projects=[SimpleNamespace(name="Main")],
            runtime=runtime,
        )

        self.assertEqual(result, ["Main"])
        self.assertEqual(runtime.selection_calls, [])
        self.assertEqual(runtime.events[0][0], ("dashboard.target_scope.defaulted",))

    def test_select_dashboard_test_scope_prefers_failed_scope_when_selected(self) -> None:
        runtime = _Runtime(selection=["Failed tests"])
        owner = _Owner()
        owner.available_types = ["backend", "frontend"]
        owner.failed_scope_available = True

        result = target_selection_support.select_dashboard_test_scope(
            owner,
            state=_state(),
            selected_projects=["Main"],
            runtime=runtime,
        )

        self.assertEqual(result, ["failed"])
        self.assertEqual(runtime.selection_calls[0]["exclusive_project_name"], "Failed tests")

    def test_available_service_types_merges_state_and_configured_metadata(self) -> None:
        state = _state(
            services={
                "Main Backend": SimpleNamespace(name="Main Backend", project="Main", type="backend"),
            },
            metadata={
                DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY: {
                    "Main": ["frontend"],
                    "Other": ["backend"],
                },
            },
        )

        result = target_selection_support.available_service_types_for_projects(
            state,
            _Runtime(),
            project_names=["Main"],
        )

        self.assertEqual(result, ["backend", "frontend"])

    def test_restart_service_type_parsing_preserves_order_and_dedupes(self) -> None:
        result = target_selection_support.restart_service_types_from_service_names(
            ["Main Frontend", "service:backend", "Main Backend", "Main Frontend"]
        )

        self.assertEqual(result, ["frontend", "backend"])

    def test_apply_interactive_target_selection_scopes_test_to_selected_services(self) -> None:
        owner = _Owner()
        owner.projects = [SimpleNamespace(name="Main"), SimpleNamespace(name="Other")]
        owner.available_types = ["backend", "frontend"]
        runtime = _Runtime()
        runtime.next_selections = [
            TargetSelection(project_names=["Main"]),
            TargetSelection(project_names=["Backend"]),
        ]
        state = _state(
            services={
                "Main Backend": SimpleNamespace(name="Main Backend", project="Main", type="backend"),
                "Main Frontend": SimpleNamespace(name="Main Frontend", project="Main", type="frontend"),
            }
        )
        route = Route(command="test", mode="trees", flags={"interactive_command": True})

        result = target_selection_support.apply_interactive_target_selection(owner, route, state, runtime)

        self.assertIs(result, route)
        self.assertEqual(route.projects, ["Main"])
        self.assertEqual(
            route.flags,
            {"interactive_command": True, "services": ["Main Backend"], "backend": True, "frontend": False},
        )

    def test_apply_interactive_target_selection_uses_failed_test_scope_without_services(self) -> None:
        owner = _Owner()
        owner.projects = [SimpleNamespace(name="Main"), SimpleNamespace(name="Other")]
        owner.available_types = ["backend", "frontend"]
        owner.failed_scope_available = True
        runtime = _Runtime()
        runtime.next_selections = [
            TargetSelection(project_names=["Main"]),
            TargetSelection(project_names=["Failed tests"]),
        ]
        route = Route(command="test", mode="trees", flags={"interactive_command": True})

        result = target_selection_support.apply_interactive_target_selection(owner, route, _state(), runtime)

        self.assertIs(result, route)
        self.assertEqual(route.projects, ["Main"])
        self.assertEqual(route.flags, {"interactive_command": True, "failed": True})

    def test_apply_interactive_target_selection_delegates_review_project_and_tab_selection(self) -> None:
        owner = _Owner()
        route = Route(command="review", mode="trees")

        result = target_selection_support.apply_interactive_target_selection(owner, route, _state(), _Runtime())

        self.assertIs(result, route)
        self.assertEqual(route.projects, ["Main"])
        self.assertTrue(route.flags["dashboard_review_tab_launch"])
        self.assertEqual(owner.review_launch_routes, [route])


if __name__ == "__main__":
    unittest.main()
