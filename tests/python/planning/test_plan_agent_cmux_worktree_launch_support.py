from __future__ import annotations

from pathlib import Path
import unittest

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree, PlanAgentLaunchConfig
from envctl_engine.planning.plan_agent import cmux_worktree_launch_support


def _launch_config() -> PlanAgentLaunchConfig:
    return PlanAgentLaunchConfig(
        enabled=True,
        transport="cmux",
        cli="codex",
        cli_command="codex",
        preset="default",
        codex_cycles=1,
        codex_cycles_warning=None,
        shell="zsh",
        require_cmux_context=False,
        cmux_workspace="",
        direct_prompt_enabled=False,
        ulw_loop_prefix=True,
        ulw_suffix=True,
    )


def _worktree() -> CreatedPlanWorktree:
    return CreatedPlanWorktree(name="feature-a-1", root=Path("/repo/trees/feature-a/1"), plan_file="feature-a.md")


class _Runtime:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, payload))


class PlanAgentCmuxWorktreeLaunchSupportTests(unittest.TestCase):
    def test_launch_single_worktree_reports_surface_create_failure(self) -> None:
        runtime = _Runtime()

        outcome = cmux_worktree_launch_support.launch_single_worktree(
            runtime,
            workspace_id="workspace-1",
            launch_config=_launch_config(),
            worktree=_worktree(),
            starter_surface_id=None,
            create_surface_fn=lambda *_args, **_kwargs: (None, "create failed"),
            start_background_surface_bootstrap_fn=lambda *_args, **_kwargs: None,
        )

        self.assertEqual(outcome.status, "failed")
        self.assertEqual(outcome.reason, "create failed")
        self.assertEqual(outcome.workspace_id, "workspace-1")
        self.assertEqual(runtime.events[0][0], "planning.agent_launch.failed")
        self.assertEqual(runtime.events[0][1]["reason"], "surface_create_failed")
        self.assertEqual(runtime.events[0][1]["workspace_id"], "workspace-1")

    def test_launch_single_worktree_reuses_starter_surface_without_creating_surface(self) -> None:
        runtime = _Runtime()
        create_calls: list[str] = []
        bootstrap_calls: list[dict[str, object]] = []

        outcome = cmux_worktree_launch_support.launch_single_worktree(
            runtime,
            workspace_id="workspace-1",
            launch_config=_launch_config(),
            worktree=_worktree(),
            starter_surface_id="surface-1",
            create_surface_fn=lambda *_args, **_kwargs: create_calls.append("create") or ("created", None),
            start_background_surface_bootstrap_fn=lambda *_runtime, **kwargs: bootstrap_calls.append(kwargs),
        )

        self.assertEqual(outcome.status, "launched")
        self.assertEqual(outcome.surface_id, "surface-1")
        self.assertEqual(outcome.workspace_id, "workspace-1")
        self.assertEqual(create_calls, [])
        self.assertEqual(runtime.events[0][0], "planning.agent_launch.surface_created")
        self.assertEqual(runtime.events[0][1]["source"], "starter_reused")
        self.assertEqual(bootstrap_calls[0]["surface_id"], "surface-1")

    def test_launch_single_worktree_creates_surface_and_starts_bootstrap(self) -> None:
        runtime = _Runtime()
        bootstrap_calls: list[dict[str, object]] = []

        outcome = cmux_worktree_launch_support.launch_single_worktree(
            runtime,
            workspace_id="workspace-1",
            launch_config=_launch_config(),
            worktree=_worktree(),
            starter_surface_id=None,
            create_surface_fn=lambda *_args, **_kwargs: ("surface-2", None),
            start_background_surface_bootstrap_fn=lambda *_runtime, **kwargs: bootstrap_calls.append(kwargs),
        )

        self.assertEqual(outcome.status, "launched")
        self.assertEqual(outcome.surface_id, "surface-2")
        self.assertEqual(outcome.workspace_id, "workspace-1")
        self.assertEqual(runtime.events[0][1]["source"], "new_surface")
        self.assertEqual(bootstrap_calls[0]["workspace_id"], "workspace-1")
        self.assertEqual(bootstrap_calls[0]["surface_id"], "surface-2")


if __name__ == "__main__":
    unittest.main()
