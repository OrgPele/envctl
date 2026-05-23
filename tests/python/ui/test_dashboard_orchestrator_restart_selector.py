from __future__ import annotations

from unittest.mock import patch

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator
from envctl_engine.ui.target_selector import TargetSelection

from tests.python.ui.dashboard_orchestrator_test_support import (
    _DashboardOrchestratorTestCase,
    _RuntimeStub,
)


class DashboardOrchestratorRestartSelectorTests(_DashboardOrchestratorTestCase):
    def test_restart_selector_uses_runtime_backend_selection(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
        )
        route = Route(
            command="restart", mode="main", raw_args=["--restart"], passthrough_args=[], projects=[], flags={}
        )
        updated = orchestrator._apply_restart_selection(route, state, runtime)

        self.assertIsNotNone(updated)
        self.assertEqual(runtime.selection_calls, [])
        assert updated is not None
        self.assertEqual(updated.projects, ["Main"])

    def test_restart_selector_does_not_flush_pending_input_for_interactive_command(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
        )
        route = Route(
            command="restart",
            mode="main",
            raw_args=["restart"],
            passthrough_args=[],
            projects=[],
            flags={"interactive_command": True},
        )

        updated = orchestrator._apply_restart_selection(route, state, runtime)

        self.assertIsNotNone(updated)
        self.assertEqual(len(runtime.selection_calls), 0)

    def test_restart_selector_skips_prompt_when_all_already_selected(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
        )
        route = Route(
            command="restart",
            mode="main",
            raw_args=["restart", "--all"],
            passthrough_args=[],
            projects=[],
            flags={"all": True, "interactive_command": True},
        )

        updated = orchestrator._apply_restart_selection(route, state, runtime)

        self.assertIsNotNone(updated)
        self.assertEqual(runtime.selection_calls, [])

    def test_interactive_restart_prompts_selector_for_single_project(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Backend", "Frontend"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "Main Frontend": ServiceRecord(
                    name="Main Frontend",
                    type="frontend",
                    cwd=".",
                    pid=101,
                    requested_port=9000,
                    actual_port=9000,
                    status="running",
                ),
            },
        )
        runtime._latest_state = state

        should_continue, next_state = orchestrator._run_interactive_command("r", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertEqual(len(runtime.selection_calls), 1)
        self.assertEqual(runtime.selection_calls[0]["prompt"], "Choose services")
        self.assertEqual(runtime.selection_calls[0]["projects"], ["Backend", "Frontend"])
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("all")))
        self.assertTrue(bool(runtime.last_dispatched_route.flags.get("restart_include_requirements")))

    def test_restart_selector_marks_full_restart_when_all_selected(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Backend", "Frontend"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "Main Frontend": ServiceRecord(
                    name="Main Frontend",
                    type="frontend",
                    cwd=".",
                    pid=101,
                    requested_port=9000,
                    actual_port=9000,
                    status="running",
                ),
            },
        )
        route = Route(
            command="restart",
            mode="main",
            raw_args=["restart"],
            passthrough_args=[],
            projects=[],
            flags={"interactive_command": True},
        )
        updated = orchestrator._apply_restart_selection(route, state, runtime)

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.projects, ["Main"])
        self.assertFalse(bool(updated.flags.get("all")))
        self.assertTrue(bool(updated.flags.get("restart_include_requirements")))

    def test_restart_selector_service_selection_restarts_selected_service_only(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Backend"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "Main Frontend": ServiceRecord(
                    name="Main Frontend",
                    type="frontend",
                    cwd=".",
                    pid=101,
                    requested_port=9000,
                    actual_port=9000,
                    status="running",
                ),
            },
        )
        route = Route(
            command="restart",
            mode="main",
            raw_args=["restart"],
            passthrough_args=[],
            projects=[],
            flags={"interactive_command": True},
        )
        updated = orchestrator._apply_restart_selection(route, state, runtime)

        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.projects, ["Main"])
        self.assertEqual(updated.flags.get("services"), ["Main Backend"])
        self.assertEqual(updated.flags.get("restart_service_types"), ["backend"])
        self.assertFalse(bool(updated.flags.get("restart_include_requirements")))

    def test_interactive_restart_can_start_stopped_service_from_resource_selector(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
            },
            requirements={"Main": RequirementsResult(project="Main", db={"enabled": True, "final": 5432})},
            metadata={
                "dashboard_stopped_services": [
                    {"name": "Main Frontend", "project": "Main", "type": "frontend"},
                ],
                "dashboard_configured_service_types": ["backend", "frontend"],
            },
        )
        runtime._latest_state = state
        selector_calls: list[dict[str, object]] = []

        def fake_restart_selector(**kwargs: object) -> list[str]:
            selector_calls.append(kwargs)
            return ["__RESTART__:service:Main Frontend"]

        with patch(
            "envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl",
            side_effect=fake_restart_selector,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("r", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.selection_calls, [])
        self.assertEqual(len(selector_calls), 1)
        self.assertIn("a selects all", selector_calls[0]["prompt"])
        labels = [item.label for item in selector_calls[0]["options"]]
        self.assertIn("All resources — apps + dependencies", labels)
        self.assertIn("Backend — Main", labels)
        self.assertIn("Frontend — Main (stopped)", labels)
        self.assertIn("postgres", labels)
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.command, "restart")
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("services"), ["Main Frontend"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("restart_service_types"), ["frontend"])
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("restart_include_requirements")))

    def test_interactive_restart_offers_running_dependencies_even_without_stopped_services(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "Main Frontend": ServiceRecord(
                    name="Main Frontend",
                    type="frontend",
                    cwd=".",
                    pid=101,
                    requested_port=9000,
                    actual_port=9000,
                    status="running",
                ),
            },
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    redis={"enabled": True, "runtime_status": "healthy", "final": 6379, "success": True},
                    n8n={"enabled": True, "runtime_status": "healthy", "final": 5678, "success": True},
                )
            },
        )
        runtime._latest_state = state
        selector_calls: list[dict[str, object]] = []

        def fake_restart_selector(**kwargs: object) -> list[str]:
            selector_calls.append(kwargs)
            return ["__RESTART__:dependency:Main:redis"]

        with patch(
            "envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl",
            side_effect=fake_restart_selector,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("r", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.selection_calls, [])
        labels = [item.label for item in selector_calls[0]["options"]]
        self.assertIn("redis", labels)
        self.assertIn("n8n", labels)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("services"), [])
        self.assertEqual(runtime.last_dispatched_route.flags.get("restart_service_types"), [])
        self.assertTrue(runtime.last_dispatched_route.flags.get("restart_include_requirements"))

    def test_interactive_restart_offers_project_configured_missing_backend(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = self._state_with_active_frontend_and_project_configured_services(["backend", "frontend"])
        runtime._latest_state = state
        selector_calls: list[dict[str, object]] = []

        def fake_restart_selector(**kwargs: object) -> list[str]:
            selector_calls.append(kwargs)
            return ["__RESTART__:service:Main Backend"]

        with patch(
            "envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl",
            side_effect=fake_restart_selector,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("r", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.selection_calls, [])
        self.assertEqual(len(selector_calls), 1)
        labels = [item.label for item in selector_calls[0]["options"]]
        self.assertIn("Backend — Main (stopped)", labels)
        self.assertIn("Frontend — Main", labels)
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.command, "restart")
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("services"), ["Main Backend"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("restart_service_types"), ["backend"])
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("restart_include_requirements")))

    def test_interactive_restart_does_not_offer_unconfigured_missing_backend(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = self._state_with_active_frontend_and_project_configured_services(["frontend"])
        route = Route(command="restart", mode="main", raw_args=["restart"], passthrough_args=[], projects=[], flags={})

        updated = orchestrator._apply_restart_selection(route, state, runtime)

        self.assertIsNotNone(updated)
        self.assertNotIn("Main Backend", updated.flags.get("services", []))  # type: ignore[union-attr]

    def test_restart_services_merges_configured_missing_and_stopped_services_without_duplicates(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = self._state_with_active_frontend_and_project_configured_services(
            ["backend", "frontend"],
            stopped_services=[
                {"name": "Main Backend", "project": "Main", "type": "backend"},
            ],
        )

        self.assertEqual(
            orchestrator._restart_services_by_project(state, runtime),
            {"Main": [("Main Backend", "backend", True), ("Main Frontend", "frontend", False)]},
        )

    def test_restart_selector_offers_configured_missing_additional_service(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = self._state_with_active_frontend_and_project_configured_services(["backend", "frontend", "voice-runtime"])
        runtime._latest_state = state
        selector_calls: list[dict[str, object]] = []

        def fake_restart_selector(**kwargs: object) -> list[str]:
            selector_calls.append(kwargs)
            return ["__RESTART__:service:Main Voice Runtime"]

        with patch(
            "envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl",
            side_effect=fake_restart_selector,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("r", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        labels = [item.label for item in selector_calls[0]["options"]]
        self.assertIn("Voice Runtime — Main (stopped)", labels)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("services"), ["Main Voice Runtime"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("restart_service_types"), ["voice-runtime"])

    def test_restart_selector_uses_service_record_project_for_active_additional_service(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        project_name = "refactoring_app_bootstrap_performance_redesign-1"
        state = RunState(
            run_id="run-trees",
            mode="trees",
            services={
                f"{project_name} Voice Runtime": ServiceRecord(
                    name=f"{project_name} Voice Runtime",
                    type="voice-runtime",
                    cwd=".",
                    pid=101,
                    requested_port=8117,
                    actual_port=8117,
                    status="running",
                    project=project_name,
                    service_slug="voice-runtime",
                ),
            },
            requirements={
                project_name: RequirementsResult(
                    project=project_name,
                    redis={"enabled": True, "success": True, "final": 6485},
                ),
            },
            metadata={"project_roots": {project_name: "."}},
        )
        runtime._latest_state = state

        with patch(
            "envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl",
            return_value=[f"__RESTART__:service:{project_name} Voice Runtime"],
        ):
            should_continue, next_state = orchestrator._run_interactive_command("r", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, [project_name])
        self.assertEqual(runtime.last_dispatched_route.flags.get("services"), [f"{project_name} Voice Runtime"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("restart_service_types"), ["voice-runtime"])

    def test_service_names_for_projects_and_types_filters_configured_missing_services(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = self._state_with_active_frontend_and_project_configured_services(["backend", "frontend"])

        self.assertEqual(
            orchestrator._service_names_for_projects_and_types(
                state,
                runtime,
                project_names=["Main"],
                service_types=["backend"],
            ),
            ["Main Backend"],
        )
        self.assertEqual(
            orchestrator._service_names_for_projects_and_types(
                state,
                runtime,
                project_names=["Other"],
                service_types=["backend", "frontend"],
            ),
            [],
        )

    def test_configured_missing_restart_event_is_emitted_only_when_missing_services_exist(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        events: list[tuple[str, dict[str, object]]] = []
        runtime._emit = lambda event, **payload: events.append((event, payload))  # type: ignore[method-assign]

        configured_state = self._state_with_active_frontend_and_project_configured_services(["backend", "frontend"])
        orchestrator._restart_services_by_project(configured_state, runtime)
        self.assertEqual(
            events,
            [
                (
                    "dashboard.restart.configured_missing_offered",
                    {
                        "run_id": "run-1",
                        "services": {"Main": ["backend"]},
                        "metadata_key": "dashboard_project_configured_services",
                    },
                )
            ],
        )

        events.clear()
        frontend_only_state = self._state_with_active_frontend_and_project_configured_services(["frontend"])
        orchestrator._restart_services_by_project(frontend_only_state, runtime)
        self.assertEqual(events, [])

