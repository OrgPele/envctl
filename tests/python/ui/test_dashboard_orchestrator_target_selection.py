from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator
from envctl_engine.ui.target_selector import TargetSelection

from tests.python.ui.dashboard_orchestrator_test_support import (
    _DashboardOrchestratorTestCase,
    _RuntimeStub,
    _RuntimeStubMissingProjectResolver,
)


class DashboardOrchestratorTargetSelectionTests(_DashboardOrchestratorTestCase):
    def test_interactive_shortcuts_map_to_action_commands(self) -> None:
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
        )
        runtime._latest_state = state

        for raw, expected in (("p", "pr"), ("c", "commit"), ("a", "review"), ("migrations", "migrate")):
            with self.subTest(raw=raw):
                runtime.last_dispatched_route = None
                if raw == "p":
                    orchestrator._run_pr_selection_flow = lambda **kwargs: (
                        runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
                    )  # type: ignore[method-assign]
                    with patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree") as dirty_probe:
                        dirty_probe.return_value = SimpleNamespace(
                            project_name="Main",
                            project_root=Path(runtime.config.base_dir),
                            git_root=Path(runtime.config.base_dir),
                            staged=False,
                            unstaged=False,
                            untracked=False,
                            dirty=False,
                        )
                        should_continue, next_state = orchestrator._run_interactive_command(raw, state, runtime)
                else:
                    should_continue, next_state = orchestrator._run_interactive_command(raw, state, runtime)
                self.assertTrue(should_continue)
                self.assertEqual(next_state.run_id, state.run_id)
                self.assertIsNotNone(runtime.last_dispatched_route)
                assert runtime.last_dispatched_route is not None
                self.assertEqual(runtime.last_dispatched_route.command, expected)

    def test_interactive_test_auto_selects_single_project_in_single_project_mode(self) -> None:
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
        )
        runtime._latest_state = state

        should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertEqual(len(runtime.selection_calls), 0)
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("all")))

    def test_interactive_test_single_project_with_backend_and_frontend_prompts_selector(self) -> None:
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

        should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertEqual(len(runtime.selection_calls), 1)
        self.assertEqual(runtime.selection_calls[0]["prompt"], "Choose test scope")
        self.assertEqual(runtime.selection_calls[0]["projects"], ["Backend", "Frontend"])
        self.assertEqual(runtime.selection_calls[0]["multi"], True)
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])

    def test_interactive_test_single_project_auto_selects_without_selector(self) -> None:
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
        runtime._latest_state = state

        should_continue, _next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(len(runtime.selection_calls), 0)
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
        self.assertFalse(bool(runtime.last_dispatched_route.flags.get("all")))

    def test_interactive_test_cancelled_selector_skips_dispatch_when_multiple_projects(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(cancelled=True)
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
                "Docs Backend": ServiceRecord(
                    name="Docs Backend",
                    type="backend",
                    cwd=".",
                    pid=101,
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
        self.assertEqual(len(runtime.selection_calls), 1)
        self.assertIsNone(runtime.last_dispatched_route)

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

    def test_interactive_test_failure_does_not_replay_duplicate_summary_after_test_suite_block(self) -> None:
        runtime = _RuntimeStub()
        runtime.dispatch_code = 1
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
        runtime._latest_state = state

        def failing_dispatch(route: Route) -> int:
            runtime.last_dispatched_route = route
            runtime._latest_state = RunState(
                run_id="run-1",
                mode="main",
                services=state.services,
                metadata={
                    "project_test_summaries": {
                        "Main": {
                            "summary_path": "/tmp/runtime/test-results/run_1/Main/failed_tests_summary.txt",
                            "short_summary_path": "/tmp/runtime/run_1/ft_deadbeef00.txt",
                            "summary_excerpt": [
                                "[Repository tests (unittest)]",
                                "tests/python/ui/test_selector.py::test_keyboard_burst",
                                "AssertionError: Regex didn't match: 'RESULT_CANCELLED=False'",
                            ],
                            "status": "failed",
                        }
                    }
                },
            )
            return 1

        runtime.dispatch = failing_dispatch  # type: ignore[assignment]

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertNotIn("Command failed (exit 1).", out.getvalue())
        rendered = strip_ansi(out.getvalue())
        self.assertNotIn("Test failure summary for Main:", rendered)
        self.assertNotIn("/tmp/runtime/run_1/ft_deadbeef00.txt", rendered)
        self.assertEqual(
            runtime.read_prompts,
            ["Press Enter to return to dashboard (manual confirmation required): "],
        )

    def test_interactive_test_success_pauses_before_returning_to_dashboard(self) -> None:
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
        runtime._latest_state = state

        should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        self.assertEqual(
            runtime.read_prompts,
            ["Press Enter to return to dashboard (manual confirmation required): "],
        )

    def test_interactive_test_interrupt_returns_to_dashboard_without_failure_summary_block(self) -> None:
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
        runtime._latest_state = state

        def interrupted_dispatch(route: Route) -> int:
            runtime.last_dispatched_route = route
            raise KeyboardInterrupt

        runtime.dispatch = interrupted_dispatch  # type: ignore[assignment]

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command("t", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, "run-1")
        rendered = out.getvalue()
        self.assertNotIn("Command failed (exit 1).", rendered)
        self.assertNotIn("Test failure summary for Main:", rendered)
        self.assertEqual(
            runtime.read_prompts,
            ["Press Enter to return to dashboard (manual confirmation required): "],
        )

