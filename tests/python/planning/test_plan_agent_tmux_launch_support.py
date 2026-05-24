from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentAttachTarget,
    PlanAgentLaunchConfig,
    PlanAgentLaunchOutcome,
    _PlanAgentWorkflow,
    _PlanAgentWorkflowStep,
)
from envctl_engine.planning.plan_agent.tmux_launch_support import launch_tmux_terminals


def _launch_config(*, cli: str = "codex") -> PlanAgentLaunchConfig:
    return PlanAgentLaunchConfig(
        enabled=True,
        transport="tmux",
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
    )


def _workflow() -> _PlanAgentWorkflow:
    return _PlanAgentWorkflow(
        mode="single",
        codex_cycles=1,
        steps=(_PlanAgentWorkflowStep(kind="submit_prompt", text="body"),),
    )


def _worktree(name: str = "feature-a-1") -> CreatedPlanWorktree:
    return CreatedPlanWorktree(name=name, root=Path(f"/repo/trees/{name}"), plan_file="feature-a.md")


def _attach_target(name: str = "envctl-feature-a") -> PlanAgentAttachTarget:
    return PlanAgentAttachTarget(
        repo_root=Path("/repo"),
        session_name=name,
        window_name="feature-a",
        attach_via="attach-session",
        attach_command=("tmux", "attach", "-t", name),
    )


class _Runtime:
    def __init__(self) -> None:
        self.config = SimpleNamespace(base_dir="/repo")
        self.env: dict[str, str] = {}
        self.events: list[tuple[str, dict[str, object]]] = []

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, payload))


