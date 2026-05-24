from __future__ import annotations

from unittest.mock import patch

from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator
from envctl_engine.ui.target_selector import TargetSelection

from tests.python.ui.dashboard_orchestrator_test_support import (
    _DashboardOrchestratorTestCase,
    _RuntimeStub,
)


class DashboardOrchestratorTargetTreesTests(_DashboardOrchestratorTestCase):
    def test_interactive_test_in_trees_prompts_selector_before_dispatch(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selections = [
            TargetSelection(project_names=["feature-a-1"]),
            TargetSelection(project_names=["Backend", "Frontend"]),
        ]
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "feature-a-1 Frontend": ServiceRecord(
                    name="feature-a-1 Frontend",
                    type="frontend",
                    cwd=".",
                    pid=101,
                    requested_port=9000,
                    actual_port=9000,
                    status="running",
                ),
                "feature-b-1 Backend": ServiceRecord(
                    name="feature-b-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=102,
                    requested_port=8010,
                    actual_port=8010,
                    status="running",
                ),
            },
        )
        runtime._latest_state = state

        should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertEqual(len(runtime.selection_calls), 2)
        self.assertEqual(runtime.selection_calls[0]["prompt"], "Choose worktrees to test")
        self.assertEqual(runtime.selection_calls[1]["prompt"], "Choose test scope")
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["feature-a-1"])
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("all")))

    def test_interactive_test_in_trees_preselects_deployed_worktrees(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selections = [
            TargetSelection(project_names=["feature-a-1"]),
            TargetSelection(project_names=["Backend", "Frontend"]),
        ]
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "feature-a-1 Frontend": ServiceRecord(
                    name="feature-a-1 Frontend",
                    type="frontend",
                    cwd=".",
                    pid=101,
                    requested_port=9000,
                    actual_port=9000,
                    status="running",
                ),
                "feature-b-1 Backend": ServiceRecord(
                    name="feature-b-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=102,
                    requested_port=8010,
                    actual_port=8010,
                    status="running",
                ),
            },
        )
        runtime._latest_state = state

        with patch(
            "envctl_engine.ui.dashboard.orchestrator._tree_preselected_projects_from_state_impl",
            return_value=["feature-b-1"],
        ):
            should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertEqual(len(runtime.selection_calls), 2)
        self.assertEqual(runtime.selection_calls[0]["prompt"], "Choose worktrees to test")
        self.assertEqual(runtime.selection_calls[0]["initial_project_names"], ["feature-b-1"])

    def test_interactive_test_in_trees_auto_selects_single_project_before_dispatch(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
            },
        )
        runtime._latest_state = state

        should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertEqual(len(runtime.selection_calls), 0)
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["feature-a-1"])
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("all")))
