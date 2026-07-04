# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchWorkflowPromptTests(PlanAgentLaunchSupportTestCase):
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

    def test_workflow_step_prompt_text_injects_worktree_code_intelligence_context(self) -> None:
        self.assertIsNotNone(_workflow_step_prompt_text)
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / ".config" / "envctl" / "codex" / "prompts" / "implement_task.md"
            worktree_root = Path(tmpdir) / "repo" / "trees" / "feature-a" / "1"
            metadata_path = worktree_root / ".envctl-state" / "code-intelligence.json"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            metadata_path.parent.mkdir(parents=True, exist_ok=True)
            (worktree_root / ".serena").mkdir(parents=True, exist_ok=True)
            (worktree_root / ".serena" / "project.local.yml").write_text(
                'project_name: "repo-feature-a-1"\n',
                encoding="utf-8",
            )
            (worktree_root / ".codegraph").mkdir(parents=True, exist_ok=True)
            (worktree_root / ".codegraph" / "codegraph.db").write_text("index\n", encoding="utf-8")
            prompt_path.write_text("Implement this task carefully.\n", encoding="utf-8")
            metadata_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "serena_project_name": "repo-feature-a-1",
                        "files": {".serena/project.yml": True, ".codegraph/codegraph.db": True},
                        "codegraph_index_mode": "auto",
                        "codegraph_index_succeeded": True,
                    }
                )
                + "\n",
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
            step = workflow._PlanAgentWorkflowStep(kind="submit_direct_prompt", text="implement_task")
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="feature-a.md")

            prompt_text, error = _workflow_step_prompt_text(
                runtime,
                launch_config=_launch_config_for_tests(cli="codex"),
                cli="codex",
                step=step,
                worktree=worktree,
            )

        self.assertIsNone(error)
        self.assertIn("Implement this task carefully.", prompt_text)
        self.assertIn("## Worktree code intelligence", prompt_text)
        self.assertIn("Serena project `repo-feature-a-1`", prompt_text)
        self.assertIn("CodeGraph index `.codegraph/` is available", prompt_text)

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
