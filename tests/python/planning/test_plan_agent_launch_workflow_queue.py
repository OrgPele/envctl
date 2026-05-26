# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchWorkflowQueueTests(PlanAgentLaunchSupportTestCase):
    def test_codex_cycle_queue_direct_prompt_tabs_without_picker_resolution(self) -> None:
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
        committed_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "• Queued follow-up messages\n"
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            if key == "tab":
                state["stage"] = "committed"
            return None

        def fake_read_screen(*_args, **_kwargs):  # noqa: ANN202, ANN001
            if state["stage"] == "typed":
                return queue_hint_screen
            return committed_screen

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
            patch("envctl_engine.planning.plan_agent.cmux_transport._send_surface_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent.cmux_transport._read_surface_screen", side_effect=fake_read_screen),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = cmux_transport._queue_codex_message(
                runtime,
                workspace_id="workspace:7",
                surface_id="surface:9",
                text=queued_text,
                require_text_match=False,
            )

        self.assertTrue(queued)
        self.assertEqual(sent_keys, ["tab"])

    def test_codex_cycle_queue_direct_prompt_requires_visible_message_text_before_tab(self) -> None:
        sent_keys: list[str] = []
        queued_text = "Direct queued prompt body"
        queue_hint_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "  tab to queue message\n"
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
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
            patch("envctl_engine.planning.plan_agent.cmux_transport._send_surface_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent.cmux_transport._read_surface_screen", return_value=queue_hint_screen),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = cmux_transport._queue_codex_message(
                runtime,
                workspace_id="workspace:7",
                surface_id="surface:9",
                text=queued_text,
                require_text_match=False,
        )

        self.assertFalse(queued)
        self.assertNotIn("tab", sent_keys)

    def test_codex_cycle_queue_direct_prompt_accepts_pasted_content_placeholder(self) -> None:
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
        committed_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "• Queued follow-up messages\n"
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            if key == "tab":
                state["stage"] = "committed"
            return None

        def fake_read_screen(*_args, **_kwargs):  # noqa: ANN202, ANN001
            if state["stage"] == "typed":
                return queue_hint_screen
            return committed_screen

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
            patch("envctl_engine.planning.plan_agent.cmux_transport._send_surface_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent.cmux_transport._read_surface_screen", side_effect=fake_read_screen),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = cmux_transport._queue_codex_message(
                runtime,
                workspace_id="workspace:7",
                surface_id="surface:9",
                text=queued_text,
                require_text_match=False,
            )

        self.assertTrue(queued)
        self.assertEqual(sent_keys, ["tab"])
