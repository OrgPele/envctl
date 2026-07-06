from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.planning.plan_agent.cmux_workflow_submission_support import (
    launch_cli_bootstrap_commands,
    queue_codex_message,
    queue_codex_workflow_steps,
    submit_direct_prompt_workflow_step,
    submit_prompt_workflow_step,
    wait_for_codex_queue_ready,
)
from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
    _PlanAgentWorkflowStep,
)


def _launch_config(*, codex_goal_enable: bool = True) -> PlanAgentLaunchConfig:
    return PlanAgentLaunchConfig(
        enabled=True,
        transport="cmux",
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


class PlanAgentCmuxWorkflowSubmissionSupportTests(unittest.TestCase):
    def test_launch_cli_bootstrap_commands_cd_then_launches_cli(self) -> None:
        calls: list[tuple[str, str]] = []

        def send_surface_text_fn(_runtime, **kwargs):  # noqa: ANN001, ANN003
            calls.append(("text", kwargs["text"]))
            return None

        def send_surface_key_fn(_runtime, **kwargs):  # noqa: ANN001, ANN003
            calls.append(("key", kwargs["key"]))
            return None

        self.assertEqual(
            launch_cli_bootstrap_commands(
                SimpleNamespace(),
                workspace_id="workspace:1",
                surface_id="surface:2",
                cwd=Path("/repo/trees/feature a/1"),
                cli_command="codex --flag",
                send_surface_text_fn=send_surface_text_fn,
                send_surface_key_fn=send_surface_key_fn,
            ),
            [None, None, None, None],
        )
        self.assertEqual(
            calls,
            [
                ("text", "cd '/repo/trees/feature a/1'"),
                ("key", "enter"),
                ("text", "codex --flag"),
                ("key", "enter"),
            ],
        )

    def test_prompt_submission_preserves_picker_and_submit_sequence(self) -> None:
        calls: list[tuple[str, str]] = []

        def send_prompt_text_fn(_runtime, **kwargs):  # noqa: ANN001, ANN003
            calls.append(("text", kwargs["text"]))
            return None

        def send_surface_key_fn(_runtime, **kwargs):  # noqa: ANN001, ANN003
            calls.append(("key", kwargs["key"]))
            return None

        def wait_picker_fn(_runtime, **_kwargs):  # noqa: ANN001, ANN003
            calls.append(("wait", "picker"))

        def wait_submit_fn(_runtime, **_kwargs):  # noqa: ANN001, ANN003
            calls.append(("wait", "submit"))

        self.assertIsNone(
            submit_prompt_workflow_step(
                SimpleNamespace(),
                workspace_id="workspace:1",
                surface_id="surface:2",
                cli="codex",
                prompt_text="/ulw-loop implement",
                send_prompt_text_fn=send_prompt_text_fn,
                send_surface_key_fn=send_surface_key_fn,
                wait_for_prompt_picker_ready_fn=wait_picker_fn,
                wait_for_prompt_submit_ready_fn=wait_submit_fn,
            )
        )
        self.assertEqual(
            calls,
            [
                ("text", "/ulw-loop implement"),
                ("key", "ctrl+e"),
                ("wait", "picker"),
                ("key", "enter"),
                ("wait", "submit"),
                ("key", "enter"),
            ],
        )

    def test_direct_prompt_submission_pastes_then_enters(self) -> None:
        calls: list[tuple[str, str]] = []

        def paste_surface_text_fn(_runtime, **kwargs):  # noqa: ANN001, ANN003
            calls.append(("paste", kwargs["text"]))
            return None

        def send_surface_key_fn(_runtime, **kwargs):  # noqa: ANN001, ANN003
            calls.append(("key", kwargs["key"]))
            return None

        self.assertIsNone(
            submit_direct_prompt_workflow_step(
                SimpleNamespace(),
                workspace_id="workspace:1",
                surface_id="surface:2",
                prompt_text="run this directly",
                paste_surface_text_fn=paste_surface_text_fn,
                send_surface_key_fn=send_surface_key_fn,
            )
        )
        self.assertEqual(calls, [("paste", "run this directly"), ("key", "enter")])

    def test_queue_codex_workflow_steps_preserves_goal_step_before_prompt(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        pasted: list[str] = []
        queued: list[str] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))
        worktree = CreatedPlanWorktree(name="feature-a-1", root=Path("/repo/trees/feature-a/1"), plan_file="a.md")
        workflow = _PlanAgentWorkflow(
            mode="ulw",
            codex_cycles=1,
            steps=(
                _PlanAgentWorkflowStep(kind="submit_prompt", text="cycle", requires_goal=True),
            ),
        )

        def workflow_step_prompt_text_fn(_runtime, **_kwargs):  # noqa: ANN001, ANN003
            return "do the work", None

        def codex_goal_text_for_worktree_fn(**_kwargs):  # noqa: ANN003
            return "goal text"

        def paste_surface_text_fn(_runtime, **kwargs):  # noqa: ANN001, ANN003
            pasted.append(kwargs["text"])
            return None

        def queue_codex_message_fn(_runtime, **kwargs):  # noqa: ANN001, ANN003
            queued.append(kwargs["text"])
            return True

        self.assertIsNone(
            queue_codex_workflow_steps(
                runtime,
                workspace_id="workspace:1",
                surface_id="surface:2",
                worktree=worktree,
                workflow=workflow,
                queued_steps=workflow.steps,
                launch_config=_launch_config(codex_goal_enable=True),
                cli="codex",
                workflow_step_prompt_text_fn=workflow_step_prompt_text_fn,
                codex_goal_text_for_worktree_fn=codex_goal_text_for_worktree_fn,
                paste_surface_text_fn=paste_surface_text_fn,
                queue_codex_message_fn=queue_codex_message_fn,
            )
        )
        self.assertEqual(pasted, ["/goal goal text", "do the work"])
        self.assertEqual(queued, ["/goal goal text", "do the work"])
        self.assertEqual(events[0][0], "planning.agent_launch.workflow_queued")

    def test_queue_codex_message_accepts_injected_clock_for_wrapper_compatibility(self) -> None:
        sent_keys: list[str] = []
        sleeps: list[float] = []
        state = {"stage": "typed"}

        def read_surface_screen_fn(_runtime, **_kwargs):  # noqa: ANN001, ANN003, ANN202
            if state["stage"] == "typed":
                return "OpenAI Codex\n  queued body\n  tab to queue message\n"
            return "OpenAI Codex\n• Queued follow-up messages\n"

        def send_surface_key_fn(_runtime, **kwargs):  # noqa: ANN001, ANN003, ANN202
            sent_keys.append(kwargs["key"])
            state["stage"] = "queued"
            return None

        queued = queue_codex_message(
            SimpleNamespace(),
            workspace_id="workspace:1",
            surface_id="surface:2",
            text="queued body",
            read_surface_screen_fn=read_surface_screen_fn,
            send_surface_key_fn=send_surface_key_fn,
            monotonic=iter([0.0, 0.1, 0.2, 0.3]).__next__,
            sleep=sleeps.append,
        )

        self.assertTrue(queued)
        self.assertEqual(sent_keys, ["tab"])
        self.assertEqual(sleeps, [0.1])

    def test_queue_codex_message_inserts_skill_picker_before_queueing(self) -> None:
        sent_keys: list[str] = []
        sleeps: list[float] = []
        state = {"stage": "picker"}
        queued_text = "$envctl-continue-task"

        def read_surface_screen_fn(_runtime, **_kwargs):  # noqa: ANN001, ANN003, ANN202
            if state["stage"] == "picker":
                return (
                    "OpenAI Codex\n"
                    "› $envctl-continue-task\n"
                    "  Envctl Continue Task [Skill]\n"
                    "  Press enter to insert or esc to close\n"
                )
            if state["stage"] == "typed":
                return "OpenAI Codex\n  $envctl-continue-task\n  tab to queue message\n"
            return "OpenAI Codex\n• Queued follow-up messages\n"

        def send_surface_key_fn(_runtime, **kwargs):  # noqa: ANN001, ANN003, ANN202
            sent_keys.append(kwargs["key"])
            if kwargs["key"] == "enter":
                state["stage"] = "typed"
            if kwargs["key"] == "tab":
                state["stage"] = "queued"
            return None

        queued = queue_codex_message(
            SimpleNamespace(),
            workspace_id="workspace:1",
            surface_id="surface:2",
            text=queued_text,
            read_surface_screen_fn=read_surface_screen_fn,
            send_surface_key_fn=send_surface_key_fn,
            monotonic=iter([0.0, 0.1, 0.2, 0.3, 0.4]).__next__,
            sleep=sleeps.append,
        )

        self.assertTrue(queued)
        self.assertEqual(sent_keys, ["enter", "tab"])
        self.assertEqual(sleeps, [0.1, 0.1])

    def test_wait_for_codex_queue_ready_accepts_injected_clock_for_wrapper_compatibility(self) -> None:
        ready_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "› follow-up prompt\n"
        )
        screens = iter(["busy", "busy", ready_screen])
        sleeps: list[float] = []

        ready = wait_for_codex_queue_ready(
            SimpleNamespace(),
            workspace_id="workspace:1",
            surface_id="surface:2",
            read_surface_screen_fn=lambda _runtime, **_kwargs: next(screens),  # noqa: ANN001, ANN003
            monotonic=iter([0.0, 0.1, 0.2, 0.3, 0.4]).__next__,
            sleep=sleeps.append,
        )

        self.assertTrue(ready)
        self.assertEqual(sleeps, [0.1, 0.1])


if __name__ == "__main__":
    unittest.main()
