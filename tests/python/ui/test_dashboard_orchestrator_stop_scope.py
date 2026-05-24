from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator
from envctl_engine.ui.target_selector import TargetSelection

from tests.python.ui.dashboard_orchestrator_test_support import (
    _DashboardOrchestratorTestCase,
    _RuntimeStub,
)


class DashboardOrchestratorStopScopeTests(_DashboardOrchestratorTestCase):
    def test_interactive_stop_shortcut_opens_scope_selector(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Dependencies only"])
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
            requirements={"Main": RequirementsResult(project="Main", db={"enabled": True, "final": 5432})},
        )
        runtime._latest_state = state

        selector_calls: list[dict[str, object]] = []

        def fake_stop_selector(**kwargs):  # noqa: ANN001
            selector_calls.append(kwargs)
            return ["__STOP__:dependency:Main:postgres"]

        out = StringIO()
        with redirect_stdout(out), patch(
            "envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl",
            side_effect=fake_stop_selector,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("s", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.selection_calls, [])
        self.assertEqual(len(selector_calls), 1)
        self.assertIn("a selects all", selector_calls[0]["prompt"])
        self.assertTrue(selector_calls[0]["multi"])
        self.assertNotIn("exclusive_token", selector_calls[0])
        labels = [item.label for item in selector_calls[0]["options"]]
        self.assertIn("All resources — apps + dependencies", labels)
        self.assertIn("Backend — Main", labels)
        self.assertIn("Frontend — Main", labels)
        self.assertIn("postgres", labels)
        self.assertNotIn("Custom services/projects...", labels)
        sections = [item.section for item in selector_calls[0]["options"]]
        self.assertIn("Resources", sections)
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.command, "stop")
        self.assertEqual(runtime.last_dispatched_route.flags.get("stop_dependency_components"), ["Main:postgres"])
        self.assertTrue(runtime.last_dispatched_route.flags.get("stop_preserve_requirements"))
        self.assertNotIn("attach:", out.getvalue())

    def test_interactive_stop_groups_resources_by_worktree_when_multiple_projects_exist(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=100),
                "Feature Frontend": ServiceRecord(name="Feature Frontend", type="frontend", cwd=".", pid=101),
            },
            requirements={
                "Main": RequirementsResult(project="Main", db={"enabled": True, "final": 5432}),
                "Feature": RequirementsResult(project="Feature", redis={"enabled": True, "final": 6379}),
            },
        )
        runtime._latest_state = state
        selector_calls: list[dict[str, object]] = []

        def fake_stop_selector(**kwargs):  # noqa: ANN001
            selector_calls.append(kwargs)
            return ["__STOP__:worktree:Feature"]

        with patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", side_effect=fake_stop_selector):
            should_continue, next_state = orchestrator._run_interactive_command("s", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(len(selector_calls), 1)
        options = selector_calls[0]["options"]
        labels = [item.label for item in options]
        sections = [item.section for item in options]
        self.assertIn("▸ Main", sections)
        self.assertIn("▸ Feature", sections)
        self.assertIn("▸ Feature — entire worktree (apps + dependencies)", labels)
        self.assertIn("  ↳ Frontend — Feature Frontend", labels)
        self.assertIn("  ↳ redis", labels)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.flags.get("services"), ["Feature Frontend"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("stop_dependency_components"), ["Feature:redis"])
        self.assertTrue(runtime.last_dispatched_route.flags.get("stop_preserve_requirements"))

    def test_interactive_stop_all_resources_row_selects_all_single_worktree_services(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=100),
                "Main Frontend": ServiceRecord(name="Main Frontend", type="frontend", cwd=".", pid=101),
            },
        )
        runtime._latest_state = state
        selector_calls: list[dict[str, object]] = []

        def fake_stop_selector(**kwargs):  # noqa: ANN001
            selector_calls.append(kwargs)
            return ["__STOP__:worktree:Main"]

        with patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", side_effect=fake_stop_selector):
            should_continue, next_state = orchestrator._run_interactive_command("s", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        labels = [item.label for item in selector_calls[0]["options"]]
        self.assertIn("All resources — apps + dependencies", labels)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.flags.get("services"), ["Main Backend", "Main Frontend"])
        self.assertTrue(runtime.last_dispatched_route.flags.get("stop_preserve_requirements"))

    def test_interactive_sessions_word_points_to_inline_dashboard_rows(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(run_id="run-1", mode="main")
        runtime._latest_state = state

        out = StringIO()
        with (
            redirect_stdout(out),
            patch(
                "envctl_engine.runtime.session_management.list_tmux_sessions",
                side_effect=AssertionError("sessions command should not list tmux sessions"),
            ),
        ):
            should_continue, next_state = orchestrator._run_interactive_command("sessions", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.selection_calls, [])
        self.assertIsNone(runtime.last_dispatched_route)
        self.assertIn("shown inline", out.getvalue())
        self.assertNotIn("attach:", out.getvalue())

    def test_interactive_kill_word_kills_ai_sessions_not_services(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=100),
            },
        )
        runtime._latest_state = state

        out = StringIO()
        with (
            redirect_stdout(out),
            patch(
                "envctl_engine.runtime.session_management.list_tmux_sessions",
                return_value=[
                    {
                        "name": "omx-main",
                        "windows": "sh",
                        "attach": "tmux attach-session -t omx-main",
                        "kill": "tmux kill-session -t omx-main",
                    }
                ],
            ),
            patch("envctl_engine.runtime.session_management.kill_session", return_value=True) as kill_session,
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["omx-main"]),
        ):
            should_continue, next_state = orchestrator._run_interactive_command("kill", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertIsNone(runtime.last_dispatched_route)
        kill_session.assert_called_once_with("omx-main")
        self.assertIn("Killing: omx-main", out.getvalue())

    def test_hidden_dashboard_command_is_rejected_without_dispatch(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-plan",
            mode="trees",
            metadata={"dashboard_hidden_commands": ["restart"]},
        )
        runtime._latest_state = state

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command("r", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertIsNone(runtime.last_dispatched_route)
        self.assertIn("Command 'restart' is not available in this dashboard", out.getvalue())

    def test_migrate_is_rejected_when_nothing_is_running(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(run_id="run-plan", mode="trees")
        runtime._latest_state = state

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command("m", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertIsNone(runtime.last_dispatched_route)
        self.assertIn("Command 'migrate' is not available in this dashboard", out.getvalue())

    def test_install_prompts_is_rejected_in_dashboard_context(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(run_id="run-plan", mode="trees")
        runtime._latest_state = state

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command(
                "install-prompts --cli codex --dry-run",
                state,
                runtime,
            )

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertIsNone(runtime.last_dispatched_route)
        self.assertIn("Command 'install-prompts' is not available in this dashboard context.", out.getvalue())

