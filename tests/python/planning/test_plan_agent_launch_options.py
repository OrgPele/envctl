# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchOptionsTests(PlanAgentLaunchSupportTestCase):
    def test_disabled_feature_returns_skipped_without_running_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
            )

            self.assertEqual(result.status, "skipped")
            self.assertEqual(result.reason, "disabled")
            self.assertEqual(rt.process_runner.calls, [])

    def test_enabled_feature_without_created_worktrees_returns_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true"})

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a"], env={}),
                created_worktrees=(),
            )

            self.assertEqual(result.status, "skipped")
            self.assertEqual(result.reason, "no_new_worktrees")
            self.assertEqual(rt.process_runner.calls, [])

    def test_missing_cmux_context_skips_when_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true"})

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "skipped")
            self.assertEqual(result.reason, "missing_cmux_context")
            self.assertIn("Plan agent launch skipped", buffer.getvalue())
            self.assertEqual(rt.process_runner.calls, [])

    def test_missing_cmux_executable_returns_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "CMUX_WORKSPACE_ID": "workspace:7",
                },
            )
            rt._command_exists = lambda command: command in {"codex", "zsh"}  # type: ignore[assignment]

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.reason, "missing_executables")
            self.assertEqual(rt.process_runner.calls, [])

    def test_missing_selected_ai_cli_returns_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CLI": "opencode",
                    "CMUX_WORKSPACE_ID": "workspace:7",
                },
            )
            rt._command_exists = lambda command: command in {"cmux", "zsh"}  # type: ignore[assignment]

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.reason, "missing_executables")
            self.assertEqual(rt.process_runner.calls, [])

    def test_plan_agent_launch_prereqs_switch_to_tmux_for_tmux_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )

            prereqs = launch_support.plan_agent_launch_prereq_commands(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={}),
            )

        self.assertEqual(prereqs, ("tmux", "opencode"))

    def test_resolve_plan_agent_launch_config_uses_tmux_and_opencode_route_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={}),
            )

        self.assertEqual(launch_config.transport, "tmux")
        self.assertEqual(launch_config.cli, "opencode")
        self.assertTrue(launch_config.enabled)

    def test_resolve_plan_agent_launch_config_treats_explicit_opencode_as_default_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )

            with patch("envctl_engine.planning.plan_agent.config.shutil.which", return_value="/usr/local/bin/cmux"):
                launch_config = launch_support.resolve_plan_agent_launch_config(
                    config,
                    {},
                    route=parse_route(["--plan", "feature-a", "--opencode"], env={}),
                )
                prereqs = launch_support.plan_agent_launch_prereq_commands(
                    config,
                    {},
                    route=parse_route(["--plan", "feature-a", "--opencode"], env={}),
                )

        self.assertEqual(launch_config.transport, "cmux")
        self.assertEqual(launch_config.cli, "opencode")
        self.assertTrue(launch_config.enabled)
        self.assertTrue(launch_config.direct_prompt_enabled)
        self.assertTrue(launch_config.ulw_loop_prefix)
        self.assertEqual(prereqs, ("cmux", "opencode"))

    def test_resolve_plan_agent_launch_config_honors_cmux_opencode_route_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--cmux", "--opencode"], env={}),
            )
            prereqs = launch_support.plan_agent_launch_prereq_commands(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--cmux", "--opencode"], env={}),
            )

        self.assertEqual(launch_config.transport, "cmux")
        self.assertEqual(launch_config.cli, "opencode")
        self.assertTrue(launch_config.enabled)
        self.assertTrue(launch_config.direct_prompt_enabled)
        self.assertTrue(launch_config.ulw_loop_prefix)
        self.assertEqual(prereqs, ("cmux", "opencode"))

    def test_resolve_plan_agent_launch_config_ulw_route_enables_direct_prompt_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_DIRECT_PROMPT": "false",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--ulw"], env={}),
            )

        self.assertTrue(launch_config.direct_prompt_enabled)
        self.assertTrue(launch_config.ulw_loop_prefix)

    def test_resolve_plan_agent_launch_config_no_ulw_loop_route_disables_default_prefix(self) -> None:
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
                route=parse_route(["--plan", "feature-a", "--cmux", "--opencode", "--no-ulw-loop"], env={}),
            )
            rt = self._runtime(repo, runtime, env={"HOME": tmpdir})

            prompt_text, error = workflow._resolve_preset_submission_text(
                rt,
                launch_config=launch_config,
                cli="opencode",
                preset="implement_task",
            )

        self.assertEqual(launch_config.transport, "cmux")
        self.assertTrue(launch_config.direct_prompt_enabled)
        self.assertFalse(launch_config.ulw_loop_prefix)
        self.assertIsNone(error)
        self.assertEqual(prompt_text, "Implement this directly.\n")

    def test_create_plan_auto_launch_default_routes_remain_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )

            codex_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {"ENVCTL_PLAN_AGENT_CODEX_CYCLES": "3"},
                route=parse_route(["--plan", "features/example", "--tmux"], env={}),
            )
            codex_workflow = _build_plan_agent_workflow(
                cli=codex_config.cli,
                preset=codex_config.preset,
                codex_cycles=codex_config.codex_cycles,
                direct_prompt_enabled=codex_config.direct_prompt_enabled,
            )

            opencode_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "features/example", "--tmux", "--opencode", "--ulw"], env={}),
            )
            opencode_workflow = _build_plan_agent_workflow(
                cli=opencode_config.cli,
                preset=opencode_config.preset,
                codex_cycles=opencode_config.codex_cycles,
                direct_prompt_enabled=opencode_config.direct_prompt_enabled,
            )

            omx_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {"ENVCTL_PLAN_AGENT_CODEX_CYCLES": "3"},
                route=parse_route(["--plan", "features/example", "--omx", "--ultragoal"], env={}),
            )
            omx_workflow = _build_plan_agent_workflow(
                cli=omx_config.cli,
                preset=omx_config.preset,
                codex_cycles=omx_config.codex_cycles,
                direct_prompt_enabled=omx_config.direct_prompt_enabled,
            )

        self.assertEqual(codex_config.transport, "tmux")
        self.assertEqual(codex_config.cli, "codex")
        self.assertEqual(codex_config.preset, "implement_task")
        self.assertEqual(codex_config.codex_cycles, 3)
        self.assertTrue(codex_config.pr_review_comments_followup_enable)
        self.assertEqual(codex_workflow.mode, "codex_cycles")
        self.assertEqual(codex_workflow.codex_cycles, 3)

        self.assertEqual(opencode_config.transport, "tmux")
        self.assertEqual(opencode_config.cli, "opencode")
        self.assertTrue(opencode_config.direct_prompt_enabled)
        self.assertTrue(opencode_config.ulw_loop_prefix)
        self.assertEqual(opencode_workflow.mode, "single_prompt")

        self.assertEqual(omx_config.transport, "omx")
        self.assertEqual(omx_config.cli, "codex")
        self.assertEqual(omx_config.omx_workflow, "ultragoal")
        self.assertEqual(omx_config.codex_cycles, 3)
        self.assertIsNone(omx_config.codex_cycles_warning)
        self.assertTrue(omx_config.pr_review_comments_followup_enable)
        self.assertEqual(omx_workflow.mode, "codex_cycles")

    def test_cmux_flag_enables_default_plan_agent_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime)})

            default_config = launch_support.resolve_plan_agent_launch_config(
                config, {}, route=parse_route(["--plan", "feature-a"], env={})
            )
            cmux_config = launch_support.resolve_plan_agent_launch_config(
                config, {}, route=parse_route(["--plan", "feature-a", "--cmux"], env={})
            )

        self.assertFalse(default_config.enabled)
        self.assertEqual(default_config.transport, "cmux")
        self.assertTrue(cmux_config.enabled)
        self.assertEqual(cmux_config.transport, "cmux")
        self.assertEqual(cmux_config.cli, "codex")

    def test_default_plan_agent_transport_prefers_cmux_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime)})

            with patch("envctl_engine.planning.plan_agent.config.shutil.which", return_value="/usr/local/bin/cmux"):
                default_config = launch_support.resolve_plan_agent_launch_config(
                    config,
                    {},
                    route=parse_route(["--plan", "feature-a"], env={}),
                )
                opencode_config = launch_support.resolve_plan_agent_launch_config(
                    config,
                    {},
                    route=parse_route(["--plan", "feature-a", "--opencode"], env={}),
                )

        self.assertEqual(default_config.transport, "cmux")
        self.assertEqual(opencode_config.transport, "cmux")
        self.assertEqual(opencode_config.cli, "opencode")

    def test_default_plan_agent_transport_falls_back_to_tmux_without_cmux(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime)})

            with patch("envctl_engine.planning.plan_agent.config.shutil.which", return_value=None):
                default_config = launch_support.resolve_plan_agent_launch_config(
                    config,
                    {},
                    route=parse_route(["--plan", "feature-a"], env={}),
                )
                opencode_config = launch_support.resolve_plan_agent_launch_config(
                    config,
                    {},
                    route=parse_route(["--plan", "feature-a", "--opencode"], env={}),
                )

        self.assertEqual(default_config.transport, "tmux")
        self.assertFalse(default_config.enabled)
        self.assertEqual(opencode_config.transport, "tmux")
        self.assertEqual(opencode_config.cli, "opencode")

    def test_resolve_plan_agent_launch_config_goal_defaults_and_route_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime)})

            codex_default = launch_support.resolve_plan_agent_launch_config(
                config, {}, route=parse_route(["--plan", "feature-a", "--tmux"], env={})
            )
            opencode_default = launch_support.resolve_plan_agent_launch_config(
                config, {}, route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={})
            )
            disabled = launch_support.resolve_plan_agent_launch_config(
                config, {}, route=parse_route(["--plan", "feature-a", "--tmux", "--no-goal", "--goal"], env={})
            )
            enabled_by_route = launch_support.resolve_plan_agent_launch_config(
                load_config({
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE": "false",
                }),
                {},
                route=parse_route(["--plan", "feature-a", "--tmux", "--goal"], env={}),
            )

        self.assertTrue(codex_default.codex_goal_enable)
        self.assertFalse(opencode_default.codex_goal_enable)
        self.assertFalse(disabled.codex_goal_enable)
        self.assertTrue(enabled_by_route.codex_goal_enable)

    def test_resolve_plan_agent_launch_config_allows_pr_review_comment_followup_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            (repo / ".envctl").write_text(
                "ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE=false\n",
                encoding="utf-8",
            )
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "features/example", "--omx", "--ralph"], env={}),
            )
            workflow = _build_plan_agent_workflow(
                cli=launch_config.cli,
                preset=launch_config.preset,
                codex_cycles=launch_config.codex_cycles,
                direct_prompt_enabled=launch_config.direct_prompt_enabled,
                pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
            )

        self.assertFalse(launch_config.pr_review_comments_followup_enable)
        self.assertNotIn(_pr_review_comments_instruction_text(), [step.text for step in workflow.steps])

    def test_resolve_plan_agent_launch_config_allows_browser_e2e_followup_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            (repo / ".envctl").write_text(
                "ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE=false\n",
                encoding="utf-8",
            )
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "features/example"], env={}),
            )
            workflow = _build_plan_agent_workflow(
                cli=launch_config.cli,
                preset=launch_config.preset,
                codex_cycles=launch_config.codex_cycles,
                direct_prompt_enabled=launch_config.direct_prompt_enabled,
                browser_e2e_followup_enable=launch_config.browser_e2e_followup_enable,
                pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
            )

        self.assertFalse(launch_config.browser_e2e_followup_enable)
        self.assertNotIn(_browser_e2e_instruction_text(), [step.text for step in workflow.steps])
        self.assertIn(_pr_review_comments_instruction_text(), [step.text for step in workflow.steps])

    def test_launch_plan_agent_terminals_rejects_ulw_without_opencode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true"})

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a", "--tmux", "--codex", "--ulw"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
            )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "unsupported_ulw_flag")

    def test_resolve_plan_agent_launch_config_accepts_explicit_codex_route_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_CLI": "opencode",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--tmux", "--codex"], env={}),
            )

        self.assertEqual(launch_config.transport, "tmux")
        self.assertEqual(launch_config.cli, "codex")
        self.assertEqual(launch_config.cli_command, "codex --dangerously-bypass-approvals-and-sandbox")
        self.assertTrue(launch_config.enabled)

    def test_resolve_plan_agent_launch_config_allows_disabling_codex_yolo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_CODEX_YOLO": "false",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--tmux", "--codex"], env={}),
            )

        self.assertEqual(launch_config.transport, "tmux")
        self.assertEqual(launch_config.cli, "codex")
        self.assertEqual(launch_config.cli_command, "codex")
        self.assertTrue(launch_config.enabled)

    def test_new_session_flag_creates_suffixed_session_for_existing_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            rt = self._runtime(repo, runtime)
            rt._command_exists = lambda command: command in {"tmux", "opencode", "zsh"}  # type: ignore[assignment]
            base_session = _tmux_session_name_for_worktree(repo, worktree, cli="opencode")
            new_session = f"{base_session}-2"
            existing_attach_target = launch_support.PlanAgentAttachTarget(
                repo_root=repo,
                session_name=base_session,
                window_name="feature-a-1",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", base_session),
            )
            launched_sessions: list[str] = []

            def launch_single(_runtime: object, **kwargs: object) -> launch_support.PlanAgentLaunchOutcome:
                launched_sessions.append(str(kwargs["session_name"]))
                return launch_support.PlanAgentLaunchOutcome(
                    worktree_name=worktree.name,
                    worktree_root=worktree.root,
                    surface_id=None,
                    status="launched",
                )

            with (
                patch("envctl_engine.planning.plan_agent.tmux_transport._find_existing_tmux_attach_target", return_value=existing_attach_target),
                patch("envctl_engine.planning.plan_agent.tmux_transport._next_available_tmux_session_name", return_value=new_session) as next_session_mock,
                patch("envctl_engine.planning.plan_agent.tmux_transport._launch_single_tmux_worktree", side_effect=launch_single),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--new-session", "--headless"], env={}),
                    created_worktrees=(worktree,),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(launched_sessions, [new_session])
            next_session_mock.assert_called_once_with(rt, base_session)
            self.assertIsNotNone(result.attach_target)
            assert result.attach_target is not None
            self.assertEqual(result.attach_target.session_name, new_session)
            self.assertEqual(result.attach_target.attach_command, ("tmux", "attach", "-t", new_session))

    def test_new_session_command_preserves_ulw_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="feature-a.md")
            command = recovery._new_session_command_for_route(
                rt,
                route=parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--ulw", "--headless"], env={}),
                launch_config=launch_support.PlanAgentLaunchConfig(
                    enabled=True,
                    transport="tmux",
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
                ),
                created_worktrees=(worktree,),
            )

        self.assertEqual(
            command,
            (
                "ENVCTL_USE_REPO_WRAPPER=1",
                str(repo.resolve() / "bin" / "envctl"),
                "--plan",
                "feature-a",
                "--tmux",
                "--opencode",
                "--ulw",
                "--new-session",
                "--headless",
            ),
        )

    def test_new_session_command_preserves_no_ulw_loop_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="feature-a.md")
            command = recovery._new_session_command_for_route(
                rt,
                route=parse_route(["--plan", "feature-a", "--cmux", "--opencode", "--no-ulw-loop", "--headless"], env={}),
                launch_config=launch_support.PlanAgentLaunchConfig(
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
                ),
                created_worktrees=(worktree,),
        )

        self.assertIn("--cmux", command)
        self.assertNotIn("--tmux", command)
        self.assertIn("--no-ulw-loop", command)
        self.assertLess(command.index("--no-ulw-loop"), command.index("--new-session"))

    def test_resolve_plan_agent_launch_config_parses_codex_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "2",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

        self.assertEqual(launch_config.codex_cycles, 2)
        self.assertIsNone(launch_config.codex_cycles_warning)

    def test_resolve_plan_agent_launch_config_applies_cycles_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "CYCLES": "3",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

        self.assertEqual(launch_config.codex_cycles, 3)
        self.assertIsNone(launch_config.codex_cycles_warning)

    def test_resolve_plan_agent_launch_config_prefers_canonical_cycles_over_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "3",
                    "CYCLES": "2",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

        self.assertEqual(launch_config.codex_cycles, 3)
        self.assertIsNone(launch_config.codex_cycles_warning)

    def test_resolve_plan_agent_launch_config_bounds_above_maximum_canonical_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "4",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

        self.assertEqual(launch_config.codex_cycles, 3)
        self.assertEqual(launch_config.codex_cycles_warning, "bounded_codex_cycles")

    def test_resolve_plan_agent_launch_config_reports_invalid_cycles_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "CYCLES": "many",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

        self.assertEqual(launch_config.codex_cycles, 0)
        self.assertEqual(launch_config.codex_cycles_warning, "invalid_codex_cycles")

    def test_resolve_plan_agent_launch_config_bounds_large_cycles_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "CYCLES": "999",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

        self.assertEqual(launch_config.codex_cycles, 3)
        self.assertEqual(launch_config.codex_cycles_warning, "bounded_codex_cycles")

    def test_resolve_plan_agent_launch_config_ignores_invalid_codex_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "many",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

        self.assertEqual(launch_config.codex_cycles, 0)
        self.assertEqual(launch_config.codex_cycles_warning, "invalid_codex_cycles")

    def test_resolve_plan_agent_launch_config_parses_direct_prompt_and_ulw_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_DIRECT_PROMPT": "true",
                    "ENVCTL_PLAN_AGENT_ULW_LOOP_PREFIX": "true",
                    "ENVCTL_PLAN_AGENT_APPEND_ULW": "true",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

        self.assertTrue(launch_config.direct_prompt_enabled)
        self.assertTrue(launch_config.ulw_loop_prefix)
        self.assertTrue(launch_config.ulw_suffix)
