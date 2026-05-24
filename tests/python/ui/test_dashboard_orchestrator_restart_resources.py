from __future__ import annotations

from unittest.mock import patch

from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator

from tests.python.ui.dashboard_orchestrator_test_support import (
    _DashboardOrchestratorTestCase,
    _RuntimeStub,
)


class DashboardOrchestratorRestartResourcesTests(_DashboardOrchestratorTestCase):
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
