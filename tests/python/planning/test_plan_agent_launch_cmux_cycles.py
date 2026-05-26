# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *



class PlanAgentLaunchCmuxCyclesTests(PlanAgentLaunchSupportTestCase):
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
                        "queued_steps": 5,
                        "queued_steps_confirmed": 5,
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
                    "pr_review_comments_followup_enable": False,
                }
            ],
        )
