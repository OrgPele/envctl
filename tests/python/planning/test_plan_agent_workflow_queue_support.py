from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
    _PlanAgentWorkflowStep,
)
from envctl_engine.planning.plan_agent.workflow_queue_support import (
    run_codex_workflow_queue,
)


def _launch_config(*, codex_goal_enable: bool = True) -> PlanAgentLaunchConfig:
    return PlanAgentLaunchConfig(
        enabled=True,
        transport="tmux",
        cli="codex",
        cli_command="codex",
        preset="implementation",
        codex_cycles=2,
        codex_cycles_warning=None,
        shell="/bin/zsh",
        require_cmux_context=False,
        cmux_workspace="",
        direct_prompt_enabled=False,
        ulw_loop_prefix=True,
        ulw_suffix=True,
        codex_goal_enable=codex_goal_enable,
    )


class PlanAgentWorkflowQueueSupportTests(unittest.TestCase):
    def test_queue_support_preserves_goal_before_required_prompt_and_emits_transport_context(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        sent: list[str] = []
        confirmed: list[tuple[str, bool]] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))
        worktree = CreatedPlanWorktree(name="feature-a-1", root=Path("/repo/trees/feature-a/1"), plan_file="a.md")
        workflow = _PlanAgentWorkflow(
            mode="codex_cycles",
            codex_cycles=2,
            steps=(_PlanAgentWorkflowStep(kind="queue_direct_prompt", text="cycle", requires_goal=True),),
        )

        error = run_codex_workflow_queue(
            runtime,
            worktree=worktree,
            workflow=workflow,
            queued_steps=workflow.steps,
            launch_config=_launch_config(),
            cli="codex",
            transport="tmux",
            event_context={"session_name": "envctl-session", "window_name": "feature-a-1"},
            codex_goal_text_for_worktree_fn=lambda **_kwargs: "goal text",
            workflow_step_prompt_text_fn=lambda *_args, **_kwargs: ("prompt text", None),
            send_text_fn=lambda text: sent.append(text) or None,
            queue_message_fn=lambda text, *, require_text_match: confirmed.append((text, require_text_match)) or True,
        )

        self.assertIsNone(error)
        self.assertEqual(sent, ["/goal goal text", "prompt text"])
        self.assertEqual(confirmed, [("/goal goal text", False), ("prompt text", False)])
        self.assertEqual(
            events,
            [
                (
                    "planning.agent_launch.workflow_queued",
                    {
                        "session_name": "envctl-session",
                        "window_name": "feature-a-1",
                        "worktree": "feature-a-1",
                        "cli": "codex",
                        "workflow_mode": "codex_cycles",
                        "codex_cycles": 2,
                        "queued_steps": 1,
                        "queued_steps_confirmed": 1,
                        "transport": "tmux",
                    },
                )
            ],
        )

    def test_queue_support_returns_structured_failure_for_prompt_resolution_error(self) -> None:
        runtime = SimpleNamespace(_emit=lambda *_args, **_kwargs: None)
        worktree = CreatedPlanWorktree(name="feature-a-1", root=Path("/repo/trees/feature-a/1"), plan_file="a.md")
        workflow = _PlanAgentWorkflow(
            mode="codex_cycles",
            codex_cycles=1,
            steps=(_PlanAgentWorkflowStep(kind="queue_direct_prompt", text="cycle"),),
        )

        error = run_codex_workflow_queue(
            runtime,
            worktree=worktree,
            workflow=workflow,
            queued_steps=workflow.steps,
            launch_config=_launch_config(),
            cli="codex",
            transport="cmux",
            event_context={"workspace_id": "workspace:1", "surface_id": "surface:2"},
            codex_goal_text_for_worktree_fn=lambda **_kwargs: "goal text",
            workflow_step_prompt_text_fn=lambda *_args, **_kwargs: ("", "missing prompt"),
            send_text_fn=lambda _text: None,
            queue_message_fn=lambda _text, *, require_text_match: True,
        )

        self.assertEqual(error, "queue_prompt_resolution_failed")
        self.assertEqual(error.step_index, 0)
        self.assertEqual(error.step_kind, "queue_direct_prompt")


if __name__ == "__main__":
    unittest.main()
