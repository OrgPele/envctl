# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchCmuxTests(PlanAgentLaunchSupportTestCase):
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
                    call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-9"]
                    and str(call[-1]).startswith("You are implementing real code, end-to-end.")
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
            implementation_buffer_index = next(
                index
                for index, call in enumerate(rt.process_runner.calls)
                if call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-9"]
                and str(call[-1]).startswith("You are implementing real code, end-to-end.")
            )
            intervening_reads = [
                call
                for call in rt.process_runner.calls[goal_buffer_index + 1 : implementation_buffer_index]
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

    def test_codex_cycle_launch_queues_follow_up_messages_with_tab(self) -> None:
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
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "2",
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
                            "› Explain this codebase\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="  /prompts:implement_task\n  Sisyphus (Ultraworker)\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "╭───────────────────────────────────────────────────╮\n"
                            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
                            "│ model:     gpt-5.4 high   fast   /model to change │\n"
                            "│ directory: ~/repo                                 │\n"
                            "› /prompts:implement_task\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "╭───────────────────────────────────────────────────╮\n"
                            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
                            "│ model:     gpt-5.4 high   fast   /model to change │\n"
                            "│ directory: ~/repo                                 │\n"
                            "› /prompts:implement_task\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "╭───────────────────────────────────────────────────╮\n"
                            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
                            "│ model:     gpt-5.4 high   fast   /model to change │\n"
                            "│ directory: ~/repo                                 │\n"
                            "› /prompts:continue_task\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "╭───────────────────────────────────────────────────╮\n"
                            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
                            "│ model:     gpt-5.4 high   fast   /model to change │\n"
                            "│ directory: ~/repo                                 │\n"
                            "› /prompts:implement_task\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter()),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent.cmux_transport._queue_codex_message", return_value=True),
            ):
                _ImmediateThread.created = []
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertTrue(
                any(
                    call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-9"]
                    and "You are implementing real code, end-to-end." in str(call[-1])
                    for call in rt.process_runner.calls
                )
            )
            self.assertTrue(
                any(
                    call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-9"]
                    and "You are preparing the next implementation iteration" in str(call[-1])
                    for call in rt.process_runner.calls
                )
            )
            self.assertTrue(
                any(
                    call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-9"]
                    and "You are finalizing an implementation" in str(call[-1])
                    for call in rt.process_runner.calls
                )
            )
            self.assertEqual(
                self._events(rt, "planning.agent_launch.workflow_queued"),
                [
                    {
                        "event": "planning.agent_launch.workflow_queued",
                        "workspace_id": "workspace:7",
                        "surface_id": "surface:9",
                        "worktree": "feature-a-1",
                        "cli": "codex",
                        "workflow_mode": "codex_cycles",
                        "codex_cycles": 2,
                        "queued_steps": 6,
                        "queued_steps_confirmed": 6,
                        "transport": "cmux",
                    }
                ],
            )
            self.assertEqual(rt._persist_events_snapshot_calls, 1)

    def test_wait_for_codex_queue_ready_tolerates_delayed_prompt_return(self) -> None:
        self.assertIsNotNone(_wait_for_codex_queue_ready)
        ready_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "› /prompts:implement_task\n"
        )
        screens = iter(["Booting MCP server...\n"] * 12 + [ready_screen])
        runtime = object()

        with (
            patch(
                "envctl_engine.planning.plan_agent.cmux_transport._read_surface_screen",
                side_effect=lambda *_args, **_kwargs: next(screens, ready_screen),
            ),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            ready = _wait_for_codex_queue_ready(runtime, workspace_id="workspace:7", surface_id="surface:9")

        self.assertTrue(ready)

    def test_codex_cycle_queue_types_message_before_waiting_for_tab_ready(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=1)
        queued_steps = workflow.steps[1:2]
        self.assertEqual(len(queued_steps), 1)
        pasted_texts: list[str] = []
        sent_keys: list[str] = []

        busy_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "• Working (32s • esc to interrupt)\n"
        )
        state = {"typed": False, "text": ""}

        def typed_screen() -> str:
            first_line = next((line for line in state["text"].splitlines() if line.strip()), "")
            return (
                "╭───────────────────────────────────────────────────╮\n"
                "│ >_ OpenAI Codex (v0.115.0)                        │\n"
                "│ model:     gpt-5.4 high   fast   /model to change │\n"
                "│ directory: ~/repo                                 │\n"
                f"  {first_line}\n"
                "  tab to queue message\n"
            )

        def fake_paste_text(*_args, text, **_kwargs):  # noqa: ANN202, ANN001
            pasted_texts.append(text)
            state["typed"] = True
            state["text"] = text
            return None

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            state["typed"] = False
            return None

        runtime = _RuntimeHarness(
            config=load_config(
                {
                    "RUN_REPO_ROOT": "/tmp/repo",
                    "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                }
            ),
            env={},
            process_runner=_RecordingRunner(),
        )

        with (
            patch("envctl_engine.planning.plan_agent.cmux_transport._paste_surface_text", side_effect=fake_paste_text),
            patch("envctl_engine.planning.plan_agent.cmux_transport._send_surface_key", side_effect=fake_send_key),
            patch(
                "envctl_engine.planning.plan_agent.cmux_transport._read_surface_screen",
                side_effect=lambda *_args, **_kwargs: typed_screen() if state["typed"] else busy_screen,
            ),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            reason = cmux_transport._queue_codex_workflow_steps(
                runtime,
                workspace_id="workspace:7",
                surface_id="surface:9",
                worktree=CreatedPlanWorktree(name="feature-a-1", root=Path("/tmp/repo"), plan_file="a.md"),
                workflow=workflow,
                queued_steps=queued_steps,
                launch_config=_launch_config_for_tests(cli="codex"),
                cli="codex",
        )

        self.assertIsNone(reason)
        self.assertEqual(len(pasted_texts), 2)
        self.assertTrue(pasted_texts[0].startswith("/goal "))
        self.assertIn("You are finalizing an implementation", pasted_texts[1])
        self.assertEqual(sent_keys, ["tab", "tab"])

    def test_cmux_codex_queue_fails_when_message_remains_in_textbox_after_tab(self) -> None:
        sent_keys: list[str] = []
        queued_text = "Direct queued prompt body"
        stuck_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "  Direct queued prompt body\n"
            "  tab to queue message\n"
        )
        runtime = _RuntimeHarness(
            config=load_config({"RUN_REPO_ROOT": "/tmp/repo", "RUN_SH_RUNTIME_DIR": "/tmp/runtime"}),
            env={},
            process_runner=_RecordingRunner(),
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            return None

        with (
            patch("envctl_engine.planning.plan_agent.cmux_transport._send_surface_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent.cmux_transport._read_surface_screen", return_value=stuck_screen),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = cmux_transport._queue_codex_message(
                runtime, workspace_id="workspace:7", surface_id="surface:9", text=queued_text, require_text_match=False
            )

        self.assertFalse(queued)
        self.assertEqual(sent_keys, ["tab", "tab"])

    def test_codex_cycle_queue_failure_falls_back_to_initial_prompt(self) -> None:
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
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "1",
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
                            "› Explain this codebase\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="  /prompts:implement_task\n  Sisyphus (Ultraworker)\n",
                        stderr="",
                    ),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter()),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_codex_queue_ready", return_value=True),
                patch(
                    "envctl_engine.planning.plan_agent.cmux_transport._paste_surface_text",
                    side_effect=[None, "queue failed"],
                ),
            ):
                _ImmediateThread.created = []
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(self._events(rt, "planning.agent_launch.failed"), [])
            self.assertEqual(
                self._events(rt, "planning.agent_launch.workflow_fallback"),
                [
                    {
                        "event": "planning.agent_launch.workflow_fallback",
                        "workspace_id": "workspace:7",
                        "surface_id": "surface:9",
                        "worktree": "feature-a-1",
                        "cli": "codex",
                        "workflow_mode": "codex_cycles",
                        "codex_cycles": 1,
                        "reason": "queue_send_failed",
                        "queue_failed_step_index": 0,
                        "queue_failed_step_kind": "queue_direct_prompt",
                        "transport": "cmux",
                    }
                ],
            )
            self.assertEqual(
                self._events(rt, "planning.agent_launch.workflow_queue_failed"),
                [
                    {
                        "event": "planning.agent_launch.workflow_queue_failed",
                        "workspace_id": "workspace:7",
                        "surface_id": "surface:9",
                        "worktree": "feature-a-1",
                        "cli": "codex",
                        "workflow_mode": "codex_cycles",
                        "codex_cycles": 1,
                        "reason": "queue_send_failed",
                        "queue_failed_step_index": 0,
                        "queue_failed_step_kind": "queue_direct_prompt",
                        "transport": "cmux",
                    }
                ],
            )

    def test_codex_cycle_launch_uses_cycles_alias_in_summary_and_workflow_selection(self) -> None:
        self.assertIsNotNone(_WorkspaceLaunchTarget)
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
                    "CYCLES": "3",
                },
            )

            def _fake_launch_single_worktree(*args, **kwargs):  # noqa: ANN202, ANN001
                worktree = kwargs["worktree"]
                return launch_support.PlanAgentLaunchOutcome(
                    worktree_name=worktree.name,
                    worktree_root=worktree.root,
                    surface_id="surface:9",
                    status="launched",
                )

            buffer = StringIO()
            with (
                redirect_stdout(buffer),
                patch(
                    "envctl_engine.planning.plan_agent.launch._ensure_workspace_id",
                    return_value=_WorkspaceLaunchTarget(workspace_id="workspace:7", created=False),
                ),
                patch(
                    "envctl_engine.planning.plan_agent.launch._launch_single_worktree",
                    side_effect=_fake_launch_single_worktree,
                ),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

        self.assertEqual(result.status, "launched")
        self.assertIn("Plan agent launch queued Codex cycle workflow (cycles=3)", buffer.getvalue())
        self.assertEqual(
            self._events(rt, "planning.agent_launch.workflow_selected"),
            [
                {
                    "event": "planning.agent_launch.workflow_selected",
                    "workspace_id": "workspace:7",
                    "warning": None,
                    "enabled": True,
                    "cli": "codex",
                    "created_worktree_count": 1,
                    "workflow_mode": "codex_cycles",
                    "codex_cycles": 3,
                    "codex_goal_enable": True,
                    "browser_e2e_followup_enable": True,
                    "pr_review_comments_followup_enable": True,
                }
            ],
        )

    def test_launch_sequence_supports_opencode_and_default_implementation_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CLI": "opencode",
                    "ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT": "false",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:4  envctl  [selected]\n  workspace:8  envctl implementation\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:12\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="Loading workspace...\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout='  ┃  Ask anything... "Fix broken tests"\n  ctrl+p commands\n  ~/repo  ⊙ 3 MCP /status    1.2.27\n',
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "  ┃ /implement_task                                                   ┃\n"
                            "  ┃ /implement_task.bak-20260313-192914                               ┃\n"
                            "  ┃ /implement_task.bak-20260315-173140                               ┃\n"
                            "  ┃                                                                 \n"
                            "  ┃  /implement_task                                                 \n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "  ┃                                                                 \n"
                            "  ┃  /implement_task                                                 \n"
                            "  ┃                                                                 \n"
                            "  ┃  Sisyphus (Ultraworker)                                          \n"
                        ),
                        stderr="",
                    ),
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
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-surface", "--workspace", "workspace:8"])
            self.assertIn(
                ["cmux", "respawn-pane", "--workspace", "workspace:8", "--surface", "surface:12", "--command", "zsh"],
                rt.process_runner.calls,
            )
            self.assertIn(["cmux", "send", "--workspace", "workspace:8", "--surface", "surface:12", f"cd {repo}"], rt.process_runner.calls)
            self.assertIn(["cmux", "send-key", "--workspace", "workspace:8", "--surface", "surface:12", "enter"], rt.process_runner.calls)
            self.assertIn(["cmux", "send", "--workspace", "workspace:8", "--surface", "surface:12", "opencode"], rt.process_runner.calls)
            direct_prompt_calls = [
                call
                for call in rt.process_runner.calls
                if call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-12"]
            ]
            self.assertEqual(len(direct_prompt_calls), 1)
            self.assertTrue(str(direct_prompt_calls[0][-1]).startswith("/ulw-loop You are implementing real code"))
            self.assertIn(
                ["cmux", "paste-buffer", "--name", "envctl-surface-12", "--workspace", "workspace:8", "--surface", "surface:12"],
                rt.process_runner.calls,
            )
            self.assertEqual(len(_ImmediateThread.created), 1)
            self.assertTrue(_ImmediateThread.created[0].started)
            self.assertEqual(_ImmediateThread.created[0].daemon, False)
            self.assertGreaterEqual(rt.process_runner.calls.count(["cmux", "read-screen", "--workspace", "workspace:8", "--surface", "surface:12", "--lines", "80"]), 2)
            self.assertGreaterEqual(
                rt.process_runner.calls.count(
                    ["cmux", "send-key", "--workspace", "workspace:8", "--surface", "surface:12", "enter"]
                ),
                2,
            )
            self.assertNotIn(
                ["cmux", "send-key", "--workspace", "workspace:8", "--surface", "surface:12", "tab"],
                rt.process_runner.calls,
            )
            self.assertGreaterEqual(len(sleep_mock.call_args_list), 2)
            self.assertIn(0.15, [call.args[0] for call in sleep_mock.call_args_list])
            self.assertIn(0.1, [call.args[0] for call in sleep_mock.call_args_list[1:]])

    def test_created_default_workspace_reuses_single_starter_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "CMUX_WORKSPACE_ID": "workspace:4",
                    "ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE": "false",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:4  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:9\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:77\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_prompt_picker_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_prompt_submit_ready", return_value=None),
            ):
                _ImmediateThread.created = []
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-workspace", "--cwd", str(repo.resolve())])
            self.assertEqual(rt.process_runner.calls[2], ["cmux", "current-workspace"])
            self.assertEqual(
                rt.process_runner.calls[3],
                ["cmux", "rename-workspace", "--workspace", "workspace:9", "envctl implementation"],
            )
            self.assertEqual(rt.process_runner.calls[4], ["cmux", "list-pane-surfaces", "--workspace", "workspace:9"])
            self.assertNotIn(["cmux", "new-surface", "--workspace", "workspace:9"], rt.process_runner.calls)
            self.assertIn(
                ["cmux", "rename-tab", "--workspace", "workspace:9", "--surface", "surface:77", "feature-a-1"],
                rt.process_runner.calls,
            )
            self.assertIn(
                ["cmux", "respawn-pane", "--workspace", "workspace:9", "--surface", "surface:77", "--command", "zsh"],
                rt.process_runner.calls,
            )
            self.assertIn(["cmux", "send", "--workspace", "workspace:9", "--surface", "surface:77", f"cd {repo}"], rt.process_runner.calls)
            self.assertIn(
                [
                    "cmux",
                    "send",
                    "--workspace",
                    "workspace:9",
                    "--surface",
                    "surface:77",
                    "codex --dangerously-bypass-approvals-and-sandbox",
                ],
                rt.process_runner.calls,
            )
            self.assertTrue(
                any(
                    call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-77"]
                    and str(call[-1]).startswith("You are implementing real code, end-to-end.")
                    for call in rt.process_runner.calls
                )
            )
            self.assertIn(
                ["cmux", "paste-buffer", "--name", "envctl-surface-77", "--workspace", "workspace:9", "--surface", "surface:77"],
                rt.process_runner.calls,
            )
            self.assertEqual(len(_ImmediateThread.created), 1)

    def test_workspace_entries_are_parsed_from_list_output(self) -> None:
        payload = """
        * workspace:1  envctl  [selected]
          workspace:2  envctl implementation
          workspace:3  supportopia
        """
        self.assertEqual(
            cmux_transport._workspace_entries_from_list_output(payload),
            (
                ("workspace:1", "envctl"),
                ("workspace:2", "envctl implementation"),
                ("workspace:3", "supportopia"),
            ),
        )

    def test_surface_ids_are_parsed_from_list_output(self) -> None:
        payload = """
        pane:1
          surface:20 [terminal] "~/repo"
          surface:21 [terminal] "feature-a-1" [selected]
        """
        self.assertEqual(
            cmux_transport._surface_ids_from_list_output(payload),
            ("surface:20", "surface:21"),
        )

    def test_surface_ids_parser_dedupes_repeated_surface_refs(self) -> None:
        payload = """
        pane:1
          surface:20 [terminal] "~/repo"
        pane:2
          surface:20 [terminal] "~/repo" [selected]
        """
        self.assertEqual(
            cmux_transport._surface_ids_from_list_output(payload),
            ("surface:20",),
        )

    def test_surface_ids_parser_ignores_non_numeric_surface_tokens(self) -> None:
        payload = """
        pane:1
          surface:notes [terminal] "~/repo"
          surface:21 [terminal] "feature-a-1" [selected]
        """
        self.assertEqual(
            cmux_transport._surface_ids_from_list_output(payload),
            ("surface:21",),
        )

    def test_workspace_ref_is_parsed_from_identify_output(self) -> None:
        payload = """
        {
          "caller": {
            "workspace_ref": "workspace:4"
          },
          "focused": {
            "workspace_ref": "workspace:8"
          }
        }
        """
        self.assertEqual(cmux_transport._workspace_ref_from_identify_output(payload), "workspace:4")

    def test_explicit_workspace_override_implies_enablement_and_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "workspace:9",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:33\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            with patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "new-surface", "--workspace", "workspace:9"])
            self.assertNotIn(["cmux", "current-workspace"], rt.process_runner.calls)

    def test_explicit_workspace_override_resolves_workspace_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "envctl",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:1  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:33\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            with patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-surface", "--workspace", "workspace:1"])
            self.assertNotIn(["cmux", "current-workspace"], rt.process_runner.calls)

    def test_cmux_alias_enables_default_implementation_workspace_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "CMUX": "true",
                    "CMUX_WORKSPACE_ID": "workspace:7",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:7  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:9\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:10\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-workspace", "--cwd", str(repo.resolve())])
            self.assertEqual(rt.process_runner.calls[2], ["cmux", "current-workspace"])
            self.assertEqual(rt.process_runner.calls[3], ["cmux", "rename-workspace", "--workspace", "workspace:9", "envctl implementation"])
            self.assertEqual(rt.process_runner.calls[4], ["cmux", "list-pane-surfaces", "--workspace", "workspace:9"])
            self.assertNotIn(["cmux", "new-surface", "--workspace", "workspace:9"], rt.process_runner.calls)

    def test_cmux_alias_resolves_uuid_workspace_context_before_default_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "CMUX": "true",
                    "CMUX_WORKSPACE_ID": "B2F931FE-491C-448F-8B45-0BA5C932C8F0",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:7  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            '{\n'
                            '  "caller": {\n'
                            '    "workspace_ref": "workspace:7"\n'
                            "  },\n"
                            '  "focused": {\n'
                            '    "workspace_ref": "workspace:7"\n'
                            "  }\n"
                            "}\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:9\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:10\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "identify"])
            self.assertEqual(rt.process_runner.calls[2], ["cmux", "new-workspace", "--cwd", str(repo.resolve())])
            self.assertEqual(rt.process_runner.calls[3], ["cmux", "current-workspace"])
            self.assertEqual(rt.process_runner.calls[4], ["cmux", "rename-workspace", "--workspace", "workspace:9", "envctl implementation"])
            self.assertEqual(rt.process_runner.calls[5], ["cmux", "list-pane-surfaces", "--workspace", "workspace:9"])
            self.assertNotIn(["cmux", "new-surface", "--workspace", "workspace:9"], rt.process_runner.calls)

    def test_cmux_workspace_alias_resolves_workspace_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "CMUX_WORKSPACE": "envctl",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:1  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:44\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            with patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-surface", "--workspace", "workspace:1"])

    def test_created_named_workspace_reuses_single_starter_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "brand-new-workspace",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:1  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:3\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:44\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-workspace", "--cwd", str(repo.resolve())])
            self.assertEqual(rt.process_runner.calls[2], ["cmux", "current-workspace"])
            self.assertEqual(
                rt.process_runner.calls[3],
                ["cmux", "rename-workspace", "--workspace", "workspace:3", "brand-new-workspace"],
            )
            self.assertEqual(rt.process_runner.calls[4], ["cmux", "list-pane-surfaces", "--workspace", "workspace:3"])
            self.assertNotIn(["cmux", "new-surface", "--workspace", "workspace:3"], rt.process_runner.calls)

    def test_created_workspace_emits_probe_and_reused_surface_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "brand-new-workspace",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:1  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:3\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:44\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            probe_events = self._events(rt, "planning.agent_launch.workspace_surface_probe")
            self.assertEqual(
                probe_events,
                [
                    {
                        "event": "planning.agent_launch.workspace_surface_probe",
                        "workspace_id": "workspace:3",
                        "result": "single",
                        "surface_count": 1,
                        "surface_id": "surface:44",
                    }
                ],
            )
            self.assertEqual(self._events(rt, "planning.agent_launch.surface_fallback"), [])
            self.assertEqual(
                self._events(rt, "planning.agent_launch.surface_created"),
                [
                    {
                        "event": "planning.agent_launch.surface_created",
                        "workspace_id": "workspace:3",
                        "surface_id": "surface:44",
                        "worktree": "feature-a-1",
                        "source": "starter_reused",
                    }
                ],
            )

    def test_created_workspace_falls_back_to_new_surface_when_starter_probe_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "brand-new-workspace",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:1  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:3\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:44\nsurface:45\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:46\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[4], ["cmux", "list-pane-surfaces", "--workspace", "workspace:3"])
            self.assertEqual(rt.process_runner.calls[5], ["cmux", "new-surface", "--workspace", "workspace:3"])

    def test_created_workspace_emits_probe_and_fallback_events_when_probe_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "brand-new-workspace",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:1  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:3\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:44\nsurface:45\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:46\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(
                self._events(rt, "planning.agent_launch.workspace_surface_probe"),
                [
                    {
                        "event": "planning.agent_launch.workspace_surface_probe",
                        "workspace_id": "workspace:3",
                        "result": "ambiguous",
                        "surface_count": 2,
                    }
                ],
            )
            self.assertEqual(
                self._events(rt, "planning.agent_launch.surface_fallback"),
                [
                    {
                        "event": "planning.agent_launch.surface_fallback",
                        "workspace_id": "workspace:3",
                        "reason": "ambiguous",
                    }
                ],
            )
            self.assertEqual(
                self._events(rt, "planning.agent_launch.surface_created"),
                [
                    {
                        "event": "planning.agent_launch.surface_created",
                        "workspace_id": "workspace:3",
                        "surface_id": "surface:46",
                        "worktree": "feature-a-1",
                        "source": "new_surface",
                    }
                ],
            )

    def test_existing_workspace_still_creates_new_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "CMUX_WORKSPACE_ID": "workspace:4",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:4  envctl  [selected]\n  workspace:9  envctl implementation\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:77\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-surface", "--workspace", "workspace:9"])

    def test_existing_workspace_emits_new_surface_event_without_probe_or_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "CMUX_WORKSPACE_ID": "workspace:4",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:4  envctl  [selected]\n  workspace:9  envctl implementation\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:77\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(self._events(rt, "planning.agent_launch.workspace_surface_probe"), [])
            self.assertEqual(self._events(rt, "planning.agent_launch.surface_fallback"), [])
            self.assertEqual(
                self._events(rt, "planning.agent_launch.surface_created"),
                [
                    {
                        "event": "planning.agent_launch.surface_created",
                        "workspace_id": "workspace:9",
                        "surface_id": "surface:77",
                        "worktree": "feature-a-1",
                        "source": "new_surface",
                    }
                ],
            )

    def test_review_launch_uses_reviews_workspace_and_repo_root_for_codex_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "feature-a" / "1"
            review_bundle = repo / "runtime" / "review" / "all.md"
            original_plan = repo / "todo" / "plans" / "implementations" / "feature-a.md"
            project_root.mkdir(parents=True, exist_ok=True)
            review_bundle.parent.mkdir(parents=True, exist_ok=True)
            original_plan.parent.mkdir(parents=True, exist_ok=True)
            review_bundle.write_text("# review\n", encoding="utf-8")
            original_plan.write_text("# Original plan\n", encoding="utf-8")
            (project_root / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (project_root / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps({"schema_version": 1, "plan_file": "implementations/feature-a.md"}) + "\n",
                encoding="utf-8",
            )
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "CMUX_WORKSPACE_ID": "workspace:4",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:4  envctl  [selected]\n  workspace:8  envctl implementation\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:10\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:12\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_prompt_picker_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_prompt_submit_ready", return_value=None),
            ):
                _ImmediateThread.created = []
                result = launch_support.launch_review_agent_terminal(
                    rt,
                    repo_root=repo,
                    project_name="feature-a-1",
                    project_root=project_root,
                    review_bundle_path=review_bundle,
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-workspace", "--cwd", str(repo.resolve())])
            self.assertEqual(rt.process_runner.calls[2], ["cmux", "rename-workspace", "--workspace", "workspace:10", "envctl reviews"])
            self.assertEqual(rt.process_runner.calls[3], ["cmux", "list-pane-surfaces", "--workspace", "workspace:10"])
            self.assertEqual(rt.process_runner.calls[4], ["cmux", "new-surface", "--workspace", "workspace:10"])
            self.assertIn(
                ["cmux", "send", "--workspace", "workspace:10", "--surface", "surface:12", f"cd {repo}"],
                rt.process_runner.calls,
            )
            self.assertNotIn(
                ["cmux", "send", "--workspace", "workspace:10", "--surface", "surface:12", f"cd {project_root}"],
                rt.process_runner.calls,
            )
            review_prompt_calls = [
                call
                for call in rt.process_runner.calls
                if call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-12"]
            ]
            self.assertEqual(len(review_prompt_calls), 1)
            self.assertIn("current local repo directory is the unedited baseline", str(review_prompt_calls[0][-1]))
            self.assertIn(f'Review bundle: "{review_bundle}"', str(review_prompt_calls[0][-1]))
            self.assertIn(f'Worktree directory: "{project_root}"', str(review_prompt_calls[0][-1]))
            self.assertIn(f'Original plan file: "{original_plan.resolve()}"', str(review_prompt_calls[0][-1]))
            self.assertIn(
                ["cmux", "paste-buffer", "--name", "envctl-surface-12", "--workspace", "workspace:10", "--surface", "surface:12"],
                rt.process_runner.calls,
            )

    def test_review_launch_honors_explicit_workspace_override_and_opencode_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "feature-a" / "1"
            review_bundle = repo / "runtime" / "review" / "all.md"
            original_plan = repo / "todo" / "plans" / "implementations" / "feature-a.md"
            project_root.mkdir(parents=True, exist_ok=True)
            review_bundle.parent.mkdir(parents=True, exist_ok=True)
            original_plan.parent.mkdir(parents=True, exist_ok=True)
            review_bundle.write_text("# review\n", encoding="utf-8")
            original_plan.write_text("# Current plan\n", encoding="utf-8")
            (project_root / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (project_root / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps({"schema_version": 1, "plan_file": "implementations/feature-a.md"}) + "\n",
                encoding="utf-8",
            )
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CLI": "opencode",
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "workspace:9",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:15\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_prompt_picker_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_prompt_submit_ready", return_value=None),
            ):
                _ImmediateThread.created = []
                result = launch_support.launch_review_agent_terminal(
                    rt,
                    repo_root=repo,
                    project_name="feature-a-1",
                    project_root=project_root,
                    review_bundle_path=review_bundle,
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "new-surface", "--workspace", "workspace:9"])
            self.assertNotIn(["cmux", "list-workspaces"], rt.process_runner.calls)
            direct_prompt_calls = [
                call
                for call in rt.process_runner.calls
                if call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-15"]
            ]
            self.assertEqual(len(direct_prompt_calls), 1)
            self.assertTrue(str(direct_prompt_calls[0][-1]).startswith("/ulw-loop You are reviewing"))
            self.assertIn(f'Review bundle: "{review_bundle}"', str(direct_prompt_calls[0][-1]))
            self.assertIn(f'Worktree directory: "{project_root}"', str(direct_prompt_calls[0][-1]))
            self.assertIn(f'Original plan file: "{original_plan.resolve()}"', str(direct_prompt_calls[0][-1]))
            self.assertIn(
                ["cmux", "paste-buffer", "--name", "envctl-surface-15", "--workspace", "workspace:9", "--surface", "surface:15"],
                rt.process_runner.calls,
            )

    def test_review_launch_resolves_original_plan_file_from_worktree_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            project_root = repo / "trees" / "feature-a" / "1"
            original_plan = repo / "todo" / "plans" / "implementations" / "feature-a.md"
            project_root.mkdir(parents=True, exist_ok=True)
            original_plan.parent.mkdir(parents=True, exist_ok=True)
            original_plan.write_text("# first plan\n", encoding="utf-8")
            (project_root / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (project_root / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps({"schema_version": 1, "plan_file": "implementations/feature-a.md"}) + "\n",
                encoding="utf-8",
            )
            original_plan_path = workflow._review_original_plan_path(
                "feature-a-1",
                project_root,
                repo_root=repo,
            )

            self.assertEqual(original_plan_path, original_plan.resolve())

    def test_review_launch_returns_none_when_original_plan_file_cannot_be_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            project_root = repo / "trees" / "feature-a" / "1"
            project_root.mkdir(parents=True, exist_ok=True)

            original_plan_path = workflow._review_original_plan_path(
                "feature-a-1",
                project_root,
                repo_root=repo,
            )

            self.assertIsNone(original_plan_path)

    def test_review_launch_does_not_infer_when_recorded_plan_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            project_root = repo / "trees" / "implementations_task" / "1"
            inferred_plan = repo / "todo" / "done" / "implementations" / "task.md"
            project_root.mkdir(parents=True, exist_ok=True)
            inferred_plan.parent.mkdir(parents=True, exist_ok=True)
            inferred_plan.write_text("# done plan\n", encoding="utf-8")
            (project_root / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (project_root / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps({"schema_version": 1, "plan_file": "implementations/missing.md"}) + "\n",
                encoding="utf-8",
            )

            original_plan_path = workflow._review_original_plan_path(
                "implementations_task-1",
                project_root,
                repo_root=repo,
            )

            self.assertIsNone(original_plan_path)

    def test_review_launch_can_infer_original_plan_file_without_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            project_root = repo / "trees" / "implementations_task" / "1"
            original_plan = repo / "todo" / "done" / "implementations" / "task.md"
            project_root.mkdir(parents=True, exist_ok=True)
            original_plan.parent.mkdir(parents=True, exist_ok=True)
            original_plan.write_text("# done plan\n", encoding="utf-8")

            original_plan_path = workflow._review_original_plan_path(
                "implementations_task-1",
                project_root,
                repo_root=repo,
            )

            self.assertEqual(original_plan_path, original_plan.resolve())

    def test_review_launch_prefers_active_plan_over_archived_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            project_root = repo / "trees" / "features_task"
            active_plan = repo / "todo" / "plans" / "features" / "task.md"
            archived_plan = repo / "todo" / "done" / "features" / "task.md"
            project_root.mkdir(parents=True, exist_ok=True)
            active_plan.parent.mkdir(parents=True, exist_ok=True)
            archived_plan.parent.mkdir(parents=True, exist_ok=True)
            active_plan.write_text("# active plan\n", encoding="utf-8")
            archived_plan.write_text("# archived plan\n", encoding="utf-8")

            original_plan_path = workflow._review_original_plan_path(
                "features_task",
                project_root,
                repo_root=repo,
            )

            self.assertEqual(original_plan_path, active_plan.resolve())
