# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchWorkflowBuildTests(PlanAgentLaunchSupportTestCase):
    def test_tmux_codex_cycles_queue_remaining_workflow_steps(self) -> None:
        self.assertIsNotNone(_run_tmux_worktree_bootstrap)
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="tmux",
                cli="codex",
                cli_command="codex --dangerously-bypass-approvals-and-sandbox",
                preset="implement_task",
                codex_cycles=2,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=False,
                ulw_loop_prefix=False,
                ulw_suffix=False,
            )
            workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=2)

            def resolve_step(*_args, step, **_kwargs):
                return (f"resolved::{step.kind}::{step.text}", None)

            with (
                patch("envctl_engine.planning.plan_agent.tmux_transport._launch_tmux_cli_bootstrap_commands", return_value=[None]),
                patch("envctl_engine.planning.plan_agent.tmux_transport._wait_for_tmux_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._workflow_step_prompt_text", side_effect=resolve_step),
                patch("envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_prompt_workflow_step", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._send_tmux_prompt", return_value=None) as send_prompt_mock,
                patch("envctl_engine.planning.plan_agent.tmux_transport._send_tmux_text", return_value=None) as send_text_mock,
                patch("envctl_engine.planning.plan_agent.tmux_transport._queue_tmux_codex_message", return_value=True) as queue_mock,
            ):
                error = _run_tmux_worktree_bootstrap(
                    rt,
                    session_name="envctl-test-session",
                    window_name="feature-a-1",
                    launch_config=launch_config,
                    workflow=workflow,
                    worktree=worktree,
                )

            self.assertIsNone(error)
            self.assertEqual(send_text_mock.call_count, 0)
            self.assertEqual(send_prompt_mock.call_count, 4)
            self.assertEqual(queue_mock.call_count, 4)
            self.assertEqual(
                self._events(rt, "planning.agent_launch.workflow_queued"),
                [
                    {
                        "event": "planning.agent_launch.workflow_queued",
                        "session_name": "envctl-test-session",
                        "window_name": "feature-a-1",
                        "worktree": "feature-a-1",
                        "cli": "codex",
                        "workflow_mode": "codex_cycles",
                        "codex_cycles": 2,
                        "queued_steps": 4,
                        "queued_steps_confirmed": 4,
                        "transport": "tmux",
                    }
                ],
            )

    def test_build_plan_agent_workflow_uses_single_prompt_by_default(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        self.assertIsNotNone(_browser_e2e_instruction_text)
        self.assertIsNotNone(_pr_review_comments_instruction_text)
        workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=0)

        self.assertEqual(workflow.mode, "single_prompt")
        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [("submit_direct_prompt", "implement_task")],
        )

    def test_browser_e2e_followup_requires_main_task_browser_visible_validation_and_fix_loop(self) -> None:
        self.assertIsNotNone(_browser_e2e_instruction_text)
        prompt = _browser_e2e_instruction_text()

        self.assertIn("$browser", prompt)
        self.assertIn("envctl list-targets --json", prompt)
        self.assertIn("envctl endpoints --project <actual-project-name> --json", prompt)
        self.assertIn("envctl qa-user ensure --project <actual-project-name>", prompt)
        self.assertIn("envctl playwright --project <actual-project-name> -- <executable> [args...]", prompt)
        self.assertIn("envctl playwright --help", prompt)
        self.assertIn("MAIN_TASK.md", prompt)
        self.assertIn("completely implemented end-to-end", prompt)
        self.assertIn("visible in the browser", prompt)
        self.assertIn("fix any issue", prompt)
        self.assertIn("introduced by the implementation", prompt)

    def test_plan_agent_followup_prompts_are_loaded_from_markdown_templates(self) -> None:
        self.assertIsNotNone(_finalization_instruction_text)
        self.assertIsNotNone(_first_cycle_completion_instruction_text)
        self.assertIsNotNone(_intermediate_cycle_completion_instruction_text)
        self.assertIsNotNone(_browser_e2e_instruction_text)
        self.assertIsNotNone(_pr_review_comments_instruction_text)

        template_root = resources.files("envctl_engine.runtime.prompt_templates")

        def assert_prompt_matches_template(prompt_text: Any, template_name: str) -> None:
            self.assertEqual(
                prompt_text(),
                template_root.joinpath(template_name).read_text(encoding="utf-8").strip(),
            )

        assert_prompt_matches_template(_finalization_instruction_text, "_plan_agent_finalization_instruction.md")
        assert_prompt_matches_template(_first_cycle_completion_instruction_text, "_plan_agent_first_cycle_completion.md")
        assert_prompt_matches_template(
            _intermediate_cycle_completion_instruction_text,
            "_plan_agent_intermediate_cycle_completion.md",
        )
        assert_prompt_matches_template(_browser_e2e_instruction_text, "_plan_agent_browser_e2e_followup.md")
        assert_prompt_matches_template(
            _pr_review_comments_instruction_text,
            "_plan_agent_pr_review_comments_followup.md",
        )

    def test_build_plan_agent_workflow_uses_direct_submission_for_implement_task(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=0)

        self.assertEqual(workflow.mode, "single_prompt")
        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [("submit_direct_prompt", "implement_task")],
        )

    def test_build_plan_agent_workflow_queues_pr_review_comments_when_enabled(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        workflow = _build_plan_agent_workflow(
            cli="codex",
            preset="implement_task",
            codex_cycles=0,
            pr_review_comments_followup_enable=True,
        )

        self.assertEqual(workflow.mode, "single_prompt")
        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [
                ("submit_direct_prompt", "implement_task"),
                ("queue_message", _pr_review_comments_instruction_text()),
            ],
        )

    def test_build_plan_agent_workflow_for_single_cycle_adds_finalization_without_browser_by_default(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        self.assertIsNotNone(_finalization_instruction_text)
        self.assertIsNotNone(_browser_e2e_instruction_text)
        workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=1)

        self.assertEqual(workflow.mode, "codex_cycles")
        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [
                ("submit_direct_prompt", "implement_task"),
                ("queue_direct_prompt", "finalize_task"),
            ],
        )

    def test_build_plan_agent_workflow_appends_browser_e2e_when_explicitly_enabled(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        self.assertIsNotNone(_browser_e2e_instruction_text)
        workflow = _build_plan_agent_workflow(
            cli="codex",
            preset="implement_task",
            codex_cycles=1,
            browser_e2e_followup_enable=True,
        )

        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [
                ("submit_direct_prompt", "implement_task"),
                ("queue_direct_prompt", "finalize_task"),
                ("queue_message", _browser_e2e_instruction_text()),
            ],
        )

    def test_build_plan_agent_workflow_for_multiple_cycles_queues_continue_and_implement_rounds(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        self.assertIsNotNone(_finalization_instruction_text)
        self.assertIsNotNone(_first_cycle_completion_instruction_text)
        self.assertIsNotNone(_browser_e2e_instruction_text)
        workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=2)

        self.assertEqual(workflow.mode, "codex_cycles")
        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [
                ("submit_direct_prompt", "implement_task"),
                ("queue_message", _first_cycle_completion_instruction_text()),
                ("queue_direct_prompt", "continue_task"),
                ("queue_direct_prompt", "implement_task"),
                ("queue_direct_prompt", "finalize_task"),
            ],
        )

    def test_build_plan_agent_workflow_for_three_cycles_uses_commit_push_middle_round(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        self.assertIsNotNone(_finalization_instruction_text)
        self.assertIsNotNone(_first_cycle_completion_instruction_text)
        self.assertIsNotNone(_intermediate_cycle_completion_instruction_text)
        workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=3)

        self.assertEqual(workflow.mode, "codex_cycles")
        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [
                ("submit_direct_prompt", "implement_task"),
                ("queue_message", _first_cycle_completion_instruction_text()),
                ("queue_direct_prompt", "continue_task"),
                ("queue_direct_prompt", "implement_task"),
                ("queue_message", _intermediate_cycle_completion_instruction_text()),
                ("queue_direct_prompt", "continue_task"),
                ("queue_direct_prompt", "implement_task"),
                ("queue_direct_prompt", "finalize_task"),
            ],
        )

    def test_build_plan_agent_workflow_keeps_opencode_on_single_prompt_even_when_cycles_set(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        workflow = _build_plan_agent_workflow(cli="opencode", preset="implement_task", codex_cycles=2)

        self.assertEqual(workflow.mode, "single_prompt")
        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [("submit_prompt", "/implement_task")],
        )

    def test_build_plan_agent_workflow_uses_direct_submission_for_opencode_when_enabled(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        workflow = _build_plan_agent_workflow(
            cli="opencode",
            preset="implement_task",
            codex_cycles=2,
            direct_prompt_enabled=True,
        )

        self.assertEqual(workflow.mode, "single_prompt")
        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [("submit_direct_prompt", "implement_task")],
        )

    def test_build_plan_agent_workflow_bounds_large_cycle_counts(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=999)

        self.assertEqual(workflow.mode, "codex_cycles")
        self.assertEqual(workflow.codex_cycles, 3)
        self.assertEqual(len(workflow.steps), 1 + (1 + 3 * (workflow.codex_cycles - 1)))

    def test_codex_cycle_queued_steps_do_not_request_goal_frames(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        workflow = _build_plan_agent_workflow(
            cli="codex",
            preset="implement_task",
            codex_cycles=3,
            browser_e2e_followup_enable=True,
            pr_review_comments_followup_enable=True,
        )

        self.assertTrue(workflow.steps[0].requires_goal)
        self.assertTrue(all(not step.requires_goal for step in workflow.steps[1:]))
