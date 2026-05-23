# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchWorkflowTests(PlanAgentLaunchSupportTestCase):
    def test_resolve_preset_submission_text_defaults_ulw_loop_for_explicit_opencode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            prompt_path = Path(tmpdir) / ".config" / "opencode" / "commands" / "implement_task.md"
            repo.mkdir(parents=True, exist_ok=True)
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text("Implement this directly.\n", encoding="utf-8")
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {"HOME": tmpdir},
                route=parse_route(["--plan", "feature-a", "--opencode"], env={}),
            )
            rt = self._runtime(repo, runtime, env={"HOME": tmpdir})

            prompt_text, error = workflow._resolve_preset_submission_text(
                rt,
                launch_config=launch_config,
                cli="opencode",
                preset="implement_task",
            )

        self.assertIsNone(error)
        self.assertEqual(prompt_text, "/ulw-loop Implement this directly.")

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
            self.assertEqual(send_prompt_mock.call_count, 12)
            self.assertEqual(queue_mock.call_count, 12)
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
                        "queued_steps": 6,
                        "queued_steps_confirmed": 6,
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
            [
                ("submit_direct_prompt", "implement_task"),
                ("queue_message", _browser_e2e_instruction_text()),
                ("queue_message", _pr_review_comments_instruction_text()),
            ],
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
            [
                ("submit_direct_prompt", "implement_task"),
                ("queue_message", _browser_e2e_instruction_text()),
                ("queue_message", _pr_review_comments_instruction_text()),
            ],
        )

    def test_build_plan_agent_workflow_for_single_cycle_adds_finalization_and_browser_e2e_messages(self) -> None:
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
                ("queue_message", _browser_e2e_instruction_text()),
                ("queue_message", _pr_review_comments_instruction_text()),
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
                ("queue_message", _browser_e2e_instruction_text()),
                ("queue_message", _pr_review_comments_instruction_text()),
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
                ("queue_message", _browser_e2e_instruction_text()),
                ("queue_message", _pr_review_comments_instruction_text()),
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

    def test_workflow_step_prompt_text_loads_direct_codex_prompt_body(self) -> None:
        self.assertIsNotNone(_workflow_step_prompt_text)
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / ".config" / "envctl" / "codex" / "prompts" / "implement_task.md"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text("Implement this task carefully.\n", encoding="utf-8")
            runtime = _RuntimeHarness(
                config=load_config(
                    {
                        "RUN_REPO_ROOT": "/tmp/repo",
                        "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                    }
                ),
                env={"HOME": tmpdir},
                process_runner=_RecordingRunner(),
            )
            step = workflow._PlanAgentWorkflowStep(kind="submit_direct_prompt", text="implement_task")

            prompt_text, error = _workflow_step_prompt_text(
                runtime,
                launch_config=_launch_config_for_tests(cli="codex"),
                cli="codex",
                step=step,
            )

        self.assertIsNone(error)
        self.assertEqual(prompt_text, "Implement this task carefully.\n")

    def test_workflow_step_prompt_text_preserves_literal_arguments_mentions_in_review_prompt(self) -> None:
        self.assertIsNotNone(_workflow_step_prompt_text)
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / ".config" / "envctl" / "codex" / "prompts" / "review_worktree_imp.md"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(
                "Inputs:\n$ARGUMENTS\nKeep `$ARGUMENTS` literal in prose.\n",
                encoding="utf-8",
            )
            runtime = _RuntimeHarness(
                config=load_config(
                    {
                        "RUN_REPO_ROOT": "/tmp/repo",
                        "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                    }
                ),
                env={"HOME": tmpdir},
                process_runner=_RecordingRunner(),
            )
            prompt_text, error = workflow._resolve_preset_submission_text(
                runtime,
                launch_config=_launch_config_for_tests(cli="codex"),
                cli="codex",
                preset="review_worktree_imp",
                arguments="Review bundle: /tmp/review.md\nWorktree directory: /tmp/tree",
            )

        self.assertIsNone(error)
        self.assertIn("Review bundle: /tmp/review.md\nWorktree directory: /tmp/tree", prompt_text)
        self.assertIn("Keep `$ARGUMENTS` literal in prose.", prompt_text)
        self.assertEqual(prompt_text.count("$ARGUMENTS"), 1)

    def test_resolve_preset_submission_text_returns_opencode_direct_body_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / ".config" / "opencode" / "commands" / "implement_task.md"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text("Implement this directly.\n", encoding="utf-8")
            runtime = _RuntimeHarness(
                config=load_config(
                    {
                        "RUN_REPO_ROOT": "/tmp/repo",
                        "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                    }
                ),
                env={"HOME": tmpdir},
                process_runner=_RecordingRunner(),
            )
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="cmux",
                cli="opencode",
                cli_command="opencode",
                preset="implement_task",
                codex_cycles=0,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=True,
                ulw_loop_prefix=False,
                ulw_suffix=False,
            )

            prompt_text, error = workflow._resolve_preset_submission_text(
                runtime,
                launch_config=launch_config,
                cli="opencode",
                preset="implement_task",
            )

        self.assertIsNone(error)
        self.assertEqual(prompt_text, "Implement this directly.\n")

    def test_resolve_preset_submission_text_keeps_slash_mode_for_opencode_by_default(self) -> None:
        runtime = _RuntimeHarness(
            config=load_config(
                {
                    "RUN_REPO_ROOT": "/tmp/repo",
                    "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                }
            ),
            env={},
            process_runner=_RecordingRunner(),
        )
        launch_config = launch_support.PlanAgentLaunchConfig(
            enabled=True,
            transport="cmux",
            cli="opencode",
            cli_command="opencode",
            preset="implement_task",
            codex_cycles=0,
            codex_cycles_warning=None,
            shell="zsh",
            require_cmux_context=True,
            cmux_workspace="",
            direct_prompt_enabled=False,
            ulw_loop_prefix=False,
            ulw_suffix=False,
        )

        prompt_text, error = workflow._resolve_preset_submission_text(
            runtime,
            launch_config=launch_config,
            cli="opencode",
            preset="implement_task",
        )

        self.assertIsNone(error)
        self.assertEqual(prompt_text, "/implement_task")

    def test_implement_task_direct_prompt_injects_current_runtime_addresses(self) -> None:
        runtime = _RuntimeHarness(
            config=load_config({"RUN_REPO_ROOT": "/tmp/repo", "RUN_SH_RUNTIME_DIR": "/tmp/runtime"}),
            env={},
            process_runner=_RecordingRunner(),
        )
        runtime.state_repository = _StateRepositoryHarness(
            RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a Backend": ServiceRecord(
                        name="feature-a Backend",
                        type="backend",
                        cwd="/tmp/repo/backend",
                        actual_port=8201,
                        requested_port=8200,
                        status="running",
                    ),
                    "feature-a Frontend": ServiceRecord(
                        name="feature-a Frontend",
                        type="frontend",
                        cwd="/tmp/repo/frontend",
                        actual_port=9201,
                        status="running",
                    ),
                },
                requirements={
                    "feature-a": RequirementsResult(
                        project="feature-a",
                        components={
                            "postgres": {"enabled": True, "success": True, "final": 5473},
                            "redis": {"enabled": True, "success": True, "final": 6420},
                            "n8n": {"enabled": True, "success": True, "final": 5780},
                            "supabase": {"enabled": False, "success": True, "final": 5633},
                        },
                    )
                },
            )
        )

        prompt_text, error = workflow._resolve_preset_submission_text(
            runtime,
            launch_config=_launch_config_for_tests(cli="codex"),
            cli="codex",
            preset="implement_task",
        )

        self.assertIsNone(error)
        self.assertIn("## Current envctl runtime addresses", prompt_text)
        self.assertIn("Postgres (feature-a): localhost:5473", prompt_text)
        self.assertIn("Redis (feature-a): redis://localhost:6420", prompt_text)
        self.assertIn("n8n (feature-a): http://localhost:5780", prompt_text)
        self.assertIn("Backend (feature-a Backend): http://localhost:8201", prompt_text)
        self.assertIn("Frontend (feature-a Frontend): http://localhost:9201", prompt_text)
        self.assertNotIn("Supabase (feature-a): http://localhost:5633", prompt_text)

    def test_worktree_prompt_does_not_inject_runtime_addresses_from_other_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            target_root = repo / "trees" / "feature-b" / "1"
            target_root.mkdir(parents=True, exist_ok=True)
            runtime = _RuntimeHarness(
                config=load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_dir)}),
                env={},
                process_runner=_RecordingRunner(),
            )
            runtime.state_repository = _StateRepositoryHarness(
                RunState(
                    run_id="run-previous",
                    mode="trees",
                    services={
                        "feature-a-1 Backend": ServiceRecord(
                            name="feature-a-1 Backend",
                            type="backend",
                            cwd=str(repo / "trees" / "feature-a" / "1" / "backend"),
                            actual_port=8201,
                            status="running",
                        )
                    },
                    requirements={
                        "feature-a-1": RequirementsResult(
                            project="feature-a-1",
                            components={"redis": {"enabled": True, "success": True, "final": 6420}},
                        )
                    },
                )
            )

            prompt_text, error = _workflow_step_prompt_text(
                runtime,
                launch_config=_launch_config_for_tests(cli="codex"),
                cli="codex",
                step=workflow._PlanAgentWorkflowStep(kind="submit_direct_prompt", text="implement_task"),
                worktree=CreatedPlanWorktree(name="feature-b-1", root=target_root, plan_file="features/feature-b.md"),
            )

        self.assertIsNone(error)
        self.assertNotIn("## Current envctl runtime addresses", prompt_text)
        self.assertNotIn("feature-a", prompt_text)
        self.assertNotIn("localhost:8201", prompt_text)
        self.assertNotIn("redis://localhost:6420", prompt_text)

    def test_browser_e2e_followup_injects_original_plan_and_runtime_addresses(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            original_plan = repo / "todo" / "plans" / "implementations" / "feature-a.md"
            worktree_root = repo / "trees" / "feature-a" / "1"
            original_plan.parent.mkdir(parents=True, exist_ok=True)
            worktree_root.mkdir(parents=True, exist_ok=True)
            original_plan.write_text("# Original task\n", encoding="utf-8")
            runtime = _RuntimeHarness(
                config=load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_dir)}),
                env={},
                process_runner=_RecordingRunner(),
            )
            runtime.state_repository = _StateRepositoryHarness(
                RunState(
                    run_id="run-1",
                    mode="trees",
                    services={
                        "feature-a Frontend": ServiceRecord(
                            name="feature-a Frontend",
                            type="frontend",
                            cwd=str(worktree_root / "frontend"),
                            actual_port=9300,
                            status="running",
                        )
                    },
                    requirements={
                        "feature-a": RequirementsResult(
                            project="feature-a",
                            components={"postgres": {"enabled": True, "success": True, "final": 5500}},
                        )
                    },
                )
            )

            prompt_text, error = _workflow_step_prompt_text(
                runtime,
                launch_config=_launch_config_for_tests(cli="codex"),
                cli="codex",
                step=workflow._PlanAgentWorkflowStep(
                    kind="queue_message",
                    text=_browser_e2e_instruction_text(),
                ),
                worktree=CreatedPlanWorktree(
                    name="feature-a-1",
                    root=worktree_root,
                    plan_file="implementations/feature-a.md",
                ),
            )

        self.assertIsNone(error)
        self.assertIn("## Original task source for E2E validation", prompt_text)
        self.assertIn(str(original_plan), prompt_text)
        self.assertIn("Use this original plan file before the current MAIN_TASK.md", prompt_text)
        self.assertIn("## Current envctl runtime addresses", prompt_text)
        self.assertIn("Postgres (feature-a): localhost:5500", prompt_text)
        self.assertIn("Frontend (feature-a Frontend): http://localhost:9300", prompt_text)

    def test_browser_e2e_followup_omits_stale_runtime_addresses_for_other_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-b" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            runtime = _RuntimeHarness(
                config=load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_dir)}),
                env={},
                process_runner=_RecordingRunner(),
            )
            runtime.state_repository = _StateRepositoryHarness(
                RunState(
                    run_id="run-previous",
                    mode="trees",
                    services={
                        "feature-a-1 Frontend": ServiceRecord(
                            name="feature-a-1 Frontend",
                            type="frontend",
                            cwd=str(repo / "trees" / "feature-a" / "1" / "frontend"),
                            actual_port=9300,
                            status="running",
                        )
                    },
                    requirements={
                        "feature-a-1": RequirementsResult(
                            project="feature-a-1",
                            components={"n8n": {"enabled": True, "success": True, "final": 5780}},
                        )
                    },
                )
            )

            prompt_text, error = _workflow_step_prompt_text(
                runtime,
                launch_config=_launch_config_for_tests(cli="codex"),
                cli="codex",
                step=workflow._PlanAgentWorkflowStep(
                    kind="queue_message",
                    text=_browser_e2e_instruction_text(),
                ),
                worktree=CreatedPlanWorktree(
                    name="feature-b-1",
                    root=worktree_root,
                    plan_file="features/feature-b.md",
                ),
            )

        self.assertIsNone(error)
        self.assertIn("## Original task source for E2E validation", prompt_text)
        self.assertNotIn("## Current envctl runtime addresses", prompt_text)
        self.assertNotIn("feature-a", prompt_text)
        self.assertNotIn("localhost:9300", prompt_text)
        self.assertNotIn("http://localhost:5780", prompt_text)

    def test_browser_e2e_followup_injects_matching_worktree_runtime_addresses(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-b" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            runtime = _RuntimeHarness(
                config=load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_dir)}),
                env={},
                process_runner=_RecordingRunner(),
            )
            runtime.state_repository = _StateRepositoryHarness(
                RunState(
                    run_id="run-current",
                    mode="trees",
                    services={
                        "feature-b-1 Backend": ServiceRecord(
                            name="feature-b-1 Backend",
                            type="backend",
                            cwd=str(worktree_root / "backend"),
                            actual_port=8300,
                            status="running",
                        )
                    },
                    requirements={
                        "feature-b-1": RequirementsResult(
                            project="feature-b-1",
                            components={"redis": {"enabled": True, "success": True, "final": 6421}},
                        )
                    },
                )
            )

            prompt_text, error = _workflow_step_prompt_text(
                runtime,
                launch_config=_launch_config_for_tests(cli="codex"),
                cli="codex",
                step=workflow._PlanAgentWorkflowStep(
                    kind="queue_message",
                    text=_browser_e2e_instruction_text(),
                ),
                worktree=CreatedPlanWorktree(
                    name="feature-b-1",
                    root=worktree_root,
                    plan_file="features/feature-b.md",
                ),
            )

        self.assertIsNone(error)
        self.assertIn("## Current envctl runtime addresses", prompt_text)
        self.assertIn("Redis (feature-b-1): redis://localhost:6421", prompt_text)
        self.assertIn("Backend (feature-b-1 Backend): http://localhost:8300", prompt_text)

    def test_runtime_addresses_are_not_injected_for_other_direct_presets(self) -> None:
        runtime = _RuntimeHarness(
            config=load_config({"RUN_REPO_ROOT": "/tmp/repo", "RUN_SH_RUNTIME_DIR": "/tmp/runtime"}),
            env={},
            process_runner=_RecordingRunner(),
        )
        runtime.state_repository = _StateRepositoryHarness(
            RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd="/tmp/repo/backend",
                        actual_port=8000,
                    )
                },
                requirements={},
            )
        )

        prompt_text, error = workflow._resolve_preset_submission_text(
            runtime,
            launch_config=_launch_config_for_tests(cli="codex"),
            cli="codex",
            preset="review_worktree_imp",
        )

        self.assertIsNone(error)
        self.assertNotIn("Current envctl runtime addresses", prompt_text)
        self.assertNotIn("localhost:8000", prompt_text)

    def test_resolve_preset_submission_text_prepends_ulw_loop_for_direct_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / ".config" / "opencode" / "commands" / "implement_task.md"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text("Implement this directly.\n", encoding="utf-8")
            runtime = _RuntimeHarness(
                config=load_config(
                    {
                        "RUN_REPO_ROOT": "/tmp/repo",
                        "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                    }
                ),
                env={"HOME": tmpdir},
                process_runner=_RecordingRunner(),
            )
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="cmux",
                cli="opencode",
                cli_command="opencode",
                preset="implement_task",
                codex_cycles=0,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=True,
                ulw_loop_prefix=True,
                ulw_suffix=False,
            )

            prompt_text, error = workflow._resolve_preset_submission_text(
                runtime,
                launch_config=launch_config,
                cli="opencode",
                preset="implement_task",
            )

        self.assertIsNone(error)
        self.assertTrue(prompt_text.startswith("/ulw-loop "))
        self.assertIn("Implement this directly.", prompt_text)

    def test_resolve_preset_submission_text_appends_ulw_suffix_in_slash_mode(self) -> None:
        runtime = _RuntimeHarness(
            config=load_config(
                {
                    "RUN_REPO_ROOT": "/tmp/repo",
                    "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                }
            ),
            env={},
            process_runner=_RecordingRunner(),
        )
        launch_config = launch_support.PlanAgentLaunchConfig(
            enabled=True,
            transport="cmux",
            cli="opencode",
            cli_command="opencode",
            preset="implement_task",
            codex_cycles=0,
            codex_cycles_warning=None,
            shell="zsh",
            require_cmux_context=True,
            cmux_workspace="",
            direct_prompt_enabled=False,
            ulw_loop_prefix=False,
            ulw_suffix=True,
        )

        prompt_text, error = workflow._resolve_preset_submission_text(
            runtime,
            launch_config=launch_config,
            cli="opencode",
            preset="implement_task",
        )

        self.assertIsNone(error)
        self.assertEqual(prompt_text, "/implement_task ulw")

    def test_resolve_preset_submission_text_rejects_ulw_loop_prefix_in_slash_mode(self) -> None:
        runtime = _RuntimeHarness(
            config=load_config(
                {
                    "RUN_REPO_ROOT": "/tmp/repo",
                    "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                }
            ),
            env={},
            process_runner=_RecordingRunner(),
        )
        launch_config = launch_support.PlanAgentLaunchConfig(
            enabled=True,
            transport="cmux",
            cli="opencode",
            cli_command="opencode",
            preset="implement_task",
            codex_cycles=0,
            codex_cycles_warning=None,
            shell="zsh",
            require_cmux_context=True,
            cmux_workspace="",
            direct_prompt_enabled=False,
            ulw_loop_prefix=True,
            ulw_suffix=False,
        )

        prompt_text, error = workflow._resolve_preset_submission_text(
            runtime,
            launch_config=launch_config,
            cli="opencode",
            preset="implement_task",
        )

        self.assertEqual(prompt_text, "")
        self.assertEqual(error, "prompt_resolution_failed: ulw_loop_prefix_requires_direct_prompt")

    def test_shape_prompt_text_rejects_multiple_slash_commands_for_direct_prompts(self) -> None:
        shaped, error = workflow._shape_prompt_text(
            "/implement_task",
            direct_prompt=True,
            ulw_loop_prefix=True,
            ulw_suffix=False,
        )

        self.assertEqual(shaped, "")
        self.assertEqual(error, "prompt_resolution_failed: multiple_slash_commands_not_allowed")

    def test_shape_prompt_text_rejects_embedded_second_slash_command_for_direct_prompts(self) -> None:
        shaped, error = workflow._shape_prompt_text(
            "Implement this directly.\n/implement_task",
            direct_prompt=True,
            ulw_loop_prefix=True,
            ulw_suffix=False,
        )

        self.assertEqual(shaped, "")
        self.assertEqual(error, "prompt_resolution_failed: multiple_slash_commands_not_allowed")

    def test_shape_prompt_text_preserves_existing_ulw_loop_prefix_and_allows_suffix(self) -> None:
        shaped, error = workflow._shape_prompt_text(
            "/ulw-loop Implement this directly.",
            direct_prompt=True,
            ulw_loop_prefix=True,
            ulw_suffix=True,
        )

        self.assertIsNone(error)
        self.assertEqual(shaped, "/ulw-loop Implement this directly. ulw")

    def test_shape_prompt_text_allows_absolute_path_literals_in_direct_prompts(self) -> None:
        shaped, error = workflow._shape_prompt_text(
            'Review bundle: "/tmp/review.md"\nWorktree directory: "/tmp/tree"',
            direct_prompt=True,
            ulw_loop_prefix=True,
            ulw_suffix=False,
        )

        self.assertIsNone(error)
        self.assertTrue(shaped.startswith("/ulw-loop "))
        self.assertIn('Review bundle: "/tmp/review.md"', shaped)

    def test_build_plan_agent_workflow_bounds_large_cycle_counts(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=999)

        self.assertEqual(workflow.mode, "codex_cycles")
        self.assertEqual(workflow.codex_cycles, 3)
        self.assertEqual(len(workflow.steps), 3 + (1 + 3 * (workflow.codex_cycles - 1)))

    def test_codex_cycle_queue_direct_prompt_tabs_without_picker_resolution(self) -> None:
        sent_keys: list[str] = []
        queued_text = "Direct queued prompt body"
        state = {"stage": "typed"}

        queue_hint_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "  Direct queued prompt body\n"
            "  tab to queue message\n"
        )
        committed_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "• Queued follow-up messages\n"
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            if key == "tab":
                state["stage"] = "committed"
            return None

        def fake_read_screen(*_args, **_kwargs):  # noqa: ANN202, ANN001
            if state["stage"] == "typed":
                return queue_hint_screen
            return committed_screen

        runtime = _RuntimeHarness(
            config=load_config(
                {
                    "RUN_REPO_ROOT": "/tmp/repo",
                    "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                }
            ),
            env={},
            process_runner=_RecordingRunner(),
        )

        with (
            patch("envctl_engine.planning.plan_agent.cmux_transport._send_surface_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent.cmux_transport._read_surface_screen", side_effect=fake_read_screen),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = cmux_transport._queue_codex_message(
                runtime,
                workspace_id="workspace:7",
                surface_id="surface:9",
                text=queued_text,
                require_text_match=False,
            )

        self.assertTrue(queued)
        self.assertEqual(sent_keys, ["tab"])

    def test_codex_cycle_queue_direct_prompt_requires_visible_message_text_before_tab(self) -> None:
        sent_keys: list[str] = []
        queued_text = "Direct queued prompt body"
        queue_hint_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "  tab to queue message\n"
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            return None

        runtime = _RuntimeHarness(
            config=load_config(
                {
                    "RUN_REPO_ROOT": "/tmp/repo",
                    "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                }
            ),
            env={},
            process_runner=_RecordingRunner(),
        )

        with (
            patch("envctl_engine.planning.plan_agent.cmux_transport._send_surface_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent.cmux_transport._read_surface_screen", return_value=queue_hint_screen),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = cmux_transport._queue_codex_message(
                runtime,
                workspace_id="workspace:7",
                surface_id="surface:9",
                text=queued_text,
                require_text_match=False,
            )

        self.assertFalse(queued)
        self.assertEqual(sent_keys, [])

    def test_codex_cycle_queue_direct_prompt_accepts_pasted_content_placeholder(self) -> None:
        sent_keys: list[str] = []
        queued_text = "Direct queued prompt body\nwith multiple lines"
        state = {"stage": "typed"}
        queue_hint_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "› [Pasted Content 6674 chars]\n"
            "  tab to queue message\n"
        )
        committed_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "• Queued follow-up messages\n"
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            if key == "tab":
                state["stage"] = "committed"
            return None

        def fake_read_screen(*_args, **_kwargs):  # noqa: ANN202, ANN001
            if state["stage"] == "typed":
                return queue_hint_screen
            return committed_screen

        runtime = _RuntimeHarness(
            config=load_config(
                {
                    "RUN_REPO_ROOT": "/tmp/repo",
                    "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                }
            ),
            env={},
            process_runner=_RecordingRunner(),
        )

        with (
            patch("envctl_engine.planning.plan_agent.cmux_transport._send_surface_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent.cmux_transport._read_surface_screen", side_effect=fake_read_screen),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = cmux_transport._queue_codex_message(
                runtime,
                workspace_id="workspace:7",
                surface_id="surface:9",
                text=queued_text,
                require_text_match=False,
            )

        self.assertTrue(queued)
        self.assertEqual(sent_keys, ["tab"])

    def test_review_prompt_arguments_preserve_newlines_for_direct_codex_submission(self) -> None:
        rendered = workflow._review_prompt_arguments(
            project_name="feature-a-1",
            project_root=Path("/tmp/worktree path"),
            review_bundle_path=Path("/tmp/review bundle.md"),
            original_plan_path=Path("/tmp/original plan.md"),
        )

        self.assertEqual(
            rendered,
            'Project: feature-a-1\n'
            'Review bundle: "/tmp/review bundle.md"\n'
            'Worktree directory: "/tmp/worktree path"\n'
            'Original plan file: "/tmp/original plan.md"',
        )

    def test_prompt_submit_screen_accepts_multiline_direct_prompt_once_each_line_is_visible(self) -> None:
        screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "Review bundle: /tmp/review.md\n"
            "Worktree directory: /tmp/tree\n"
            "Original plan file: /tmp/plan.md\n"
        )
        prompt_text = "Review bundle: /tmp/review.md\nWorktree directory: /tmp/tree\nOriginal plan file: /tmp/plan.md"

        self.assertTrue(_prompt_submit_screen_looks_ready("codex", screen, prompt_text))

    def test_prompt_submit_screen_rejects_multiline_direct_prompt_when_line_missing(self) -> None:
        screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "Review bundle: /tmp/review.md\n"
            "Worktree directory: /tmp/tree\n"
        )
        prompt_text = "Review bundle: /tmp/review.md\nWorktree directory: /tmp/tree\nOriginal plan file: /tmp/plan.md"

        self.assertFalse(_prompt_submit_screen_looks_ready("codex", screen, prompt_text))

    def test_tab_title_for_worktree_uses_first_and_last_three_words(self) -> None:
        self.assertEqual(
            _tab_title_for_worktree("refactoring_envctl_ai_pr_fix-1"),
            "refactoring_ai_pr_fix-1",
        )

    def test_tab_title_for_worktree_drops_third_from_last_word_when_still_too_long(self) -> None:
        self.assertEqual(
            _tab_title_for_worktree("refactoring_envctl_python_engine_cutover_reliability_plan-1"),
            "refactoring_reliability_plan-1",
        )

    def test_tab_title_for_worktree_skips_low_signal_origin_token(self) -> None:
        self.assertEqual(
            _tab_title_for_worktree("features_envctl_prompt_overwrite_confirmation_and_origin_review_preset-1"),
            "features_review_preset-1",
        )

    def test_review_launch_uses_direct_prompt_submission_for_opencode_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "feature-a" / "1"
            review_bundle = repo / "runtime" / "review" / "all.md"
            original_plan = repo / "todo" / "plans" / "implementations" / "feature-a.md"
            installed_prompt = Path(tmpdir) / ".config" / "opencode" / "commands" / "review_worktree_imp.md"
            project_root.mkdir(parents=True, exist_ok=True)
            review_bundle.parent.mkdir(parents=True, exist_ok=True)
            original_plan.parent.mkdir(parents=True, exist_ok=True)
            installed_prompt.parent.mkdir(parents=True, exist_ok=True)
            review_bundle.write_text("# review\n", encoding="utf-8")
            original_plan.write_text("# Current plan\n", encoding="utf-8")
            installed_prompt.write_text("Review prompt body\n$ARGUMENTS\n", encoding="utf-8")
            (project_root / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (project_root / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps({"schema_version": 1, "plan_file": "implementations/feature-a.md"}) + "\n",
                encoding="utf-8",
            )
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "HOME": tmpdir,
                    "ENVCTL_PLAN_AGENT_CLI": "opencode",
                    "ENVCTL_PLAN_AGENT_DIRECT_PROMPT": "true",
                    "ENVCTL_PLAN_AGENT_ULW_LOOP_PREFIX": "true",
                    "ENVCTL_PLAN_AGENT_APPEND_ULW": "true",
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "workspace:9",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:15\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_cli_ready", return_value=None),
            ):
                _ImmediateThread.created = []
                result = launch_support.launch_review_agent_terminal(
                    rt,
                    repo_root=repo,
                    project_name="feature-a-1",
                    project_root=project_root,
                    review_bundle_path=review_bundle,
                )

            self.assertEqual(result.status, "launched")
            direct_prompt_calls = [
                call
                for call in rt.process_runner.calls
                if call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-15"]
            ]
            self.assertEqual(len(direct_prompt_calls), 1)
            self.assertTrue(str(direct_prompt_calls[0][-1]).startswith("/ulw-loop Review prompt body"))
            self.assertIn(f'Review bundle: "{review_bundle}"', str(direct_prompt_calls[0][-1]))
            self.assertIn(f'Original plan file: "{original_plan.resolve()}" ulw', str(direct_prompt_calls[0][-1]))
            self.assertTrue(str(direct_prompt_calls[0][-1]).rstrip().endswith("ulw"))
            self.assertIn(
                ["cmux", "paste-buffer", "--name", "envctl-surface-15", "--workspace", "workspace:9", "--surface", "surface:15"],
                rt.process_runner.calls,
            )
