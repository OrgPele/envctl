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


class DashboardOrchestratorPrFlowTests(_DashboardOrchestratorTestCase):
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

    def test_project_action_failure_details_render_hyperlinked_report_path(self) -> None:
        runtime = _RuntimeStub()
        runtime.env["ENVCTL_UI_HYPERLINK_MODE"] = "on"
        orchestrator = DashboardOrchestrator(runtime)
        with tempfile.TemporaryDirectory() as tmpdir:
            report_path = Path(tmpdir) / "failure.log"
            report_path.write_text("report\n", encoding="utf-8")
            state = RunState(
                run_id="run-1",
                mode="main",
                metadata={
                    "project_action_reports": {
                        "Main": {
                            "review": {
                                "status": "failed",
                                "summary": "review failed\nhint: open the log",
                                "report_path": str(report_path),
                            }
                        }
                    }
                },
            )

            out = _TtyStringIO()
            with redirect_stdout(out):
                printed = orchestrator._print_project_action_failure_details(
                    Route(
                        command="review",
                        mode="main",
                        raw_args=["review"],
                        passthrough_args=[],
                        projects=["Main"],
                        flags={},
                    ),
                    state,
                )

        self.assertTrue(printed)
        self.assertIn("\x1b]8;;file://", out.getvalue())
        self.assertIn(str(report_path), strip_ansi(out.getvalue()))

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

    def test_commit_prompts_for_message_and_uses_explicit_value_when_provided(self) -> None:
        runtime = _RuntimeStub()
        runtime.text_input_responses = ["Ship the feature"]
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

        should_continue, next_state = orchestrator._run_interactive_command("c", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, state.run_id)
        self.assertEqual(runtime.read_prompts, [])
        self.assertEqual(len(runtime.text_input_prompts), 1)
        self.assertEqual(runtime.text_input_prompts[0]["title"], "Commit Message")
        self.assertEqual(runtime.text_input_prompts[0]["default_button_label"], "Use envctl commit log")
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.command, "commit")
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("commit_message"), "Ship the feature")

    def test_commit_blank_message_uses_existing_default_resolution(self) -> None:
        runtime = _RuntimeStub()
        runtime.text_input_responses = [""]
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

        should_continue, next_state = orchestrator._run_interactive_command("c", state, runtime)

        self.assertTrue(should_continue)
        self.assertEqual(next_state.run_id, state.run_id)
        self.assertEqual(runtime.read_prompts, [])
        self.assertEqual(len(runtime.text_input_prompts), 1)
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.command, "commit")
        self.assertNotIn("commit_message", runtime.last_dispatched_route.flags)

    def test_pr_prompts_for_message_and_uses_explicit_value_when_provided(self) -> None:
        runtime = _RuntimeStub()
        runtime.text_input_responses = ["Ship the feature in this PR"]
        orchestrator = DashboardOrchestrator(runtime)
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]
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
        self.assertEqual(next_state.run_id, state.run_id)
        self.assertEqual(runtime.read_prompts, [])
        self.assertEqual(len(runtime.text_input_prompts), 1)
        self.assertEqual(runtime.text_input_prompts[0]["title"], "PR Message")
        self.assertEqual(runtime.text_input_prompts[0]["default_button_label"], "Use MAIN_TASK.md")
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.command, "pr")
        self.assertEqual(runtime.last_dispatched_route.projects, ["Main"])
        self.assertEqual(runtime.last_dispatched_route.flags.get("pr_base"), "main")
        self.assertEqual(runtime.last_dispatched_route.flags.get("pr_body"), "Ship the feature in this PR")

    def test_pr_blank_message_uses_existing_default_resolution(self) -> None:
        runtime = _RuntimeStub()
        runtime.text_input_responses = [""]
        orchestrator = DashboardOrchestrator(runtime)
        orchestrator._run_pr_selection_flow = lambda **kwargs: (
            runtime.pr_flow_calls.append(kwargs) or runtime.next_pr_flow_result
        )  # type: ignore[method-assign]
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
        self.assertEqual(next_state.run_id, state.run_id)
        self.assertEqual(runtime.read_prompts, [])
        self.assertEqual(len(runtime.text_input_prompts), 1)
        self.assertIsNotNone(runtime.last_dispatched_route)
        assert runtime.last_dispatched_route is not None
        self.assertEqual(runtime.last_dispatched_route.command, "pr")
        self.assertNotIn("pr_body", runtime.last_dispatched_route.flags)

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

    def test_prompt_yes_no_dialog_supports_runtime_single_argument_signature(self) -> None:
        prompts: list[str] = []

        class _RuntimeSingleArgConfirm:
            @staticmethod
            def _prompt_yes_no(prompt: str) -> bool:
                prompts.append(prompt)
                return True

        result = DashboardOrchestrator._prompt_yes_no_dialog(
            _RuntimeSingleArgConfirm(),
            title="Commit dirty changes before PR?",
            prompt="Main has unstaged changes. Choose whether to commit first, continue without committing, or cancel PR creation.",
        )

        self.assertEqual(result, "commit")
        self.assertEqual(
            prompts,
            [
                "Main has unstaged changes. Choose whether to commit first, continue without committing, or cancel PR creation."
            ],
        )

    def test_prompt_yes_no_dialog_blank_fallback_declines_commit(self) -> None:
        class _RuntimeReadFallback:
            def __init__(self) -> None:
                self.read_prompts: list[str] = []
                self.read_responses: list[str] = [""]

            def _read_interactive_command_line(self, prompt: str) -> str:
                self.read_prompts.append(prompt)
                if self.read_responses:
                    return self.read_responses.pop(0)
                return ""

        runtime = _RuntimeReadFallback()

        result = DashboardOrchestrator._prompt_yes_no_dialog(
            runtime,
            title="Commit dirty changes before PR?",
            prompt="Main has unstaged changes. Choose whether to commit first, continue without committing, or cancel PR creation.",
        )

        self.assertEqual(result, "skip")
        self.assertEqual(
            runtime.read_prompts,
            [
                "Main has unstaged changes. Choose whether to commit first, continue without committing, or cancel PR creation."
            ],
        )

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

    def test_project_action_failure_details_print_migrate_results_in_route_order_with_deduped_hints(self) -> None:
        runtime = _RuntimeStub()
        runtime.env["ENVCTL_UI_HYPERLINK_MODE"] = "on"
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-migrate-results",
            mode="trees",
            metadata={
                "project_action_reports": {
                    "feature-a-1": {
                        "migrate": {
                            "status": "success",
                        }
                    },
                    "feature-b-1": {
                        "migrate": {
                            "status": "failed",
                            "headline": "alembic.util.exc.CommandError: migration failed",
                            "summary": (
                                "Traceback (most recent call last):\n"
                                "alembic.util.exc.CommandError: migration failed\n"
                                "hint: envctl migrate loads backend env from backend/.env by default.\n"
                                "hint: envctl migrate loads backend env from backend/.env by default.\n"
                                "hint: BACKEND_ENV_FILE_OVERRIDE or MAIN_ENV_FILE_PATH can redirect the env file.\n"
                            ),
                            "report_path": "/tmp/runtime/feature-b-1_migrate.txt",
                        }
                    },
                }
            },
        )

        out = _TtyStringIO()
        with redirect_stdout(out):
            printed = orchestrator._print_project_action_failure_details(
                Route(
                    command="migrate",
                    mode="trees",
                    raw_args=["migrate"],
                    passthrough_args=[],
                    projects=["feature-a-1", "feature-b-1"],
                    flags={},
                ),
                state,
            )

        self.assertTrue(printed)
        rendered = strip_ansi(out.getvalue())
        self.assertLess(
            rendered.index("✓ migrate succeeded for feature-a-1"),
            rendered.index("✗ migrate failed for feature-b-1: alembic.util.exc.CommandError: migration failed"),
        )
        self.assertEqual(
            rendered.count("hint: envctl migrate loads backend env from backend/.env by default."),
            1,
        )
        self.assertIn(
            "hint: BACKEND_ENV_FILE_OVERRIDE or MAIN_ENV_FILE_PATH can redirect the env file.",
            rendered,
        )
        self.assertIn(
            "migrate failure log for feature-b-1:\n/tmp/runtime/feature-b-1_migrate.txt",
            rendered,
        )

    def test_project_action_failure_details_print_migrate_results_for_all_selection_using_state_projects(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-migrate-all-selection",
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
                "project_action_reports": {
                    "feature-a-1": {"migrate": {"status": "success"}},
                    "feature-b-1": {
                        "migrate": {
                            "status": "failed",
                            "headline": "pydantic_core._pydantic_core.ValidationError: missing env",
                            "summary": (
                                "pydantic_core._pydantic_core.ValidationError: missing env\n"
                                "hint: envctl migrate loads backend env from backend/.env by default.\n"
                            ),
                            "report_path": "/tmp/runtime/feature-b-1_migrate.txt",
                        }
                    },
                }
            },
        )

        out = StringIO()
        with redirect_stdout(out):
            printed = orchestrator._print_project_action_failure_details(
                Route(
                    command="migrate",
                    mode="trees",
                    raw_args=["migrate", "--all"],
                    passthrough_args=[],
                    projects=[],
                    flags={"all": True},
                ),
                state,
            )

        rendered = strip_ansi(out.getvalue())
        self.assertTrue(printed)
        self.assertIn("✓ migrate succeeded for feature-a-1", rendered)
        self.assertIn(
            "✗ migrate failed for feature-b-1: pydantic_core._pydantic_core.ValidationError: missing env",
            rendered,
        )
        self.assertIn("migrate failure log for feature-b-1:\n/tmp/runtime/feature-b-1_migrate.txt", rendered)

    def test_project_action_failure_details_compact_multi_failure_logs_and_hints(self) -> None:
        runtime = _RuntimeStub()
        runtime.env["ENVCTL_UI_COLOR_MODE"] = "on"
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-migrate-compact-failures",
            mode="trees",
            metadata={
                "project_action_reports": {
                    "feature-a-1": {
                        "migrate": {
                            "status": "failed",
                            "headline": "ConnectionResetError: [Errno 54] Connection reset by peer",
                            "summary": (
                                "ConnectionResetError: [Errno 54] Connection reset by peer\n"
                                "hint: backend env source: default | /tmp/runtime/backend-a.env\n"
                                "hint: backend connection was reset while applying migrations.\n"
                            ),
                            "report_path": "/tmp/runtime/run-compact/feature-a-1_migrate.txt",
                        }
                    },
                    "feature-b-1": {
                        "migrate": {
                            "status": "failed",
                            "headline": "ConnectionResetError: [Errno 54] Connection reset by peer",
                            "summary": (
                                "ConnectionResetError: [Errno 54] Connection reset by peer\n"
                                "hint: backend env source: default | /tmp/runtime/backend-b.env\n"
                                "hint: backend connection was reset while applying migrations.\n"
                            ),
                            "report_path": "/tmp/runtime/run-compact/feature-b-1_migrate.txt",
                        }
                    },
                }
            },
        )

        out = _TtyStringIO()
        with redirect_stdout(out):
            printed = orchestrator._print_project_action_failure_details(
                Route(
                    command="migrate",
                    mode="trees",
                    raw_args=["migrate"],
                    passthrough_args=[],
                    projects=["feature-a-1", "feature-b-1"],
                    flags={},
                ),
                state,
            )

        raw_rendered = out.getvalue()
        self.assertIn("\x1b[1;31m✗\x1b[0m", raw_rendered)
        self.assertIn("\x1b[1;34mfeature-a-1\x1b[0m", raw_rendered)
        self.assertIn("\x1b[1;35mfeature-b-1\x1b[0m", raw_rendered)
        rendered = strip_ansi(raw_rendered)
        self.assertTrue(printed)
        self.assertIn("✗ migrate failed for feature-a-1: ConnectionResetError: [Errno 54] Connection reset by peer", rendered)
        self.assertIn("✗ migrate failed for feature-b-1: ConnectionResetError: [Errno 54] Connection reset by peer", rendered)
        self.assertEqual(rendered.count("hint: backend connection was reset while applying migrations."), 1)
        self.assertNotIn("hint: backend env source:", rendered)
        self.assertIn("migrate failure logs:", rendered)
        self.assertIn("/tmp/runtime/run-compact", rendered)
        self.assertIn("- feature-a-1: feature-a-1_migrate.txt", rendered)
        self.assertIn("- feature-b-1: feature-b-1_migrate.txt", rendered)
        self.assertNotIn("migrate failure log for feature-a-1:", rendered)
        self.assertNotIn("migrate failure log for feature-b-1:", rendered)

