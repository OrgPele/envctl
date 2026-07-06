from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
    _PlanAgentWorkflowStep,
    _QueueFailure,
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
        assert isinstance(error, _QueueFailure)
        self.assertEqual(error.step_index, 0)
        self.assertEqual(error.step_kind, "queue_direct_prompt")

    def test_queue_support_sends_multiline_prompt_as_single_file_backed_queue_message(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        sent: list[str] = []
        confirmed: list[tuple[str, bool]] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))
        queued_prompt = "First, read MAIN_TASK.md.\nThen inspect relevant code before editing.\n"
        workflow = _PlanAgentWorkflow(
            mode="codex_cycles",
            codex_cycles=1,
            steps=(_PlanAgentWorkflowStep(kind="queue_direct_prompt", text="cycle"),),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            worktree_root = Path(tmpdir) / "repo"
            worktree_root.mkdir(parents=True, exist_ok=True)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")

            error = run_codex_workflow_queue(
                runtime,
                worktree=worktree,
                workflow=workflow,
                queued_steps=workflow.steps,
                launch_config=_launch_config(codex_goal_enable=False),
                cli="codex",
                transport="cmux",
                event_context={"workspace_id": "workspace:1", "surface_id": "surface:2"},
                codex_goal_text_for_worktree_fn=lambda **_kwargs: "goal text",
                workflow_step_prompt_text_fn=lambda *_args, **_kwargs: (queued_prompt, None),
                send_text_fn=lambda text: sent.append(text) or None,
                queue_message_fn=lambda text, *, require_text_match: confirmed.append((text, require_text_match))
                or True,
            )

            expected_queue_text = (
                "Read and follow the queued follow-up prompt from the current worktree: "
                ".envctl-state/plan-agent-queue/000-queue-direct-prompt.md"
            )
            prompt_file = worktree_root / ".envctl-state" / "plan-agent-queue" / "000-queue-direct-prompt.md"

            self.assertIsNone(error)
            self.assertEqual(sent, [expected_queue_text])
            self.assertNotIn("\n", sent[0])
            self.assertEqual(confirmed, [(expected_queue_text, False)])
            self.assertEqual(prompt_file.read_text(encoding="utf-8"), queued_prompt)


if __name__ == "__main__":
    unittest.main()
