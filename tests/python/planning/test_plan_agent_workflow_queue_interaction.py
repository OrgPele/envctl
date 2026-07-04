from __future__ import annotations

import unittest

from envctl_engine.planning.plan_agent.workflow_queue_interaction import (
    CodexQueueMessageInteractor,
    wait_until_codex_queue_ready,
)


class PlanAgentWorkflowQueueInteractionTests(unittest.TestCase):
    def test_wait_until_codex_queue_ready_polls_until_prompt_returns(self) -> None:
        ready_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "› Explain this codebase\n"
        )
        screens = iter(["working", "still busy", ready_screen])
        sleeps: list[float] = []

        ready = wait_until_codex_queue_ready(
            read_screen=lambda: next(screens),
            monotonic=iter([0.0, 0.1, 0.2, 0.3, 0.4]).__next__,
            sleep=sleeps.append,
            timeout_seconds=1.0,
            poll_interval_seconds=0.05,
        )

        self.assertTrue(ready)
        self.assertEqual(sleeps, [0.05, 0.05])

    def test_queue_message_tabs_only_after_message_text_is_visible(self) -> None:
        sent_keys: list[str] = []
        state = {"stage": "typed"}
        queued_text = "Queued prompt body"
        ready_screen = f"OpenAI Codex\n  {queued_text}\n  tab to queue message\n"
        queued_screen = "OpenAI Codex\n• Queued follow-up messages\n"

        interactor = CodexQueueMessageInteractor(
            read_screen=lambda: ready_screen if state["stage"] == "typed" else queued_screen,
            send_key=lambda key: sent_keys.append(key) or state.update(stage="queued") or None,
            monotonic=iter([0.0, 0.1, 0.2, 0.3]).__next__,
            sleep=lambda _seconds: None,
            timeout_seconds=1.0,
            poll_interval_seconds=0.05,
            max_tab_attempts=3,
        )

        self.assertTrue(interactor.queue_message(queued_text))
        self.assertEqual(sent_keys, ["tab"])

    def test_queue_message_tabs_when_long_paste_is_collapsed_by_codex(self) -> None:
        sent_keys: list[str] = []
        state = {"stage": "typed"}
        queued_text = "You are finalizing an implementation.\n" + ("Confirm validation evidence.\n" * 80)
        ready_screen = "OpenAI Codex\n  › [Pasted Content 2198 chars]\n  tab to queue message\n"
        queued_screen = "OpenAI Codex\n• Queued follow-up messages\n"

        interactor = CodexQueueMessageInteractor(
            read_screen=lambda: ready_screen if state["stage"] == "typed" else queued_screen,
            send_key=lambda key: sent_keys.append(key) or state.update(stage="queued") or None,
            monotonic=iter([0.0, 0.1, 0.2, 0.3]).__next__,
            sleep=lambda _seconds: None,
            timeout_seconds=1.0,
            poll_interval_seconds=0.05,
            max_tab_attempts=3,
        )

        self.assertTrue(interactor.queue_message(queued_text))
        self.assertEqual(sent_keys, ["tab"])

    def test_queue_message_tabs_for_long_prompt_when_only_tab_hint_is_visible(self) -> None:
        sent_keys: list[str] = []
        state = {"stage": "typed"}
        queued_text = "You are finalizing an implementation.\n" + ("Confirm validation evidence.\n" * 80)
        ready_screen = "OpenAI Codex\n  tab to queue message\n"
        queued_screen = "OpenAI Codex\n• Queued follow-up messages\n"

        interactor = CodexQueueMessageInteractor(
            read_screen=lambda: ready_screen if state["stage"] == "typed" else queued_screen,
            send_key=lambda key: sent_keys.append(key) or state.update(stage="queued") or None,
            monotonic=iter([0.0, 0.1, 0.2, 0.3]).__next__,
            sleep=lambda _seconds: None,
            timeout_seconds=1.0,
            poll_interval_seconds=0.05,
            max_tab_attempts=3,
        )

        self.assertTrue(interactor.queue_message(queued_text))
        self.assertEqual(sent_keys, ["tab"])

    def test_queue_message_does_not_send_keys_when_message_text_is_not_visible(self) -> None:
        sent_keys: list[str] = []
        queued_text = "Queued prompt body"
        ready_screen = "OpenAI Codex\n  tab to queue message\n"

        interactor = CodexQueueMessageInteractor(
            read_screen=lambda: ready_screen,
            send_key=lambda key: sent_keys.append(key) or None,
            prompt_picker_enabled=True,
            monotonic=iter([0.0, 0.1, 0.2, 0.3]).__next__,
            sleep=lambda _seconds: None,
            timeout_seconds=0.2,
            poll_interval_seconds=0.05,
            max_tab_attempts=3,
        )

        self.assertFalse(interactor.queue_message(queued_text, require_text_match=False))
        self.assertEqual(sent_keys, [])

    def test_queue_message_can_submit_picker_before_tab_confirmation(self) -> None:
        sent_keys: list[str] = []
        state = {"stage": "picker"}
        queued_text = "/goal Write tests"
        picker_screen = f"OpenAI Codex\n  {queued_text}\n  /goal Write tests\n  press enter to submit\n"
        ready_screen = f"OpenAI Codex\n  {queued_text}\n  tab to queue message\n"
        queued_screen = "OpenAI Codex\n• Queued follow-up messages\n"

        def read_screen() -> str:
            if state["stage"] == "picker":
                return picker_screen
            if state["stage"] == "typed":
                return ready_screen
            return queued_screen

        def send_key(key: str) -> str | None:
            sent_keys.append(key)
            if key == "enter":
                state["stage"] = "typed"
            if key == "tab":
                state["stage"] = "queued"
            return None

        interactor = CodexQueueMessageInteractor(
            read_screen=read_screen,
            send_key=send_key,
            prompt_picker_enabled=True,
            monotonic=iter([0.0, 0.1, 0.2, 0.3, 0.4]).__next__,
            sleep=lambda _seconds: None,
            timeout_seconds=1.0,
            poll_interval_seconds=0.05,
            max_tab_attempts=3,
        )

        self.assertTrue(interactor.queue_message(queued_text))
        self.assertEqual(sent_keys, ["enter", "tab"])

    def test_queue_message_aborts_when_picker_submit_fails(self) -> None:
        sent_keys: list[str] = []
        queued_text = "/goal Write tests"
        picker_screen = f"OpenAI Codex\n  {queued_text}\n  /goal Write tests\n  press enter to submit\n"

        interactor = CodexQueueMessageInteractor(
            read_screen=lambda: picker_screen,
            send_key=lambda key: sent_keys.append(key) or "failed",
            prompt_picker_enabled=True,
            monotonic=iter([0.0, 0.1, 0.2, 0.3]).__next__,
            sleep=lambda _seconds: None,
            timeout_seconds=1.0,
            poll_interval_seconds=0.05,
            max_tab_attempts=3,
        )

        self.assertFalse(interactor.queue_message(queued_text))
        self.assertEqual(sent_keys, ["enter"])


if __name__ == "__main__":
    unittest.main()
