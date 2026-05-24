from __future__ import annotations

from pathlib import Path
import unittest

from envctl_engine.planning.plan_agent.models import (
    AiCliReadyResult,
    CreatedPlanWorktree,
    PlanAgentLaunchConfig,
    _PlanAgentWorkflow,
    _PlanAgentWorkflowStep,
)
from envctl_engine.planning.plan_agent.tmux_workflow_submission_support import (
    run_existing_tmux_session_workflow,
    run_tmux_worktree_bootstrap,
)


def _launch_config(
    *,
    transport: str = "tmux",
    cli: str = "codex",
    codex_goal_enable: bool = False,
    codex_cycles: int = 1,
    omx_workflow: str = "",
) -> PlanAgentLaunchConfig:
    return PlanAgentLaunchConfig(
        enabled=True,
        transport=transport,  # type: ignore[arg-type]
        cli=cli,
        cli_command=cli,
        preset="implementation",
        codex_cycles=codex_cycles,
        codex_cycles_warning=None,
        shell="/bin/zsh",
        require_cmux_context=False,
        cmux_workspace="",
        direct_prompt_enabled=False,
        ulw_loop_prefix=True,
        ulw_suffix=True,
        codex_goal_enable=codex_goal_enable,
        omx_workflow=omx_workflow,  # type: ignore[arg-type]
    )


def _worktree() -> CreatedPlanWorktree:
    return CreatedPlanWorktree(
        name="feature-a-1",
        root=Path("/repo/trees/feature-a/1"),
        plan_file="features/a.md",
    )


def _workflow(*, codex_cycles: int = 1, queued: bool = False) -> _PlanAgentWorkflow:
    steps = [_PlanAgentWorkflowStep(kind="submit_prompt", text="initial")]
    if queued:
        steps.append(_PlanAgentWorkflowStep(kind="queue_direct_prompt", text="queued"))
    return _PlanAgentWorkflow(mode="codex_cycles", codex_cycles=codex_cycles, steps=tuple(steps))


class _Runtime:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, payload))


