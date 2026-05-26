# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchTmuxWorkflowQueueTests(PlanAgentLaunchSupportTestCase):
    def test_tmux_codex_workflow_queue_failure_emits_fallback_with_step_context(self) -> None:
        self.assertIsNotNone(_run_tmux_worktree_bootstrap)
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="tmux",
                cli="codex",
                cli_command="codex --dangerously-bypass-approvals-and-sandbox",
                preset="implement_task",
                codex_cycles=1,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=False,
                ulw_loop_prefix=False,
                ulw_suffix=False,
            )
            workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=1)

            def resolve_step(*_args, step, **_kwargs):
                return (f"resolved::{step.kind}::{step.text}", None)

            with (
                patch("envctl_engine.planning.plan_agent.tmux_transport._launch_tmux_cli_bootstrap_commands", return_value=[None]),
                patch("envctl_engine.planning.plan_agent.tmux_transport._wait_for_tmux_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._workflow_step_prompt_text", side_effect=resolve_step),
                patch("envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_prompt_workflow_step", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._send_tmux_prompt", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._queue_tmux_codex_message", return_value=False),
            ):
                error = _run_tmux_worktree_bootstrap(
                    rt,
                    session_name="envctl-test-session",
                    window_name="feature-a-1",
                    launch_config=launch_config,
                    workflow=workflow,
                    worktree=worktree,
                )

            self.assertIsNone(error)
            expected = {
                "session_name": "envctl-test-session",
                "window_name": "feature-a-1",
                "worktree": "feature-a-1",
                "cli": "codex",
                "workflow_mode": "codex_cycles",
                "codex_cycles": 1,
                "reason": "queue_not_ready",
                "transport": "tmux",
                "queue_failed_step_index": 0,
                "queue_failed_step_kind": "queue_direct_prompt",
            }
            self.assertEqual(
                self._events(rt, "planning.agent_launch.workflow_queue_failed"),
                [{"event": "planning.agent_launch.workflow_queue_failed", **expected}],
            )
            self.assertEqual(
                self._events(rt, "planning.agent_launch.workflow_fallback"),
                [{"event": "planning.agent_launch.workflow_fallback", **expected}],
            )

    def test_tmux_codex_queue_confirms_message_after_tab(self) -> None:
        sent_keys: list[str] = []
        queued_text = "Direct queued prompt body"
        state = {"stage": "typed"}
        queue_hint_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "  Direct queued prompt body\n"
            "  tab to queue message\n"
        )
        committed_screen = "• Queued follow-up messages\n"
        runtime = _RuntimeHarness(
            config=load_config({"RUN_REPO_ROOT": "/tmp/repo", "RUN_SH_RUNTIME_DIR": "/tmp/runtime"}),
            env={},
            process_runner=_RecordingRunner(),
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            if key == "tab":
                state["stage"] = "committed"
            return None

        def fake_read_screen(*_args, **_kwargs):  # noqa: ANN202, ANN001
            return queue_hint_screen if state["stage"] == "typed" else committed_screen

        with (
            patch("envctl_engine.planning.plan_agent.tmux_transport._send_tmux_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent.tmux_transport._read_tmux_screen", side_effect=fake_read_screen),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = tmux_transport._queue_tmux_codex_message(
                runtime, session_name="envctl-test", window_name="feature-a-1", text=queued_text, require_text_match=False
            )

        self.assertTrue(queued)
        self.assertEqual(sent_keys, ["tab"])

    def test_tmux_codex_queue_fails_when_message_remains_in_textbox_after_tab(self) -> None:
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
            patch("envctl_engine.planning.plan_agent.tmux_transport._send_tmux_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent.tmux_transport._read_tmux_screen", return_value=stuck_screen),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = tmux_transport._queue_tmux_codex_message(
                runtime, session_name="envctl-test", window_name="feature-a-1", text=queued_text, require_text_match=False
            )

        self.assertFalse(queued)
        self.assertEqual(sent_keys, ["tab", "tab"])

    def test_tmux_codex_queue_accepts_pasted_content_only_after_post_tab_confirmation(self) -> None:
        sent_keys: list[str] = []
        queued_text = "Direct queued prompt body\nwith multiple lines"
        state = {"stage": "typed"}
        queue_hint_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "› [Pasted Content 6674 chars]\n"
            "  tab to queue message\n"
        )
        committed_screen = "• Queued follow-up messages\n"
        runtime = _RuntimeHarness(
            config=load_config({"RUN_REPO_ROOT": "/tmp/repo", "RUN_SH_RUNTIME_DIR": "/tmp/runtime"}),
            env={},
            process_runner=_RecordingRunner(),
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            if key == "tab":
                state["stage"] = "committed"
            return None

        with (
            patch("envctl_engine.planning.plan_agent.tmux_transport._send_tmux_key", side_effect=fake_send_key),
            patch(
                "envctl_engine.planning.plan_agent.tmux_transport._read_tmux_screen",
                side_effect=lambda *_args, **_kwargs: queue_hint_screen if state["stage"] == "typed" else committed_screen,
            ),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = tmux_transport._queue_tmux_codex_message(
                runtime, session_name="envctl-test", window_name="feature-a-1", text=queued_text, require_text_match=False
            )

        self.assertTrue(queued)
        self.assertEqual(sent_keys, ["tab"])