class PlanAgentTmuxLaunchSupportTests(unittest.TestCase):
    def test_unhealthy_existing_session_returns_recorded_failure(self) -> None:
        runtime = _Runtime()
        runtime._last_unhealthy_existing_tmux_session_reason = "existing_tmux_session_unhealthy"
        runtime._last_unhealthy_existing_tmux_session_outcomes = (
            PlanAgentLaunchOutcome(
                worktree_name="feature-a-1",
                worktree_root=Path("/repo/trees/feature-a-1"),
                surface_id=None,
                status="failed",
                reason="existing_tmux_session_unhealthy",
            ),
        )

        result = launch_tmux_terminals(
            runtime,
            route=SimpleNamespace(flags={}),
            launch_config=_launch_config(),
            workflow=_workflow(),
            created_worktrees=(_worktree(),),
            base_payload={},
            prompt_on_existing=False,
            should_prompt_existing_session_fn=lambda *_args, **_kwargs: False,
            prompt_existing_session_action_fn=lambda *_args, **_kwargs: "new",
            find_existing_attach_target_fn=lambda *_args, **_kwargs: None,
            new_session_command_for_route_fn=lambda *_args, **_kwargs: (),
            tmux_session_name_for_worktree_fn=lambda *_args, **_kwargs: "envctl-feature-a",
            next_available_tmux_session_name_fn=lambda *_args, **_kwargs: "envctl-feature-a-2",
            tmux_window_name_for_worktree_fn=lambda _worktree: "feature-a",
            launch_single_tmux_worktree_fn=lambda *_args, **_kwargs: self.fail("should not launch"),
            guidance_attach_command_fn=lambda session: ("tmux", "attach", "-t", session),
            summarize_failed_launch_outcomes_fn=lambda _failed: "",
            print_launch_summary_fn=lambda _message: None,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "existing_tmux_session_unhealthy")
        self.assertFalse(hasattr(runtime, "_last_unhealthy_existing_tmux_session_reason"))
        self.assertFalse(hasattr(runtime, "_last_unhealthy_existing_tmux_session_outcomes"))

    def test_existing_session_returns_attach_guidance_without_new_session(self) -> None:
        runtime = _Runtime()
        existing = _attach_target()

        result = launch_tmux_terminals(
            runtime,
            route=SimpleNamespace(flags={}),
            launch_config=_launch_config(),
            workflow=_workflow(),
            created_worktrees=(_worktree(),),
            base_payload={"plan": "feature-a.md"},
            prompt_on_existing=False,
            should_prompt_existing_session_fn=lambda *_args, **_kwargs: False,
            prompt_existing_session_action_fn=lambda *_args, **_kwargs: "new",
            find_existing_attach_target_fn=lambda *_args, **_kwargs: existing,
            new_session_command_for_route_fn=lambda *_args, **_kwargs: ("envctl", "plan", "--tmux", "--new-session"),
            tmux_session_name_for_worktree_fn=lambda *_args, **_kwargs: "envctl-feature-a",
            next_available_tmux_session_name_fn=lambda *_args, **_kwargs: "envctl-feature-a-2",
            tmux_window_name_for_worktree_fn=lambda _worktree: "feature-a",
            launch_single_tmux_worktree_fn=lambda *_args, **_kwargs: self.fail("should not launch"),
            guidance_attach_command_fn=lambda session: ("tmux", "attach", "-t", session),
            summarize_failed_launch_outcomes_fn=lambda _failed: "",
            print_launch_summary_fn=lambda _message: None,
        )

        self.assertEqual(result.status, "failed")
        self.assertIn("already exists", result.reason or "")
        self.assertEqual(result.attach_target.new_session_command if result.attach_target else None, ("envctl", "plan", "--tmux", "--new-session"))
        self.assertEqual(runtime.events[0][0], "planning.agent_launch.skipped")
        self.assertEqual(runtime.events[0][1]["reason"], "existing_tmux_session")
        self.assertEqual(runtime.events[0][1]["plan"], "feature-a.md")

    def test_new_session_launch_uses_available_names_and_returns_attach_target(self) -> None:
        runtime = _Runtime()
        launched_names: list[str] = []

        result = launch_tmux_terminals(
            runtime,
            route=SimpleNamespace(flags={"new_session": True}),
            launch_config=_launch_config(),
            workflow=_workflow(),
            created_worktrees=(_worktree(),),
            base_payload={},
            prompt_on_existing=False,
            should_prompt_existing_session_fn=lambda *_args, **_kwargs: False,
            prompt_existing_session_action_fn=lambda *_args, **_kwargs: "new",
            find_existing_attach_target_fn=lambda *_args, **_kwargs: None,
            new_session_command_for_route_fn=lambda *_args, **_kwargs: (),
            tmux_session_name_for_worktree_fn=lambda *_args, **_kwargs: "envctl-feature-a",
            next_available_tmux_session_name_fn=lambda _runtime, session_name: f"{session_name}-2",
            tmux_window_name_for_worktree_fn=lambda _worktree: "feature-a",
            launch_single_tmux_worktree_fn=lambda _runtime, *, session_name, worktree, **_kwargs: (
                launched_names.append(session_name)
                or PlanAgentLaunchOutcome(worktree.name, worktree.root, None, "launched")
            ),
            guidance_attach_command_fn=lambda session: ("tmux", "attach", "-t", session),
            summarize_failed_launch_outcomes_fn=lambda _failed: "",
            print_launch_summary_fn=lambda _message: None,
        )

        self.assertEqual(result.status, "launched")
        self.assertEqual(launched_names, ["envctl-feature-a-2"])
        self.assertEqual(result.attach_target.session_name if result.attach_target else None, "envctl-feature-a-2")
        self.assertEqual(result.attach_target.attach_command if result.attach_target else None, ("tmux", "attach", "-t", "envctl-feature-a-2"))

    def test_mixed_worktree_results_return_partial(self) -> None:
        runtime = _Runtime()
        summaries: list[str] = []

        result = launch_tmux_terminals(
            runtime,
            route=SimpleNamespace(flags={}),
            launch_config=_launch_config(),
            workflow=_workflow(),
            created_worktrees=(_worktree("feature-a-1"), _worktree("feature-b-1")),
            base_payload={},
            prompt_on_existing=False,
            should_prompt_existing_session_fn=lambda *_args, **_kwargs: False,
            prompt_existing_session_action_fn=lambda *_args, **_kwargs: "new",
            find_existing_attach_target_fn=lambda *_args, **_kwargs: None,
            new_session_command_for_route_fn=lambda *_args, **_kwargs: (),
            tmux_session_name_for_worktree_fn=lambda _repo_root, worktree, **_kwargs: f"envctl-{worktree.name}",
            next_available_tmux_session_name_fn=lambda _runtime, session_name: session_name,
            tmux_window_name_for_worktree_fn=lambda worktree: worktree.name,
            launch_single_tmux_worktree_fn=lambda _runtime, *, session_name, worktree, **_kwargs: PlanAgentLaunchOutcome(
                worktree.name,
                worktree.root,
                None,
                "failed" if worktree.name == "feature-b-1" else "launched",
                "bootstrap failed" if worktree.name == "feature-b-1" else None,
            ),
            guidance_attach_command_fn=lambda session: ("tmux", "attach", "-t", session),
            summarize_failed_launch_outcomes_fn=lambda _failed: "feature-b-1: bootstrap failed",
            print_launch_summary_fn=lambda message: summaries.append(message),
        )

        self.assertEqual(result.status, "partial")
        self.assertEqual([outcome.status for outcome in result.outcomes], ["launched", "failed"])
        self.assertEqual(result.attach_target.session_name if result.attach_target else None, "envctl-feature-a-1")
        self.assertIn("partial success", summaries[0])


if __name__ == "__main__":
    unittest.main()
