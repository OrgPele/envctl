from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentAttachTarget,
    PlanAgentAttachValidation,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
    _PlanAgentWorkflowStep,
)
from envctl_engine.planning.plan_agent.omx_launch_support import launch_omx_terminals


def _launch_config(*, cli: str = "codex") -> PlanAgentLaunchConfig:
    return PlanAgentLaunchConfig(
        enabled=True,
        transport="omx",
        cli=cli,
        cli_command=cli,
        preset="implement_task",
        codex_cycles=1,
        codex_cycles_warning=None,
        shell="zsh",
        require_cmux_context=True,
        cmux_workspace="",
        direct_prompt_enabled=False,
        ulw_loop_prefix=False,
        ulw_suffix=False,
        omx_workflow="ralph",
    )


def _workflow() -> _PlanAgentWorkflow:
    return _PlanAgentWorkflow(
        mode="single",
        codex_cycles=1,
        steps=(_PlanAgentWorkflowStep(kind="submit_prompt", text="body"),),
    )


def _worktree(name: str = "feature-a-1") -> CreatedPlanWorktree:
    return CreatedPlanWorktree(name=name, root=Path(f"/repo/trees/{name}"), plan_file="feature-a.md")


def _attach_target(name: str = "omx-feature-a") -> PlanAgentAttachTarget:
    return PlanAgentAttachTarget(
        repo_root=Path("/repo"),
        session_name=name,
        window_name="%42",
        attach_via="attach-session",
        attach_command=("tmux", "attach", "-t", name),
    )


class _Runtime:
    def __init__(self) -> None:
        self.config = SimpleNamespace(base_dir="/repo")
        self.env: dict[str, str] = {}
        self.events: list[tuple[str, dict[str, object]]] = []
        self.snapshots = 0

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, payload))


