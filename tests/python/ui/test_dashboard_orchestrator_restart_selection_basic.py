from __future__ import annotations


from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator
from envctl_engine.ui.target_selector import TargetSelection

from tests.python.ui.dashboard_orchestrator_test_support import (
    _DashboardOrchestratorTestCase,
    _RuntimeStub,
)


class DashboardOrchestratorRestartSelectionBasicTests(_DashboardOrchestratorTestCase):
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
