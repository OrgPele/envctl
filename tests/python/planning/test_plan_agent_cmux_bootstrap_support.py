from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.planning.plan_agent.cmux_bootstrap_support import (
    complete_review_surface_bootstrap,
    complete_surface_bootstrap,
    start_background_review_surface_bootstrap,
    start_background_surface_bootstrap,
)
from envctl_engine.planning.plan_agent.constants import _REVIEW_WORKTREE_PRESET
from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
    _PlanAgentWorkflowStep,
)


def _launch_config() -> PlanAgentLaunchConfig:
    return PlanAgentLaunchConfig(
        enabled=True,
        transport="cmux",
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
    )


class _RecordingThread:
    created: list["_RecordingThread"] = []

    def __init__(self, *, target, kwargs, name: str, daemon: bool):  # noqa: ANN001
        self.target = target
        self.kwargs = kwargs
        self.name = name
        self.daemon = daemon
        self.started = False
        self.created.append(self)

    def start(self) -> None:
        self.started = True


class PlanAgentCmuxBootstrapSupportTests(unittest.TestCase):
    def test_start_background_surface_bootstrap_names_non_daemon_thread(self) -> None:
        _RecordingThread.created = []
        runtime = SimpleNamespace()
        launch_config = _launch_config()
        worktree = CreatedPlanWorktree(name="feature-a-1", root=Path("/repo/trees/feature-a/1"), plan_file="a.md")

        start_background_surface_bootstrap(
            runtime,
            workspace_id="workspace:1",
            surface_id="surface:2",
            launch_config=launch_config,
            worktree=worktree,
            complete_surface_bootstrap_fn=lambda *_args, **_kwargs: None,
            thread_factory=_RecordingThread,
        )

        thread = _RecordingThread.created[0]
        self.assertTrue(thread.started)
        self.assertFalse(thread.daemon)
        self.assertEqual(thread.name, "envctl-plan-agent-feature-a-1")
        self.assertEqual(thread.kwargs["worktree"], worktree)

    def test_complete_surface_bootstrap_emits_success_and_persists_snapshot(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        persisted: list[object] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))
        launch_config = _launch_config()
        worktree = CreatedPlanWorktree(name="feature-a-1", root=Path("/repo/trees/feature-a/1"), plan_file="a.md")
        workflow = _PlanAgentWorkflow(
            mode="ulw",
            codex_cycles=2,
            steps=(_PlanAgentWorkflowStep(kind="submit_prompt", text="implement"),),
        )

        complete_surface_bootstrap(
            runtime,
            workspace_id="workspace:1",
            surface_id="surface:2",
            launch_config=launch_config,
            worktree=worktree,
            build_plan_agent_workflow_fn=lambda **_kwargs: workflow,
            run_surface_bootstrap_fn=lambda *_args, **_kwargs: None,
            persist_runtime_events_snapshot_fn=lambda _runtime: persisted.append(_runtime),
        )

        self.assertEqual(events[0][0], "planning.agent_launch.command_sent")
        self.assertEqual(events[0][1]["workflow_mode"], "ulw")
        self.assertEqual(events[0][1]["codex_cycles"], 2)
        self.assertEqual(persisted, [runtime])

    def test_complete_surface_bootstrap_emits_failure_and_persists_snapshot(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        persisted: list[object] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))
        launch_config = _launch_config()
        worktree = CreatedPlanWorktree(name="feature-a-1", root=Path("/repo/trees/feature-a/1"), plan_file="a.md")
        workflow = _PlanAgentWorkflow(mode="single", codex_cycles=1, steps=())

        complete_surface_bootstrap(
            runtime,
            workspace_id="workspace:1",
            surface_id="surface:2",
            launch_config=launch_config,
            worktree=worktree,
            build_plan_agent_workflow_fn=lambda **_kwargs: workflow,
            run_surface_bootstrap_fn=lambda *_args, **_kwargs: "boom",
            persist_runtime_events_snapshot_fn=lambda _runtime: persisted.append(_runtime),
        )

        self.assertEqual(events[0][0], "planning.agent_launch.failed")
        self.assertEqual(events[0][1]["reason"], "bootstrap_failed")
        self.assertEqual(events[0][1]["error"], "boom")
        self.assertEqual(persisted, [runtime])

    def test_review_bootstrap_uses_review_event_contract(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runtime = SimpleNamespace(_emit=lambda event, **payload: events.append((event, payload)))

        complete_review_surface_bootstrap(
            runtime,
            workspace_id="workspace:1",
            surface_id="surface:2",
            launch_config=_launch_config(),
            repo_root=Path("/repo"),
            project_name="Main",
            project_root=Path("/repo"),
            review_bundle_path=None,
            run_review_surface_bootstrap_fn=lambda *_args, **_kwargs: None,
            persist_runtime_events_snapshot_fn=lambda _runtime: None,
        )

        self.assertEqual(events[0][0], "dashboard.review_tab.command_sent")
        self.assertEqual(events[0][1]["project"], "Main")
        self.assertEqual(events[0][1]["preset"], _REVIEW_WORKTREE_PRESET)

    def test_start_background_review_surface_bootstrap_names_non_daemon_thread(self) -> None:
        _RecordingThread.created = []
        runtime = SimpleNamespace()

        start_background_review_surface_bootstrap(
            runtime,
            workspace_id="workspace:1",
            surface_id="surface:2",
            launch_config=_launch_config(),
            repo_root=Path("/repo"),
            project_name="Main",
            project_root=Path("/repo/project"),
            review_bundle_path=None,
            complete_review_surface_bootstrap_fn=lambda *_args, **_kwargs: None,
            thread_factory=_RecordingThread,
        )

        thread = _RecordingThread.created[0]
        self.assertTrue(thread.started)
        self.assertFalse(thread.daemon)
        self.assertEqual(thread.name, "envctl-review-agent-Main")
        self.assertEqual(thread.kwargs["project_name"], "Main")


if __name__ == "__main__":
    unittest.main()
