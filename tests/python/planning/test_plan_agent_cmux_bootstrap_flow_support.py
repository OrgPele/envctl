from __future__ import annotations

from pathlib import Path
import unittest

from envctl_engine.planning.plan_agent.cmux_bootstrap_support import (
    run_review_surface_bootstrap,
    run_surface_bootstrap,
)
from envctl_engine.planning.plan_agent.models import (
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
    _PlanAgentWorkflowStep,
)


def _launch_config(
    *,
    cli: str = "codex",
    direct_prompt_enabled: bool = False,
    codex_goal_enable: bool = False,
) -> PlanAgentLaunchConfig:
    return PlanAgentLaunchConfig(
        enabled=True,
        transport="cmux",
        cli=cli,
        cli_command=cli,
        preset="default",
        codex_cycles=1,
        codex_cycles_warning=None,
        shell="zsh",
        require_cmux_context=False,
        cmux_workspace="",
        direct_prompt_enabled=direct_prompt_enabled,
        ulw_loop_prefix=True,
        ulw_suffix=True,
        codex_goal_enable=codex_goal_enable,
    )


def _worktree() -> CreatedPlanWorktree:
    return CreatedPlanWorktree(
        name="feature-a-1",
        root=Path("/repo/trees/feature-a/1"),
        plan_file="todo/plans/feature-a.md",
    )


class _Runtime:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, payload))


