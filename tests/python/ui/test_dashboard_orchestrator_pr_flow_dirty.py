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


class DashboardOrchestratorPrFlowDirtyTests(_DashboardOrchestratorTestCase):
    def test_pr_dirty_target_accepts_commit_then_dispatches_pr(self) -> None:
        runtime = _RuntimeStub()
        runtime.text_input_responses = ["PR body", "Ship dirty changes"]
        orchestrator = DashboardOrchestrator(runtime)
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]
        state = RunState(
            run_id="run-pr-dirty-accept",
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
            metadata={"project_roots": {"Main": "."}},
        )
        runtime._latest_state = state

        with (
            patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree") as dirty_probe,
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl") as selector,
        ):
            selector.return_value = ["__DIRTY_PR_COMMIT__"]
            dirty_probe.return_value = SimpleNamespace(
                project_name="Main",
                project_root=Path(runtime.config.base_dir),
                git_root=Path(runtime.config.base_dir),
                staged=False,
                unstaged=True,
                untracked=False,
                dirty=True,
            )
            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual([route.command for route in runtime.dispatched_routes], ["commit", "pr"])
        self.assertEqual(runtime.dispatched_routes[0].projects, ["Main"])
        self.assertEqual(runtime.dispatched_routes[0].flags.get("commit_message"), "Ship dirty changes")
        self.assertEqual(runtime.dispatched_routes[1].flags.get("pr_body"), "PR body")
        selector.assert_called_once()
        selector_kwargs = selector.call_args.kwargs
        self.assertEqual(
            selector_kwargs["prompt"],
            "UNSTAGED CODE IN WORKTREE Main - DO YOU WANT TO STAGE IT?",
        )
        self.assertEqual([item.label for item in selector_kwargs["options"]], ["Commit", "Do nothing"])
        self.assertEqual([item.kind for item in selector_kwargs["options"]], ["", ""])
        self.assertEqual(selector_kwargs["multi"], False)

    def test_pr_dirty_target_decline_skips_commit_and_dispatches_pr_only(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]
        state = RunState(
            run_id="run-pr-dirty-decline",
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
            metadata={"project_roots": {"Main": "."}},
        )
        runtime._latest_state = state

        with (
            patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree") as dirty_probe,
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["__DIRTY_PR_SKIP__"]),
        ):
            dirty_probe.return_value = SimpleNamespace(
                project_name="Main",
                project_root=Path(runtime.config.base_dir),
                git_root=Path(runtime.config.base_dir),
                staged=True,
                unstaged=False,
                untracked=False,
                dirty=True,
            )
            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual([route.command for route in runtime.dispatched_routes], ["pr"])

    def test_pr_dirty_target_cancel_aborts_without_dispatch(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]
        state = RunState(
            run_id="run-pr-dirty-cancel",
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
            metadata={"project_roots": {"Main": "."}},
        )
        runtime._latest_state = state

        out = StringIO()
        with (
            patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree") as dirty_probe,
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=None),
            redirect_stdout(out),
        ):
            dirty_probe.return_value = SimpleNamespace(
                project_name="Main",
                project_root=Path(runtime.config.base_dir),
                git_root=Path(runtime.config.base_dir),
                staged=False,
                unstaged=False,
                untracked=True,
                dirty=True,
            )
            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.dispatched_routes, [])
        self.assertIn("Cancelled PR creation.", out.getvalue())

    def test_pr_clean_target_skips_commit_prompt(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]
        state = RunState(
            run_id="run-pr-clean",
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
            metadata={"project_roots": {"Main": "."}},
        )
        runtime._latest_state = state

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
            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.confirm_prompts, [])
        self.assertEqual([route.command for route in runtime.dispatched_routes], ["pr"])

    def test_typed_pr_command_still_runs_dirty_preflight(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-pr-typed",
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
            metadata={"project_roots": {"Main": "."}},
        )
        runtime._latest_state = state

        with (
            patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree") as dirty_probe,
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["__DIRTY_PR_SKIP__"]),
        ):
            dirty_probe.return_value = SimpleNamespace(
                project_name="Main",
                project_root=Path(runtime.config.base_dir),
                git_root=Path(runtime.config.base_dir),
                staged=True,
                unstaged=False,
                untracked=False,
                dirty=True,
            )
            should_continue, next_state = orchestrator._run_interactive_command(
                "pr --project Main --pr-base release/2026-03-10",
                state,
                runtime,
            )

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        dirty_probe.assert_called_once()
        self.assertEqual([route.command for route in runtime.dispatched_routes], ["pr"])
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.flags.get("pr_base"), "release/2026-03-10")

    def test_pr_commit_failure_aborts_pr_dispatch(self) -> None:
        runtime = _RuntimeStub()
        runtime.text_input_responses = ["Ship dirty changes"]
        orchestrator = DashboardOrchestrator(runtime)
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]
        state = RunState(
            run_id="run-pr-commit-fail",
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
            metadata={
                "project_roots": {"Main": "."},
                "project_action_reports": {
                    "Main": {
                        "commit": {
                            "status": "failed",
                            "summary": "git commit failed\ndetails",
                            "report_path": "/tmp/runtime/Main_commit.txt",
                        }
                    }
                },
            },
        )
        runtime._latest_state = state

        def fail_commit_dispatch(route: Route) -> int:
            runtime.last_dispatched_route = route
            runtime.dispatched_routes.append(route)
            return 1 if route.command == "commit" else 0

        runtime.dispatch = fail_commit_dispatch  # type: ignore[assignment]

        out = StringIO()
        with (
            patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree") as dirty_probe,
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["__DIRTY_PR_COMMIT__"]),
            redirect_stdout(out),
        ):
            dirty_probe.return_value = SimpleNamespace(
                project_name="Main",
                project_root=Path(runtime.config.base_dir),
                git_root=Path(runtime.config.base_dir),
                staged=True,
                unstaged=True,
                untracked=False,
                dirty=True,
            )
            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual([route.command for route in runtime.dispatched_routes], ["commit"])
        self.assertIn("commit failed for Main: git commit failed", out.getvalue())

    def test_pr_multi_target_commits_only_dirty_subset(self) -> None:
        runtime = _RuntimeStub()
        runtime.text_input_responses = ["Ship dirty subset"]
        runtime.next_pr_flow_result = PrFlowResult(project_names=["feature-a-1", "feature-b-1"], base_branch="main")
        orchestrator = DashboardOrchestrator(runtime)
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]
        state = RunState(
            run_id="run-pr-dirty-multi",
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
                "feature-b-1 Backend": ServiceRecord(
                    name="feature-b-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=101,
                    requested_port=8001,
                    actual_port=8001,
                    status="running",
                ),
            },
            metadata={
                "project_roots": {
                    "feature-a-1": "trees/feature-a/1",
                    "feature-b-1": "trees/feature-b/1",
                }
            },
        )
        runtime._latest_state = state

        def fake_probe(project_root: Path, repo_root: Path, *, project_name: str = "") -> object:
            is_dirty = project_name == "feature-a-1"
            return SimpleNamespace(
                project_name=project_name,
                project_root=project_root,
                git_root=project_root,
                staged=is_dirty,
                unstaged=False,
                untracked=False,
                dirty=is_dirty,
            )

        with (
            patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree", side_effect=fake_probe),
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["__DIRTY_PR_COMMIT__"]),
        ):
            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual([route.command for route in runtime.dispatched_routes], ["commit", "pr"])
        self.assertEqual(runtime.dispatched_routes[0].projects, ["feature-a-1"])
        self.assertEqual(runtime.dispatched_routes[1].projects, ["feature-a-1"])

    def test_pr_multi_target_dedupes_shared_git_root_before_commit_and_pr(self) -> None:
        runtime = _RuntimeStub()
        runtime.text_input_responses = ["PR body", "Ship shared root"]
        runtime.next_pr_flow_result = PrFlowResult(project_names=["feature-a-1", "feature-b-1"], base_branch="main")
        orchestrator = DashboardOrchestrator(runtime)
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]
        state = RunState(
            run_id="run-pr-dirty-shared-root",
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
                "feature-b-1 Backend": ServiceRecord(
                    name="feature-b-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=101,
                    requested_port=8001,
                    actual_port=8001,
                    status="running",
                ),
            },
            metadata={
                "project_roots": {
                    "feature-a-1": ".",
                    "feature-b-1": ".",
                }
            },
        )
        runtime._latest_state = state

        def fake_probe(project_root: Path, repo_root: Path, *, project_name: str = "") -> object:
            return SimpleNamespace(
                project_name=project_name,
                project_root=project_root,
                git_root=Path(runtime.config.base_dir),
                staged=True,
                unstaged=False,
                untracked=False,
                dirty=True,
            )

        with (
            patch("envctl_engine.ui.dashboard.orchestrator.probe_dirty_worktree", side_effect=fake_probe),
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["__DIRTY_PR_COMMIT__"]),
        ):
            should_continue, next_state = orchestrator._run_interactive_command("p", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual([route.command for route in runtime.dispatched_routes], ["commit", "pr"])
        self.assertEqual(runtime.dispatched_routes[0].projects, ["feature-a-1"])
        self.assertEqual(runtime.dispatched_routes[1].projects, ["feature-a-1"])
