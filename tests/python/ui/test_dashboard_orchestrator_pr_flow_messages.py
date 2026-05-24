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


class DashboardOrchestratorPrFlowMessageTests(_DashboardOrchestratorTestCase):
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
