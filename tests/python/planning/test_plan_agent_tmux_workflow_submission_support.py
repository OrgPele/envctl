from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.planning.plan_agent.models import (
    AiCliReadyResult,
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
    _PlanAgentWorkflowStep,
)
from envctl_engine.planning.plan_agent.tmux_workflow_submission_support import (
    launch_tmux_cli_bootstrap_commands,
    maybe_submit_tmux_codex_goal,
    queue_tmux_codex_workflow_steps,
    submit_tmux_prompt_workflow_step,
)
from envctl_engine.planning.plan_agent.tmux_prompt_readiness_support import (
    wait_for_tmux_prompt_accepted,
)
from envctl_engine.planning.plan_agent.tmux_workflow_queue_support import (
    queue_tmux_codex_message,
)


def _launch_config(*, codex_goal_enable: bool = True, transport: str = "tmux") -> PlanAgentLaunchConfig:
    return PlanAgentLaunchConfig(
        enabled=True,
        transport=transport,
        cli="codex",
        cli_command="codex",
        preset="implementation",
        codex_cycles=1,
        codex_cycles_warning=None,
        shell="/bin/zsh",
        require_cmux_context=False,
        cmux_workspace="",
        direct_prompt_enabled=False,
        ulw_loop_prefix=True,
        ulw_suffix=True,
        codex_goal_enable=codex_goal_enable,
    )