class PlanAgentOmxLaunchSupportTests(unittest.TestCase):
    def test_rejects_non_codex_cli_before_session_work(self) -> None:
        runtime = _Runtime()

        result = launch_omx_terminals(
            runtime,
            route=SimpleNamespace(flags={}),
            launch_config=_launch_config(cli="opencode"),
            workflow=_workflow(),
            created_worktrees=(_worktree(),),
            base_payload={"plan": "feature-a.md"},
            prompt_on_existing=False,
            find_existing_attach_target_fn=lambda *_args, **_kwargs: self.fail("should not inspect sessions"),
            should_prompt_existing_session_fn=lambda *_args, **_kwargs: False,
            prompt_existing_session_action_fn=lambda *_args, **_kwargs: "new",
            new_session_command_for_route_fn=lambda *_args, **_kwargs: ("envctl", "plan", "--omx"),
            read_omx_session_id_fn=lambda *_args, **_kwargs: None,
            read_omx_session_ids_fn=lambda *_args, **_kwargs: (),
            find_omx_tmux_panes_for_worktree_fn=lambda *_args, **_kwargs: (),
            spawn_omx_session_for_worktree_fn=lambda *_args, **_kwargs: None,
            wait_for_omx_attach_target_fn=lambda *_args, **_kwargs: None,
            attach_discovery_diagnostics_fn=lambda *_args, **_kwargs: {},
            run_tmux_existing_session_workflow_fn=lambda *_args, **_kwargs: None,
            validate_plan_agent_attach_target_fn=lambda *_args, **_kwargs: PlanAgentAttachValidation(ok=True, reason=""),
            mark_worktree_plan_agent_launch_fn=lambda *_args, **_kwargs: None,
            persist_runtime_events_snapshot_fn=lambda _runtime: None,
            summarize_failed_launch_outcomes_fn=lambda _failed: "",
            print_launch_summary_fn=lambda _message: None,
            plan_agent_native_recovery_command_fn=lambda *_args, **_kwargs: (),
            plan_agent_recovery_command_text_fn=lambda _command: "",
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "unsupported_omx_cli")
        self.assertEqual(runtime.events, [("planning.agent_launch.failed", {"reason": "unsupported_omx_cli", "plan": "feature-a.md"})])

    def test_existing_session_returns_attach_guidance_without_new_session(self) -> None:
        runtime = _Runtime()
        existing = _attach_target()

        result = launch_omx_terminals(
            runtime,
            route=SimpleNamespace(flags={}),
            launch_config=_launch_config(),
            workflow=_workflow(),
            created_worktrees=(_worktree(),),
            base_payload={},
            prompt_on_existing=False,
            find_existing_attach_target_fn=lambda *_args, **_kwargs: existing,
            should_prompt_existing_session_fn=lambda *_args, **_kwargs: False,
            prompt_existing_session_action_fn=lambda *_args, **_kwargs: "new",
            new_session_command_for_route_fn=lambda *_args, **_kwargs: ("envctl", "plan", "--omx", "--new-session"),
            read_omx_session_id_fn=lambda *_args, **_kwargs: None,
            read_omx_session_ids_fn=lambda *_args, **_kwargs: (),
            find_omx_tmux_panes_for_worktree_fn=lambda *_args, **_kwargs: (),
            spawn_omx_session_for_worktree_fn=lambda *_args, **_kwargs: None,
            wait_for_omx_attach_target_fn=lambda *_args, **_kwargs: None,
            attach_discovery_diagnostics_fn=lambda *_args, **_kwargs: {},
            run_tmux_existing_session_workflow_fn=lambda *_args, **_kwargs: None,
            validate_plan_agent_attach_target_fn=lambda *_args, **_kwargs: PlanAgentAttachValidation(ok=True, reason=""),
            mark_worktree_plan_agent_launch_fn=lambda *_args, **_kwargs: None,
            persist_runtime_events_snapshot_fn=lambda _runtime: None,
            summarize_failed_launch_outcomes_fn=lambda _failed: "",
            print_launch_summary_fn=lambda _message: None,
            plan_agent_native_recovery_command_fn=lambda *_args, **_kwargs: (),
            plan_agent_recovery_command_text_fn=lambda _command: "",
        )

        self.assertEqual(result.status, "failed")
        self.assertIn("already exists", result.reason or "")
        self.assertEqual(result.attach_target.session_name if result.attach_target else None, "omx-feature-a")
        self.assertEqual(result.attach_target.new_session_command if result.attach_target else None, ("envctl", "plan", "--omx", "--new-session"))
        self.assertEqual(runtime.events[0][0], "planning.agent_launch.skipped")
        self.assertEqual(runtime.events[0][1]["reason"], "existing_omx_session")

    def test_launches_worktree_after_spawn_attach_bootstrap_and_validation(self) -> None:
        runtime = _Runtime()
        worktree = _worktree()
        target = _attach_target()
        marked: list[tuple[str, str, str]] = []
        snapshots: list[object] = []

        result = launch_omx_terminals(
            runtime,
            route=SimpleNamespace(flags={}),
            launch_config=_launch_config(),
            workflow=_workflow(),
            created_worktrees=(worktree,),
            base_payload={},
            prompt_on_existing=False,
            find_existing_attach_target_fn=lambda *_args, **_kwargs: None,
            should_prompt_existing_session_fn=lambda *_args, **_kwargs: False,
            prompt_existing_session_action_fn=lambda *_args, **_kwargs: "new",
            new_session_command_for_route_fn=lambda *_args, **_kwargs: (),
            read_omx_session_id_fn=lambda *_args, **_kwargs: "old",
            read_omx_session_ids_fn=lambda *_args, **_kwargs: ("old",),
            find_omx_tmux_panes_for_worktree_fn=lambda *_args, **_kwargs: (),
            spawn_omx_session_for_worktree_fn=lambda *_args, **_kwargs: None,
            wait_for_omx_attach_target_fn=lambda *_args, **_kwargs: target,
            attach_discovery_diagnostics_fn=lambda *_args, **_kwargs: {},
            run_tmux_existing_session_workflow_fn=lambda *_args, **_kwargs: None,
            validate_plan_agent_attach_target_fn=lambda *_args, **_kwargs: PlanAgentAttachValidation(ok=True, reason=""),
            mark_worktree_plan_agent_launch_fn=lambda item, *, status, transport, session_name: marked.append((item.name, status, session_name)),
            persist_runtime_events_snapshot_fn=lambda item: snapshots.append(item),
            summarize_failed_launch_outcomes_fn=lambda _failed: "",
            print_launch_summary_fn=lambda _message: None,
            plan_agent_native_recovery_command_fn=lambda *_args, **_kwargs: (),
            plan_agent_recovery_command_text_fn=lambda _command: "",
        )

        self.assertEqual(result.status, "launched")
        self.assertEqual(result.attach_target, target)
        self.assertEqual(marked, [("feature-a-1", "launched", "omx-feature-a")])
        self.assertEqual(snapshots, [runtime])
        event_names = [event for event, _payload in runtime.events]
        self.assertIn("planning.agent_launch.evaluate", event_names)
        self.assertIn("planning.agent_launch.surface_created", event_names)
        self.assertIn("planning.agent_launch.command_sent", event_names)

    def test_mixed_worktree_results_return_partial_with_recovery_guidance(self) -> None:
        runtime = _Runtime()
        first = _worktree("feature-a-1")
        second = _worktree("feature-b-1")
        summaries: list[str] = []

        result = launch_omx_terminals(
            runtime,
            route=SimpleNamespace(flags={"new_session": True}),
            launch_config=_launch_config(),
            workflow=_workflow(),
            created_worktrees=(first, second),
            base_payload={},
            prompt_on_existing=False,
            find_existing_attach_target_fn=lambda *_args, **_kwargs: None,
            should_prompt_existing_session_fn=lambda *_args, **_kwargs: False,
            prompt_existing_session_action_fn=lambda *_args, **_kwargs: "new",
            new_session_command_for_route_fn=lambda *_args, **_kwargs: (),
            read_omx_session_id_fn=lambda *_args, **_kwargs: None,
            read_omx_session_ids_fn=lambda *_args, **_kwargs: (),
            find_omx_tmux_panes_for_worktree_fn=lambda *_args, **_kwargs: (),
            spawn_omx_session_for_worktree_fn=lambda _runtime, *, worktree, **_kwargs: "spawn failed" if worktree is second else None,
            wait_for_omx_attach_target_fn=lambda _runtime, *, worktree, **_kwargs: _attach_target(f"omx-{worktree.name}"),
            attach_discovery_diagnostics_fn=lambda *_args, **_kwargs: {},
            run_tmux_existing_session_workflow_fn=lambda *_args, **_kwargs: None,
            validate_plan_agent_attach_target_fn=lambda *_args, **_kwargs: PlanAgentAttachValidation(ok=True, reason=""),
            mark_worktree_plan_agent_launch_fn=lambda *_args, **_kwargs: None,
            persist_runtime_events_snapshot_fn=lambda _runtime: None,
            summarize_failed_launch_outcomes_fn=lambda _failed: "feature-b-1: spawn failed",
            print_launch_summary_fn=lambda message: summaries.append(message),
            plan_agent_native_recovery_command_fn=lambda *_args, **_kwargs: ("envctl", "plan", "--omx"),
            plan_agent_recovery_command_text_fn=lambda command: " ".join(command),
        )

        self.assertEqual(result.status, "partial")
        self.assertEqual([outcome.status for outcome in result.outcomes], ["launched", "failed"])
        self.assertIn("partial success", summaries[0])
        self.assertEqual(summaries[1], "recovery: envctl plan --omx")


if __name__ == "__main__":
    unittest.main()
