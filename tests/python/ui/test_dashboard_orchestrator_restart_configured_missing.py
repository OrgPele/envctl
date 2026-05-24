from __future__ import annotations

from unittest.mock import patch

from envctl_engine.runtime.command_router import Route
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator

from tests.python.ui.dashboard_orchestrator_test_support import (
    _DashboardOrchestratorTestCase,
    _RuntimeStub,
)


class DashboardOrchestratorRestartConfiguredMissingTests(_DashboardOrchestratorTestCase):
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
        state = self._state_with_active_frontend_and_project_configured_services(
            ["backend", "frontend", "voice-runtime"]
        )
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
