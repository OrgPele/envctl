from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.planning.plan_agent.cmux_goal_support import (
    maybe_submit_surface_codex_goal,
    submit_surface_codex_goal,
)
from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
    _PlanAgentWorkflowStep,
)


def _launch_config(*, cli: str = "codex", codex_goal_enable: bool = True) -> PlanAgentLaunchConfig:
    return PlanAgentLaunchConfig(
        enabled=True,
        transport="cmux",
        cli=cli,
        cli_command=cli,
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


class PlanAgentCmuxGoalSupportTests(unittest.TestCase):
    def test_maybe_submit_surface_codex_goal_skips_non_codex_or_disabled_goal(self) -> None:
        calls: list[str] = []
        runtime = SimpleNamespace()
        worktree = CreatedPlanWorktree(name="feature-a-1", root=Path("/repo/trees/feature-a/1"), plan_file="a.md")
        workflow = _PlanAgentWorkflow(
            mode="single",
            codex_cycles=1,
            steps=(_PlanAgentWorkflowStep(kind="submit_prompt", text="implement"),),
        )

        for launch_config in (
            _launch_config(cli="opencode", codex_goal_enable=True),
            _launch_config(cli="codex", codex_goal_enable=False),
        ):
            self.assertIsNone(
                maybe_submit_surface_codex_goal(
                    runtime,
                    workspace_id="workspace:1",
                    surface_id="surface:2",
                    launch_config=launch_config,
                    workflow=workflow,
                    worktree=worktree,
                    codex_goal_text_for_worktree_fn=lambda **_kwargs: calls.append("goal") or "goal text",
                    submit_surface_codex_goal_fn=lambda *_args, **_kwargs: calls.append("submit") or None,
                    emit_codex_goal_event_fn=lambda *_args, **_kwargs: calls.append("emit"),
                )
            )

        self.assertEqual(calls, [])

    def test_maybe_submit_surface_codex_goal_emits_submitted_event(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace()
        worktree = CreatedPlanWorktree(name="feature-a-1", root=Path("/repo/trees/feature-a/1"), plan_file="a.md")
        workflow = _PlanAgentWorkflow(
            mode="ulw",
            codex_cycles=2,
            steps=(_PlanAgentWorkflowStep(kind="submit_prompt", text="implement"),),
        )

        error = maybe_submit_surface_codex_goal(
            runtime,
            workspace_id="workspace:1",
            surface_id="surface:2",
            launch_config=_launch_config(),
            workflow=workflow,
            worktree=worktree,
            codex_goal_text_for_worktree_fn=lambda **_kwargs: "goal text",
            submit_surface_codex_goal_fn=lambda *_args, **kwargs: None,
            emit_codex_goal_event_fn=lambda _runtime, event, **payload: events.append((event, payload)),
        )

        self.assertIsNone(error)
        self.assertEqual(events[0][0], "planning.agent_launch.codex_goal_submitted")
        self.assertEqual(events[0][1]["transport"], "cmux")
        self.assertEqual(events[0][1]["worktree"], worktree)

    def test_maybe_submit_surface_codex_goal_emits_fallback_on_ready_timeout(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace()
        worktree = CreatedPlanWorktree(name="feature-a-1", root=Path("/repo/trees/feature-a/1"), plan_file="a.md")
        workflow = _PlanAgentWorkflow(
            mode="single",
            codex_cycles=1,
            steps=(_PlanAgentWorkflowStep(kind="submit_prompt", text="implement"),),
        )

        error = maybe_submit_surface_codex_goal(
            runtime,
            workspace_id="workspace:1",
            surface_id="surface:2",
            launch_config=_launch_config(),
            workflow=workflow,
            worktree=worktree,
            codex_goal_text_for_worktree_fn=lambda **_kwargs: "goal text",
            submit_surface_codex_goal_fn=lambda *_args, **_kwargs: "codex_goal_ready_timeout",
            emit_codex_goal_event_fn=lambda _runtime, event, **payload: events.append((event, payload)),
        )

        self.assertEqual(error, "codex_goal_ready_timeout")
        self.assertEqual(events[0][0], "planning.agent_launch.codex_goal_fallback")
        self.assertEqual(events[0][1]["reason"], "codex_goal_ready_timeout")

    def test_submit_surface_codex_goal_requires_active_goal_before_queue_ready(self) -> None:
        calls: list[str] = []

        error = submit_surface_codex_goal(
            SimpleNamespace(),
            workspace_id="workspace:1",
            surface_id="surface:2",
            goal_text="Implement this task",
            submit_direct_prompt_workflow_step_fn=lambda *_args, **kwargs: calls.append(kwargs["prompt_text"]) or None,
            wait_for_surface_codex_goal_active_fn=lambda *_args, **_kwargs: False,
            wait_for_codex_queue_ready_fn=lambda *_args, **_kwargs: calls.append("queue-ready") or True,
        )

        self.assertEqual(error, "codex_goal_active_timeout")
        self.assertEqual(calls, ["/go Implement this task"])


if __name__ == "__main__":
    unittest.main()
