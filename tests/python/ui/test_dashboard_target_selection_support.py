from __future__ import annotations

from types import SimpleNamespace
import unittest

from envctl_engine.dashboard_metadata import DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY
from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard import target_selection_support


def _state(**kwargs: object) -> RunState:
    defaults: dict[str, object] = {"run_id": "r1", "mode": "dev", "services": {}, "metadata": {}}
    defaults.update(kwargs)
    return RunState(**defaults)  # type: ignore[arg-type]


class _Owner:
    def __init__(self) -> None:
        self.available_types: list[str] = []
        self.all_tests_available = False
        self.failed_scope_available = False

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


class _Runtime:
    def __init__(self, selection: list[str] | None = None) -> None:
        self.events: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.selection = selection or []
        self.selection_calls: list[dict[str, object]] = []

    def _emit(self, *args: object, **kwargs: object) -> None:
        self.events.append((args, kwargs))

    def _select_project_targets(self, **kwargs: object) -> SimpleNamespace:
        self.selection_calls.append(kwargs)
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


if __name__ == "__main__":
    unittest.main()
