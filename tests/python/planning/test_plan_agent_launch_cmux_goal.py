# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *
from tests.python.planning.plan_agent_launch_support_test_support import (
    _codex_goal_screen_looks_active,
    _ImmediateThread,
    _monotonic_counter,
    _RecordingRunner,
)



class PlanAgentLaunchCmuxGoalTests(PlanAgentLaunchSupportTestCase):
    def test_launch_sequence_uses_cmux_commands_for_codex(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "workspace:7",
                    "ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE": "false",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:9\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "╭───────────────────────────────────────────────────╮\n"
                            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
                            "│ model:     gpt-5.4 high   fast   /model to change │\n"
                            "│ directory: ~/repo                                 │\n"
                            "• Booting MCP server: playwright (0s • esc to interrupt)\n"
                            "› Explain this codebase\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "╭───────────────────────────────────────────────────╮\n"
                            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
                            "│ model:     gpt-5.4 high   fast   /model to change │\n"
                            "│ directory: ~/repo                                 │\n"
                            "› Explain this codebase\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "  /prompts:implement_task\n"
                            "  /prompts:implement_task.bak-20260313-192914\n"
                            "  /prompts:implement_task\n"
                            "  Sisyphus (Ultraworker)\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="  /prompts:implement_task\n  Sisyphus (Ultraworker)\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None) as sleep_mock,
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter()),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
            ):
                _ImmediateThread.created = []
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "new-surface", "--workspace", "workspace:7"])
            self.assertIn(["cmux", "rename-tab", "--workspace", "workspace:7", "--surface", "surface:9", "feature-a-1"], rt.process_runner.calls)
            self.assertIn(["cmux", "respawn-pane", "--workspace", "workspace:7", "--surface", "surface:9", "--command", "zsh"], rt.process_runner.calls)
            self.assertIn(["cmux", "send", "--workspace", "workspace:7", "--surface", "surface:9", f"cd {repo}"], rt.process_runner.calls)
            self.assertIn(
                [
                    "cmux",
                    "send",
                    "--workspace",
                    "workspace:7",
                    "--surface",
                    "surface:9",
                    "codex --dangerously-bypass-approvals-and-sandbox",
                ],
                rt.process_runner.calls,
            )
            self.assertTrue(
                any(
                    call
                    == [
                        "cmux",
                        "send",
                        "--workspace",
                        "workspace:7",
                        "--surface",
                        "surface:9",
                        "/prompts:implement_task",
                    ]
                    for call in rt.process_runner.calls
                )
            )
            self.assertIn(
                ["cmux", "paste-buffer", "--name", "envctl-surface-9", "--workspace", "workspace:7", "--surface", "surface:9"],
                rt.process_runner.calls,
            )
            self.assertEqual(len(_ImmediateThread.created), 1)
            self.assertTrue(_ImmediateThread.created[0].started)
            self.assertEqual(_ImmediateThread.created[0].daemon, False)
            self.assertGreaterEqual(rt.process_runner.calls.count(["cmux", "read-screen", "--workspace", "workspace:7", "--surface", "surface:9", "--lines", "80"]), 2)
            self.assertGreaterEqual(len(sleep_mock.call_args_list), 1)
            self.assertEqual(sleep_mock.call_args_list[0].args[0], 0.15)

    def test_codex_goal_screen_detects_observed_active_goal_frame(self) -> None:
        goal_text = "Implement the envctl plan-agent task for features/a.md in this worktree."

        self.assertTrue(
            terminal_screen._codex_goal_screen_looks_active(
                "╭────────────────────────╮\n"
                "│ >_ OpenAI Codex        │\n"
                "• Goal active Objective: Implement the envctl plan-agent task for features/a.md in this worktree.\n"
                "› Explain this codebase\n",
                goal_text,
            )
        )
        self.assertFalse(
            terminal_screen._codex_goal_screen_looks_active(
                "╭────────────────────────╮\n"
                "│ >_ OpenAI Codex        │\n"
                "│ model: gpt-5.5         │\n"
                "│ directory: ~/repo      │\n"
                "› Explain this codebase\n",
                goal_text,
            )
        )
        self.assertFalse(
            terminal_screen._codex_goal_screen_looks_active(
                "• Goal active Objective: Review a different project before editing.\n"
                "› Explain this codebase\n",
                goal_text,
            )
        )

    def test_codex_goal_screen_detects_active_goal_frame(self) -> None:
        self.assertTrue(
            _codex_goal_screen_looks_active(
                "╭────────────────────────╮\n"
                "│ >_ OpenAI Codex        │\n"
                "│ Active goal            │\n"
                "│ Implement the plan     │\n"
                "› Explain this codebase\n"
            )
        )
        self.assertTrue(_codex_goal_screen_looks_active("<goal_context>\n<objective>Implement the plan</objective>"))
        self.assertFalse(
            _codex_goal_screen_looks_active(
                "╭────────────────────────╮\n"
                "│ >_ OpenAI Codex        │\n"
                "│ model: gpt-5.4         │\n"
                "│ directory: ~/repo      │\n"
                "› Explain this codebase\n"
            )
        )

    def test_cmux_codex_launch_waits_for_active_goal_before_implementation_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "workspace:7",
                    "ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE": "false",
                    "ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE": "false",
                },
            )
            ready_screen = (
                "╭───────────────────────────────────────────────────╮\n"
                "│ >_ OpenAI Codex (v0.115.0)                        │\n"
                "│ model:     gpt-5.4 high   fast   /model to change │\n"
                "│ directory: ~/repo                                 │\n"
                "› Explain this codebase\n"
            )
            active_goal_screen = (
                "╭───────────────────────────────────────────────────╮\n"
                "│ >_ OpenAI Codex (v0.115.0)                        │\n"
                "│ model:     gpt-5.4 high   fast   /model to change │\n"
                "│ directory: ~/repo                                 │\n"
                "│ Goal active Objective: Implement the envctl plan-agent task for a.md in this worktree. │\n"
                "› Explain this codebase\n"
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:9\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout=ready_screen, stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout=ready_screen, stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout=active_goal_screen, stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout=active_goal_screen, stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter()),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
            ):
                _ImmediateThread.created = []
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            goal_buffer_index = next(
                index
                for index, call in enumerate(rt.process_runner.calls)
                if call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-9"]
                and str(call[-1]).startswith("/goal ")
            )
            implementation_command_index = next(
                index
                for index, call in enumerate(rt.process_runner.calls)
                if call
                == [
                    "cmux",
                    "send",
                    "--workspace",
                    "workspace:7",
                    "--surface",
                    "surface:9",
                    "/prompts:implement_task",
                ]
            )
            intervening_reads = [
                call
                for call in rt.process_runner.calls[goal_buffer_index + 1 : implementation_command_index]
                if call
                == ["cmux", "read-screen", "--workspace", "workspace:7", "--surface", "surface:9", "--lines", "80"]
            ]
            self.assertGreaterEqual(len(intervening_reads), 2)
            self.assertEqual(len(self._events(rt, "planning.agent_launch.codex_goal_submitted")), 1)

    def test_cmux_codex_goal_must_be_active_before_implementation_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime_dir)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="features/a.md")
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="cmux",
                cli="codex",
                cli_command="codex",
                preset="implement_task",
                codex_cycles=0,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="workspace:7",
                direct_prompt_enabled=False,
                ulw_loop_prefix=False,
                ulw_suffix=False,
                browser_e2e_followup_enable=False,
                pr_review_comments_followup_enable=False,
                codex_goal_enable=True,
            )
            pasted_texts: list[str] = []
            screens = iter(
                [
                    "╭────────────────────────╮\n│ >_ OpenAI Codex        │\n│ model: gpt-5.4         │\n› Explain this codebase\n",
                    "╭────────────────────────╮\n"
                    "│ >_ OpenAI Codex        │\n"
                    "• Goal active Objective: Implement the envctl plan-agent task for features/a.md in this worktree.\n"
                    "› Explain this codebase\n",
                    "╭────────────────────────╮\n│ >_ OpenAI Codex        │\n│ model: gpt-5.4         │\n│ directory: ~/repo      │\n› Explain this codebase\n",
                ]
            )

            def fake_paste(*_args, text, **_kwargs):  # noqa: ANN202, ANN001
                pasted_texts.append(text)
                return None

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport._prepare_surface", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._launch_cli_bootstrap_commands", return_value=[None]),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._paste_surface_text", side_effect=fake_paste),
                patch("envctl_engine.planning.plan_agent.cmux_transport._send_surface_key", return_value=None),
                patch(
                    "envctl_engine.planning.plan_agent.cmux_transport._read_surface_screen",
                    side_effect=lambda *_args, **_kwargs: next(screens),
                ),
                patch(
                    "envctl_engine.planning.plan_agent.cmux_transport._workflow_step_prompt_text",
                    return_value=("IMPLEMENT PROMPT", None),
                ),
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter()),
            ):
                error = cmux_transport._run_surface_bootstrap(
                    rt,
                    workspace_id="workspace:7",
                    surface_id="surface:9",
                    launch_config=launch_config,
                    worktree=worktree,
                )

        self.assertIsNone(error)
        self.assertEqual(len(pasted_texts), 2)
        self.assertTrue(pasted_texts[0].startswith("/goal "))
        self.assertEqual(pasted_texts[1], "IMPLEMENT PROMPT")

    def test_cmux_codex_goal_inactive_screen_blocks_implementation_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime_dir)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="features/a.md")
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="cmux",
                cli="codex",
                cli_command="codex",
                preset="implement_task",
                codex_cycles=0,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="workspace:7",
                direct_prompt_enabled=False,
                ulw_loop_prefix=False,
                ulw_suffix=False,
                browser_e2e_followup_enable=False,
                pr_review_comments_followup_enable=False,
                codex_goal_enable=True,
            )
            pasted_texts: list[str] = []
            ready_screen = (
                "╭────────────────────────╮\n"
                "│ >_ OpenAI Codex        │\n"
                "│ model: gpt-5.4         │\n"
                "│ directory: ~/repo      │\n"
                "› Explain this codebase\n"
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport._prepare_surface", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._launch_cli_bootstrap_commands", return_value=[None]),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_cli_ready", return_value=None),
                patch(
                    "envctl_engine.planning.plan_agent.cmux_transport._paste_surface_text",
                    side_effect=lambda *_args, text, **_kwargs: pasted_texts.append(text) or None,
                ),
                patch("envctl_engine.planning.plan_agent.cmux_transport._send_surface_key", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._read_surface_screen", return_value=ready_screen),
                patch(
                    "envctl_engine.planning.plan_agent.cmux_transport._workflow_step_prompt_text",
                    return_value=("IMPLEMENT PROMPT", None),
                ),
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=1.0)),
            ):
                error = cmux_transport._run_surface_bootstrap(
                    rt,
                    workspace_id="workspace:7",
                    surface_id="surface:9",
                    launch_config=launch_config,
                    worktree=worktree,
                )

        self.assertEqual(error, "codex_goal_active_timeout")
        self.assertEqual(len(pasted_texts), 1)
        self.assertTrue(pasted_texts[0].startswith("/goal "))
