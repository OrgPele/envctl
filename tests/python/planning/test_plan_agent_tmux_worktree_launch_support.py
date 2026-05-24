from __future__ import annotations

from pathlib import Path
import unittest

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree, PlanAgentLaunchConfig, _PlanAgentWorkflow
from envctl_engine.planning.plan_agent import tmux_worktree_launch_support


def _launch_config() -> PlanAgentLaunchConfig:
    return PlanAgentLaunchConfig(
        enabled=True,
        transport="tmux",
        cli="codex",
        cli_command="codex",
        preset="default",
        codex_cycles=2,
        codex_cycles_warning=None,
        shell="zsh",
        require_cmux_context=False,
        cmux_workspace="",
        direct_prompt_enabled=False,
        ulw_loop_prefix=True,
        ulw_suffix=True,
    )


def _workflow() -> _PlanAgentWorkflow:
    return _PlanAgentWorkflow(mode="queued", codex_cycles=2, steps=())


def _worktree() -> CreatedPlanWorktree:
    return CreatedPlanWorktree(name="feature-a-1", root=Path("/repo/trees/feature-a/1"), plan_file="feature-a.md")


class _Runtime:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, payload))


class PlanAgentTmuxWorktreeLaunchSupportTests(unittest.TestCase):
    def test_launch_single_tmux_worktree_reports_window_create_failure(self) -> None:
        runtime = _Runtime()

        outcome = tmux_worktree_launch_support.launch_single_tmux_worktree(
            runtime,
            session_name="envctl-feature",
            window_name="feature-a-1",
            launch_config=_launch_config(),
            workflow=_workflow(),
            worktree=_worktree(),
            ensure_tmux_window_fn=lambda *_args, **_kwargs: "create failed",
            run_tmux_worktree_bootstrap_fn=lambda *_args, **_kwargs: None,
            persist_runtime_events_snapshot_fn=lambda _runtime: None,
        )

        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.reason, "create failed")
        self.assertEqual(outcome.worktree_name, "feature-a-1")
        self.assertEqual(runtime.events[0][0], "planning.agent_launch.failed")
        self.assertEqual(runtime.events[0][1]["reason"], "window_create_failed")
        self.assertEqual(runtime.events[0][1]["transport"], "tmux")

    def test_launch_single_tmux_worktree_reports_bootstrap_failure_after_surface_created(self) -> None:
        runtime = _Runtime()

        outcome = tmux_worktree_launch_support.launch_single_tmux_worktree(
            runtime,
            session_name="envctl-feature",
            window_name="feature-a-1",
            launch_config=_launch_config(),
            workflow=_workflow(),
            worktree=_worktree(),
            ensure_tmux_window_fn=lambda *_args, **_kwargs: None,
            run_tmux_worktree_bootstrap_fn=lambda *_args, **_kwargs: "bootstrap failed",
            persist_runtime_events_snapshot_fn=lambda _runtime: None,
        )

        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.reason, "bootstrap failed")
        self.assertEqual([event for event, _payload in runtime.events], ["planning.agent_launch.surface_created", "planning.agent_launch.failed"])
        self.assertEqual(runtime.events[1][1]["reason"], "bootstrap_failed")

    def test_launch_single_tmux_worktree_emits_success_and_persists_event_snapshot(self) -> None:
        runtime = _Runtime()
        persisted: list[object] = []

        outcome = tmux_worktree_launch_support.launch_single_tmux_worktree(
            runtime,
            session_name="envctl-feature",
            window_name="feature-a-1",
            launch_config=_launch_config(),
            workflow=_workflow(),
            worktree=_worktree(),
            ensure_tmux_window_fn=lambda *_args, **_kwargs: None,
            run_tmux_worktree_bootstrap_fn=lambda *_args, **_kwargs: None,
            persist_runtime_events_snapshot_fn=persisted.append,
        )

        self.assertEqual(outcome.status, "launched")
        self.assertEqual(outcome.reason, None)
        self.assertEqual([event for event, _payload in runtime.events], ["planning.agent_launch.surface_created", "planning.agent_launch.command_sent"])
        self.assertEqual(runtime.events[1][1]["preset"], "default")
        self.assertEqual(runtime.events[1][1]["workflow_mode"], "queued")
        self.assertEqual(runtime.events[1][1]["codex_cycles"], 2)
        self.assertEqual(runtime.events[1][1]["transport"], "tmux")
        self.assertEqual(persisted, [runtime])


if __name__ == "__main__":
    unittest.main()
