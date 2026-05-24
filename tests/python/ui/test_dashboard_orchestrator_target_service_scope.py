from __future__ import annotations


from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator
from envctl_engine.ui.target_selector import TargetSelection

from tests.python.ui.dashboard_orchestrator_test_support import (
    _DashboardOrchestratorTestCase,
    _RuntimeStub,
    _RuntimeStubMissingProjectResolver,
)


class DashboardOrchestratorTargetServiceScopeTests(_DashboardOrchestratorTestCase):
    def test_interactive_test_service_selection_limits_backend_frontend_flags(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selections = [
            TargetSelection(project_names=["feature-a-1"]),
            TargetSelection(project_names=["Frontend"]),
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
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["feature-a-1"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("services"), ["feature-a-1 Frontend"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("backend"), False)
        self.assertEqual(runtime.last_dispatched_route.flags.get("frontend"), True)

    def test_interactive_test_service_selection_offers_failed_rerun_when_saved_failures_exist(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Failed tests"])
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
            metadata={
                "project_test_summaries": {
                    "Main": {
                        "manifest_path": "/tmp/runtime/Main_failed_tests_manifest.json",
                        "failed_tests": 2,
                        "status": "failed",
                    }
                }
            },
        )
        runtime._latest_state = state

        should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertEqual(runtime.selection_calls[0]["projects"], ["Backend", "Frontend", "Failed tests"])
        self.assertEqual(runtime.selection_calls[0]["multi"], True)
        self.assertEqual(runtime.selection_calls[0]["exclusive_project_name"], "Failed tests")
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertTrue(bool(runtime.last_dispatched_route.flags.get("failed")))
        self.assertNotIn("services", runtime.last_dispatched_route.flags)
        self.assertNotIn("backend", runtime.last_dispatched_route.flags)
        self.assertNotIn("frontend", runtime.last_dispatched_route.flags)

    def test_interactive_test_service_selection_hides_failed_rerun_without_saved_failures(self) -> None:
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

        should_continue, _next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(runtime.selection_calls[0]["projects"], ["Backend", "Frontend"])
        self.assertEqual(runtime.selection_calls[0]["multi"], True)
        self.assertIsNone(runtime.selection_calls[0]["exclusive_project_name"])

    def test_interactive_test_service_selection_hides_failed_rerun_when_latest_status_passed(
        self,
    ) -> None:
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
            metadata={
                "project_test_summaries": {
                    "Main": {
                        "manifest_path": "/tmp/runtime/Main_failed_tests_manifest.json",
                        "short_summary_path": "/tmp/runtime/ft_deadbeef00.txt",
                        "failed_tests": 0,
                        "failed_manifest_entries": 0,
                        "status": "passed",
                    }
                }
            },
        )
        runtime._latest_state = state

        should_continue, _next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(runtime.selection_calls[0]["projects"], ["Backend", "Frontend"])
        self.assertEqual(runtime.selection_calls[0]["multi"], True)
        self.assertIsNone(runtime.selection_calls[0]["exclusive_project_name"])

    def test_interactive_test_service_selection_falls_back_to_service_name_parsing(self) -> None:
        runtime = _RuntimeStubMissingProjectResolver()
        runtime.next_selection = TargetSelection(project_names=["Failed tests"])
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
            metadata={
                "project_test_summaries": {
                    "Main": {
                        "manifest_path": "/tmp/runtime/Main_failed_tests_manifest.json",
                        "failed_tests": 2,
                        "status": "failed",
                    }
                }
            },
        )
        runtime._latest_state = state

        should_continue, _next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(runtime.selection_calls[0]["projects"], ["Backend", "Frontend", "Failed tests"])
        self.assertEqual(runtime.selection_calls[0]["multi"], True)
        self.assertEqual(runtime.selection_calls[0]["exclusive_project_name"], "Failed tests")

    def test_interactive_test_service_selection_uses_configured_service_types_when_services_not_running(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Failed tests"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={},
            metadata={
                "dashboard_configured_service_types": ["backend", "frontend"],
                "project_roots": {"Main": "."},
                "project_test_summaries": {
                    "Main": {
                        "manifest_path": "/tmp/runtime/Main_failed_tests_manifest.json",
                        "failed_tests": 2,
                        "status": "failed",
                    }
                },
            },
        )
        runtime._latest_state = state

        should_continue, _next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(runtime.selection_calls[0]["projects"], ["Backend", "Frontend", "Failed tests"])
        self.assertEqual(runtime.selection_calls[0]["multi"], True)
        self.assertEqual(runtime.selection_calls[0]["exclusive_project_name"], "Failed tests")

    def test_interactive_test_service_selection_offers_failed_rerun_when_status_failed_but_count_zero(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Failed tests"])
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
            metadata={
                "project_test_summaries": {
                    "Main": {
                        "manifest_path": "/tmp/runtime/Main_failed_tests_manifest.json",
                        "failed_tests": 0,
                        "failed_manifest_entries": 0,
                        "status": "failed",
                    }
                }
            },
        )
        runtime._latest_state = state

        should_continue, _next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(runtime.selection_calls[0]["projects"], ["Backend", "Frontend", "Failed tests"])
        self.assertEqual(runtime.selection_calls[0]["multi"], True)
        self.assertEqual(runtime.selection_calls[0]["exclusive_project_name"], "Failed tests")
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertTrue(bool(runtime.last_dispatched_route.flags.get("failed")))

    def test_interactive_test_service_selection_offers_all_tests_when_only_root_suite_exists(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Backend", "Frontend"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={},
            metadata={
                "project_roots": {"Main": "."},
                "project_test_summaries": {
                    "Main": {
                        "manifest_path": "/tmp/runtime/Main_failed_tests_manifest.json",
                        "failed_tests": 2,
                        "status": "failed",
                    }
                },
            },
        )
        runtime._latest_state = state

        should_continue, _next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(runtime.selection_calls[0]["projects"], ["All tests", "Failed tests"])
        self.assertEqual(runtime.selection_calls[0]["multi"], True)
        self.assertEqual(runtime.selection_calls[0]["exclusive_project_name"], "Failed tests")
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertNotIn("services", runtime.last_dispatched_route.flags)
        self.assertNotIn("backend", runtime.last_dispatched_route.flags)
        self.assertNotIn("frontend", runtime.last_dispatched_route.flags)
        self.assertNotIn("failed", runtime.last_dispatched_route.flags)