class PlanAgentCmuxBootstrapFlowSupportTests(unittest.TestCase):
    def test_run_surface_bootstrap_returns_prepare_error_without_sending(self) -> None:
        calls: list[str] = []

        error = run_surface_bootstrap(
            _Runtime(),
            workspace_id="workspace-1",
            surface_id="surface-1",
            launch_config=_launch_config(),
            worktree=_worktree(),
            build_plan_agent_workflow_fn=lambda **_kwargs: _PlanAgentWorkflow(
                mode="single",
                codex_cycles=1,
                steps=(_PlanAgentWorkflowStep(kind="submit_prompt", text="initial"),),
            ),
            prepare_surface_fn=lambda *_args, **_kwargs: "prepare failed",
            tab_title_for_worktree_fn=lambda name: f"tab:{name}",
            surface_respawn_command_fn=lambda *_args, **_kwargs: "exec zsh",
            launch_cli_bootstrap_commands_fn=lambda *_args, **_kwargs: calls.append("send") or (),
            wait_for_cli_ready_fn=lambda *_args, **_kwargs: calls.append("ready"),
            maybe_submit_surface_codex_goal_fn=lambda *_args, **_kwargs: None,
            workflow_step_prompt_text_fn=lambda *_args, **_kwargs: ("prompt", None),
            submit_direct_prompt_workflow_step_fn=lambda *_args, **_kwargs: calls.append("direct") or None,
            submit_prompt_workflow_step_fn=lambda *_args, **_kwargs: calls.append("prompt") or None,
            queue_codex_workflow_steps_fn=lambda *_args, **_kwargs: None,
            queue_failure_event_context_fn=lambda _reason: {},
        )

        self.assertEqual(error, "prepare failed")
        self.assertEqual(calls, [])

    def test_run_surface_bootstrap_uses_direct_initial_submission(self) -> None:
        calls: list[tuple[str, object]] = []

        error = run_surface_bootstrap(
            _Runtime(),
            workspace_id="workspace-1",
            surface_id="surface-1",
            launch_config=_launch_config(cli="codex", direct_prompt_enabled=True),
            worktree=_worktree(),
            build_plan_agent_workflow_fn=lambda **_kwargs: _PlanAgentWorkflow(
                mode="direct",
                codex_cycles=1,
                steps=(_PlanAgentWorkflowStep(kind="submit_direct_prompt", text="initial"),),
            ),
            prepare_surface_fn=lambda *_args, **kwargs: calls.append(("prepare", kwargs["tab_title"])) or None,
            tab_title_for_worktree_fn=lambda name: f"tab:{name}",
            surface_respawn_command_fn=lambda *_args, **_kwargs: "exec zsh",
            launch_cli_bootstrap_commands_fn=lambda *_args, **_kwargs: (),
            wait_for_cli_ready_fn=lambda *_args, **_kwargs: calls.append(("ready", None)),
            maybe_submit_surface_codex_goal_fn=lambda *_args, **_kwargs: None,
            workflow_step_prompt_text_fn=lambda *_args, **_kwargs: ("direct prompt", None),
            submit_direct_prompt_workflow_step_fn=lambda *_args, **kwargs: calls.append(("direct", kwargs["prompt_text"])) or None,
            submit_prompt_workflow_step_fn=lambda *_args, **_kwargs: calls.append(("prompt", None)) or None,
            queue_codex_workflow_steps_fn=lambda *_args, **_kwargs: None,
            queue_failure_event_context_fn=lambda _reason: {},
        )

        self.assertIsNone(error)
        self.assertIn(("prepare", "tab:feature-a-1"), calls)
        self.assertIn(("direct", "direct prompt"), calls)
        self.assertNotIn(("prompt", None), calls)

    def test_run_surface_bootstrap_emits_queue_fallback_without_failing_launch(self) -> None:
        runtime = _Runtime()

        error = run_surface_bootstrap(
            runtime,
            workspace_id="workspace-1",
            surface_id="surface-1",
            launch_config=_launch_config(cli="codex"),
            worktree=_worktree(),
            build_plan_agent_workflow_fn=lambda **_kwargs: _PlanAgentWorkflow(
                mode="multi",
                codex_cycles=2,
                steps=(
                    _PlanAgentWorkflowStep(kind="submit_prompt", text="initial"),
                    _PlanAgentWorkflowStep(kind="submit_prompt", text="queued"),
                ),
            ),
            prepare_surface_fn=lambda *_args, **_kwargs: None,
            tab_title_for_worktree_fn=lambda name: name,
            surface_respawn_command_fn=lambda *_args, **_kwargs: "exec zsh",
            launch_cli_bootstrap_commands_fn=lambda *_args, **_kwargs: (),
            wait_for_cli_ready_fn=lambda *_args, **_kwargs: None,
            maybe_submit_surface_codex_goal_fn=lambda *_args, **_kwargs: None,
            workflow_step_prompt_text_fn=lambda *_args, **_kwargs: ("prompt", None),
            submit_direct_prompt_workflow_step_fn=lambda *_args, **_kwargs: None,
            submit_prompt_workflow_step_fn=lambda *_args, **_kwargs: None,
            queue_codex_workflow_steps_fn=lambda *_args, **_kwargs: "queue_not_ready",
            queue_failure_event_context_fn=lambda reason: {"reason_detail": f"detail:{reason}"},
        )

        self.assertIsNone(error)
        self.assertEqual(
            [event for event, _payload in runtime.events],
            [
                "planning.agent_launch.workflow_queue_failed",
                "planning.agent_launch.workflow_fallback",
            ],
        )
        self.assertEqual(runtime.events[0][1]["reason"], "queue_not_ready")
        self.assertEqual(runtime.events[0][1]["transport"], "cmux")
        self.assertEqual(runtime.events[0][1]["reason_detail"], "detail:queue_not_ready")

    def test_run_review_surface_bootstrap_uses_direct_submission_when_configured(self) -> None:
        calls: list[tuple[str, object]] = []

        error = run_review_surface_bootstrap(
            _Runtime(),
            workspace_id="workspace-1",
            surface_id="surface-1",
            launch_config=_launch_config(cli="opencode", direct_prompt_enabled=True),
            repo_root=Path("/repo"),
            project_name="feature-a-1",
            project_root=Path("/repo/trees/feature-a/1"),
            review_bundle_path=Path("/repo/review.json"),
            prepare_surface_fn=lambda *_args, **kwargs: calls.append(("prepare_event", kwargs["failure_event"])) or None,
            tab_title_for_worktree_fn=lambda name: f"tab:{name}",
            launch_cli_bootstrap_commands_fn=lambda *_args, **_kwargs: (),
            wait_for_cli_ready_fn=lambda *_args, **_kwargs: None,
            review_prompt_arguments_fn=lambda **kwargs: {"project": kwargs["project_name"]},
            review_original_plan_path_fn=lambda *_args, **_kwargs: Path("/repo/MAIN_TASK.md"),
            resolve_preset_submission_text_fn=lambda *_args, **_kwargs: ("review prompt", None),
            uses_direct_submission_fn=lambda **_kwargs: True,
            submit_direct_prompt_workflow_step_fn=lambda *_args, **kwargs: calls.append(("direct_event", kwargs["failure_event"])) or None,
            submit_prompt_workflow_step_fn=lambda *_args, **_kwargs: calls.append(("prompt", None)) or None,
        )

        self.assertIsNone(error)
        self.assertEqual(calls, [("prepare_event", "dashboard.review_tab.failed"), ("direct_event", "dashboard.review_tab.failed")])

    def test_run_review_surface_bootstrap_returns_preset_resolution_error(self) -> None:
        error = run_review_surface_bootstrap(
            _Runtime(),
            workspace_id="workspace-1",
            surface_id="surface-1",
            launch_config=_launch_config(cli="codex"),
            repo_root=Path("/repo"),
            project_name="feature-a-1",
            project_root=Path("/repo/trees/feature-a/1"),
            review_bundle_path=None,
            prepare_surface_fn=lambda *_args, **_kwargs: None,
            tab_title_for_worktree_fn=lambda name: name,
            launch_cli_bootstrap_commands_fn=lambda *_args, **_kwargs: (),
            wait_for_cli_ready_fn=lambda *_args, **_kwargs: None,
            review_prompt_arguments_fn=lambda **_kwargs: {},
            review_original_plan_path_fn=lambda *_args, **_kwargs: None,
            resolve_preset_submission_text_fn=lambda *_args, **_kwargs: ("", "preset failed"),
            uses_direct_submission_fn=lambda **_kwargs: False,
            submit_direct_prompt_workflow_step_fn=lambda *_args, **_kwargs: None,
            submit_prompt_workflow_step_fn=lambda *_args, **_kwargs: None,
        )

        self.assertEqual(error, "preset failed")


if __name__ == "__main__":
    unittest.main()