class PlanAgentTmuxWorkflowSubmissionSupportTests(unittest.TestCase):
    def test_bootstrap_commands_type_cd_and_cli_command(self) -> None:
        calls: list[tuple[str, str, bool]] = []

        def send_text_fn(_runtime, **kwargs):  # noqa: ANN001, ANN003
            calls.append(("text", kwargs["text"], kwargs["emit_failure_event"]))
            return None

        def send_key_fn(_runtime, **kwargs):  # noqa: ANN001, ANN003
            calls.append(("key", kwargs["key"], kwargs["emit_failure_event"]))
            return None

        errors = launch_tmux_cli_bootstrap_commands(
            SimpleNamespace(),
            session_name="envctl-session",
            window_name="feature-a-1",
            cwd=Path("/repo/work tree"),
            cli_command="codex",
            failure_event="dashboard.review_tab.failed",
            send_tmux_text_fn=send_text_fn,
            send_tmux_key_fn=send_key_fn,
        )

        self.assertEqual(errors, [None, None, None, None])
        self.assertEqual(
            calls,
            [
                ("text", "cd '/repo/work tree'", False),
                ("key", "enter", False),
                ("text", "codex", False),
                ("key", "enter", False),
            ],
        )

    def test_submit_prompt_workflow_step_waits_for_opencode_acceptance(self) -> None:
        calls: list[str] = []

        error = submit_tmux_prompt_workflow_step(
            SimpleNamespace(),
            session_name="envctl-session",
            window_name="feature-a-1",
            prompt_text="implement",
            cli="opencode",
            send_tmux_prompt_fn=lambda *_args, **kwargs: calls.append(f"prompt:{kwargs['text']}") or None,
            send_tmux_key_fn=lambda *_args, **kwargs: calls.append(f"key:{kwargs['key']}") or None,
            wait_for_tmux_prompt_accepted_fn=lambda *_args, **_kwargs: AiCliReadyResult(
                ready=True,
                reason="prompt_accepted",
            ),
            format_ai_cli_ready_failure_fn=lambda result: f"failure:{result.reason}",
            sleep_fn=lambda seconds: calls.append(f"sleep:{seconds}"),
        )

        self.assertIsNone(error)
        self.assertEqual(calls, ["prompt:implement", "sleep:1.0", "key:enter"])

    def test_maybe_submit_tmux_codex_goal_emits_fallback_on_ready_timeout(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace()
        worktree = CreatedPlanWorktree(name="feature-a-1", root=Path("/repo/trees/feature-a/1"), plan_file="a.md")
        workflow = _PlanAgentWorkflow(
            mode="single",
            codex_cycles=1,
            steps=(_PlanAgentWorkflowStep(kind="submit_prompt", text="implement"),),
        )

        error = maybe_submit_tmux_codex_goal(
            runtime,
            session_name="envctl-session",
            window_name="feature-a-1",
            launch_config=_launch_config(),
            workflow=workflow,
            worktree=worktree,
            transport="tmux",
            codex_goal_text_for_worktree_fn=lambda **_kwargs: "goal text",
            submit_tmux_codex_goal_fn=lambda *_args, **_kwargs: "codex_goal_ready_timeout",
            emit_codex_goal_event_fn=lambda _runtime, event, **payload: events.append((event, payload)),
        )

        self.assertEqual(error, "codex_goal_ready_timeout")
        self.assertEqual(events[0][0], "planning.agent_launch.codex_goal_fallback")
        self.assertEqual(events[0][1]["transport"], "tmux")
        self.assertEqual(events[0][1]["reason"], "codex_goal_ready_timeout")

    def test_queue_tmux_codex_workflow_steps_preserves_goal_before_prompt(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        sent: list[str] = []
        queued: list[str] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))
        worktree = CreatedPlanWorktree(name="feature-a-1", root=Path("/repo/trees/feature-a/1"), plan_file="a.md")
        workflow = _PlanAgentWorkflow(
            mode="codex_cycles",
            codex_cycles=1,
            steps=(_PlanAgentWorkflowStep(kind="queue_direct_prompt", text="cycle", requires_goal=True),),
        )

        error = queue_tmux_codex_workflow_steps(
            runtime,
            session_name="envctl-session",
            window_name="feature-a-1",
            worktree=worktree,
            workflow=workflow,
            queued_steps=workflow.steps,
            launch_config=_launch_config(),
            cli="codex",
            transport="tmux",
            codex_goal_text_for_worktree_fn=lambda **_kwargs: "goal text",
            workflow_step_prompt_text_fn=lambda *_args, **_kwargs: ("prompt text", None),
            send_tmux_prompt_fn=lambda *_args, **kwargs: sent.append(kwargs["text"]) or None,
            queue_tmux_codex_message_fn=lambda *_args, **kwargs: queued.append(kwargs["text"]) or True,
        )

        self.assertIsNone(error)
        self.assertEqual(sent, ["/goal goal text", "prompt text"])
        self.assertEqual(queued, ["/goal goal text", "prompt text"])
        self.assertEqual(events[0][0], "planning.agent_launch.workflow_queued")
        self.assertEqual(events[0][1]["transport"], "tmux")

    def test_queue_tmux_codex_message_tabs_only_after_text_is_visible(self) -> None:
        sent_keys: list[str] = []
        state = {"stage": "typed"}
        queued_text = "Queued prompt body"
        ready_screen = f"OpenAI Codex\n  {queued_text}\n  tab to queue message\n"
        queued_screen = "OpenAI Codex\n• Queued follow-up messages\n"

        def read_screen(_runtime, **_kwargs):  # noqa: ANN001, ANN003
            return ready_screen if state["stage"] == "typed" else queued_screen

        def send_key(_runtime, **kwargs):  # noqa: ANN001, ANN003
            sent_keys.append(kwargs["key"])
            state["stage"] = "queued"
            return None

        queued = queue_tmux_codex_message(
            SimpleNamespace(),
            session_name="envctl-session",
            window_name="feature-a-1",
            text=queued_text,
            read_tmux_screen_fn=read_screen,
            send_tmux_key_fn=send_key,
        )

        self.assertTrue(queued)
        self.assertEqual(sent_keys, ["tab"])

    def test_wait_for_tmux_prompt_accepted_skips_post_submit_check_for_codex(self) -> None:
        result = wait_for_tmux_prompt_accepted(
            SimpleNamespace(),
            session_name="envctl-session",
            window_name="feature-a-1",
            cli="codex",
            prompt_text="implement",
            read_tmux_screen_fn=lambda *_args, **_kwargs: "",
        )

        self.assertTrue(result.ready)
        self.assertEqual(result.reason, "post_submit_check_not_required")


if __name__ == "__main__":
    unittest.main()