class PlanAgentTmuxBootstrapFlowSupportTests(unittest.TestCase):
    def test_run_tmux_worktree_bootstrap_returns_cli_ready_failure(self) -> None:
        error = run_tmux_worktree_bootstrap(
            _Runtime(),
            session_name="session",
            window_name="window",
            launch_config=_launch_config(),
            workflow=_workflow(),
            worktree=_worktree(),
            launch_tmux_cli_bootstrap_commands_fn=lambda *_args, **_kwargs: (),
            wait_for_tmux_cli_ready_fn=lambda *_args, **_kwargs: AiCliReadyResult(
                ready=False,
                reason="codex_ready_timeout",
                screen_excerpt="not ready",
            ),
            format_ai_cli_ready_failure_fn=lambda result: f"{result.reason}:{result.screen_excerpt}",
            maybe_submit_tmux_codex_goal_fn=lambda *_args, **_kwargs: None,
            workflow_step_prompt_text_fn=lambda *_args, **_kwargs: ("prompt", None),
            submit_tmux_prompt_workflow_step_fn=lambda *_args, **_kwargs: None,
            queue_tmux_codex_workflow_steps_fn=lambda *_args, **_kwargs: None,
            queue_failure_event_context_fn=lambda _reason: {},
        )

        self.assertEqual(error, "codex_ready_timeout:not ready")

    def test_run_tmux_worktree_bootstrap_emits_queue_fallback_without_failing_launch(self) -> None:
        runtime = _Runtime()

        error = run_tmux_worktree_bootstrap(
            runtime,
            session_name="session",
            window_name="window",
            launch_config=_launch_config(transport="tmux"),
            workflow=_workflow(queued=True),
            worktree=_worktree(),
            launch_tmux_cli_bootstrap_commands_fn=lambda *_args, **_kwargs: (),
            wait_for_tmux_cli_ready_fn=lambda *_args, **_kwargs: None,
            format_ai_cli_ready_failure_fn=lambda result: result.reason,
            maybe_submit_tmux_codex_goal_fn=lambda *_args, **_kwargs: None,
            workflow_step_prompt_text_fn=lambda *_args, **_kwargs: ("prompt", None),
            submit_tmux_prompt_workflow_step_fn=lambda *_args, **_kwargs: None,
            queue_tmux_codex_workflow_steps_fn=lambda *_args, **_kwargs: "queue_not_ready",
            queue_failure_event_context_fn=lambda reason: {"detail": f"detail:{reason}"},
        )

        self.assertIsNone(error)
        self.assertEqual(
            [event for event, _payload in runtime.events],
            [
                "planning.agent_launch.workflow_queue_failed",
                "planning.agent_launch.workflow_fallback",
            ],
        )
        self.assertEqual(runtime.events[0][1]["transport"], "tmux")
        self.assertEqual(runtime.events[0][1]["reason"], "queue_not_ready")
        self.assertEqual(runtime.events[0][1]["detail"], "detail:queue_not_ready")

    def test_existing_omx_session_wraps_initial_prompt_and_queues_cycles(self) -> None:
        submitted: list[str] = []
        queued: list[tuple[str, int]] = []

        error = run_existing_tmux_session_workflow(
            _Runtime(),
            session_name="session",
            window_name="window",
            launch_config=_launch_config(transport="omx", omx_workflow="ralph", codex_cycles=1),
            workflow=_workflow(codex_cycles=1, queued=True),
            worktree=_worktree(),
            wait_for_tmux_cli_ready_fn=lambda *_args, **_kwargs: None,
            format_ai_cli_ready_failure_fn=lambda result: result.reason,
            maybe_submit_tmux_codex_goal_fn=lambda *_args, **_kwargs: None,
            workflow_step_prompt_text_fn=lambda *_args, **_kwargs: ("IMPLEMENT", None),
            wrap_omx_initial_prompt_for_workflow_fn=lambda text, *, workflow: f"${workflow}\n\n{text}",
            submit_tmux_prompt_workflow_step_fn=lambda *_args, **kwargs: submitted.append(kwargs["prompt_text"]) or None,
            queue_tmux_codex_workflow_steps_fn=lambda *_args, **kwargs: queued.append((kwargs["transport"], len(kwargs["queued_steps"]))) or None,
            queue_failure_event_context_fn=lambda _reason: {},
        )

        self.assertIsNone(error)
        self.assertEqual(submitted, ["$ralph\n\nIMPLEMENT"])
        self.assertEqual(queued, [("omx", 1)])

    def test_existing_omx_session_skips_cycle_queue_when_omx_cycles_disabled(self) -> None:
        queued: list[str] = []

        error = run_existing_tmux_session_workflow(
            _Runtime(),
            session_name="session",
            window_name="window",
            launch_config=_launch_config(transport="omx", codex_cycles=0),
            workflow=_workflow(codex_cycles=0, queued=True),
            worktree=_worktree(),
            wait_for_tmux_cli_ready_fn=lambda *_args, **_kwargs: None,
            format_ai_cli_ready_failure_fn=lambda result: result.reason,
            maybe_submit_tmux_codex_goal_fn=lambda *_args, **_kwargs: "codex_goal_ready_timeout",
            workflow_step_prompt_text_fn=lambda *_args, **_kwargs: ("IMPLEMENT", None),
            wrap_omx_initial_prompt_for_workflow_fn=lambda text, *, workflow: text,
            submit_tmux_prompt_workflow_step_fn=lambda *_args, **_kwargs: None,
            queue_tmux_codex_workflow_steps_fn=lambda *_args, **_kwargs: queued.append("queued") or None,
            queue_failure_event_context_fn=lambda _reason: {},
        )

        self.assertIsNone(error)
        self.assertEqual(queued, [])


if __name__ == "__main__":
    unittest.main()
