# ruff: noqa: F401
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator
from envctl_engine.ui.dashboard.pr_flow import PrFlowResult
from envctl_engine.ui.target_selector import TargetSelection

from tests.python.ui.dashboard_orchestrator_test_support import (
    _DashboardOrchestratorTestCase,
    _RuntimeStub,
    _TtyStringIO,
)


class DashboardOrchestratorPrFlowSelectionTests(_DashboardOrchestratorTestCase):
    def test_pr_interactive_flow_prompts_for_target_before_base_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Envctl Tests"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo, check=True)
            (repo / "README.md").write_text("test\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
            subprocess.run(["git", "branch", "release/2026-03-10"], cwd=repo, check=True)
            runtime = _RuntimeStub(base_dir=repo)
            orchestrator = DashboardOrchestrator(runtime)
            runtime.next_pr_flow_result = PrFlowResult(project_names=["Main"], base_branch="main")
            state = RunState(
                run_id="run-pr",
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
            orchestrator._run_pr_selection_flow = lambda **kwargs: (
                runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
            )  # type: ignore[method-assign]

            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

            self.assertTrue(should_continue)
            self.assertIs(next_state, state)
            self.assertEqual(len(runtime.pr_flow_calls), 1)
            self.assertEqual(runtime.pr_flow_calls[0]["default_branch"], "main")

    def test_pr_interactive_flow_uses_entered_base_branch_after_target_selection(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        runtime.next_pr_flow_result = PrFlowResult(project_names=["Main"], base_branch="release/2026-03-10")
        state = RunState(
            run_id="run-pr-feature",
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
            should_continue, _next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(len(runtime.pr_flow_calls), 1)
        self.assertEqual(runtime.read_prompts, [])
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.flags.get("pr_base"), "release/2026-03-10")

    def test_pr_interactive_flow_cancels_when_no_base_branch_is_selected(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        runtime.next_pr_flow_result = PrFlowResult(
            project_names=["Main"],
            base_branch=None,
            cancelled=True,
            cancelled_step="branch",
        )
        state = RunState(
            run_id="run-pr-cancelled",
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
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]

        out = StringIO()
        with redirect_stdout(out):
            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertIsNone(runtime.last_dispatched_route)
        self.assertIn("No PR base branch selected.", out.getvalue())

    def test_project_scoped_commands_auto_select_single_project(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Main"])
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

        for raw in ("p", "c", "a", "m"):
            with self.subTest(raw=raw):
                runtime.selection_calls.clear()
                runtime.pr_flow_calls.clear()
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
                self.assertEqual(len(runtime.selection_calls), 0)
                if raw == "p":
                    self.assertEqual(len(runtime.pr_flow_calls), 1)
                    self.assertEqual(runtime.pr_flow_calls[0]["initial_project_names"], ["Main"])
                else:
                    self.assertEqual(len(runtime.pr_flow_calls), 0)
                self.assertIsNotNone(runtime.last_dispatched_route)
                assert runtime.last_dispatched_route is not None
                self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
                self.assertIsNone(runtime.last_dispatched_route.flags.get("services"))

    def test_project_scoped_commands_use_project_selector_when_multiple_projects_exist(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["Feature A"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "Feature A Backend": ServiceRecord(
                    name="Feature A Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "Feature B Backend": ServiceRecord(
                    name="Feature B Backend",
                    type="backend",
                    cwd=".",
                    pid=101,
                    requested_port=8001,
                    actual_port=8001,
                    status="running",
                ),
            },
        )
        runtime._latest_state = state

        should_continue, next_state = orchestrator._run_interactive_command("c", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, state.run_id)
        self.assertEqual(len(runtime.selection_calls), 1)
        self.assertEqual(runtime.selection_calls[0]["selector"], "project")
        self.assertEqual(runtime.selection_calls[0]["prompt"], "Commit changes for")
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.projects, ["Feature A"])
