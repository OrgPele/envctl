# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchOmxConfigTests(PlanAgentLaunchSupportTestCase):
    def test_plan_agent_launch_prereqs_switch_to_omx_for_omx_route(self) -> None:
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
                route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
            )

        self.assertEqual(prereqs, ("omx", "tmux", "script", "codex"))

    def test_resolve_plan_agent_launch_config_accepts_omx_route_flag(self) -> None:
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
                route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
            )

        self.assertEqual(launch_config.transport, "omx")
        self.assertEqual(launch_config.cli, "codex")
        self.assertTrue(launch_config.enabled)

    def test_resolve_plan_agent_launch_config_records_omx_workflow_flag(self) -> None:
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

            for token, workflow_name in (("--ultragoal", "ultragoal"), ("--ralph", "ralph"), ("--team", "team")):
                with self.subTest(token=token):
                    launch_config = launch_support.resolve_plan_agent_launch_config(
                        config,
                        {},
                        route=parse_route(["--plan", "feature-a", "--omx", token], env={}),
                    )

                    self.assertEqual(launch_config.transport, "omx")
                    self.assertEqual(launch_config.cli, "codex")
                    self.assertEqual(launch_config.omx_workflow, workflow_name)
                    self.assertEqual(launch_config.codex_cycles, 2)

    def test_resolve_plan_agent_launch_config_keeps_cycles_for_plain_omx(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "3",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--omx"], env={}),
            )

        self.assertEqual(launch_config.transport, "omx")
        self.assertEqual(launch_config.cli, "codex")
        self.assertEqual(launch_config.codex_cycles, 3)
        self.assertIsNone(launch_config.codex_cycles_warning)

    def test_resolve_plan_agent_launch_config_keeps_cycles_for_omx_workflows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "3",
                }
            )

            for token, workflow_name in (("--ultragoal", "ultragoal"), ("--ralph", "ralph"), ("--team", "team")):
                with self.subTest(token=token):
                    launch_config = launch_support.resolve_plan_agent_launch_config(
                        config,
                        {},
                        route=parse_route(["--plan", "feature-a", "--omx", token], env={}),
                    )
                    workflow = _build_plan_agent_workflow(
                        cli=launch_config.cli,
                        preset=launch_config.preset,
                        codex_cycles=launch_config.codex_cycles,
                        direct_prompt_enabled=launch_config.direct_prompt_enabled,
                    )

                    self.assertEqual(launch_config.omx_workflow, workflow_name)
                    self.assertEqual(launch_config.codex_cycles, 3)
                    self.assertIsNone(launch_config.codex_cycles_warning)
                    self.assertEqual(workflow.mode, "codex_cycles")
                    self.assertEqual(workflow.codex_cycles, 3)
                    self.assertEqual(len(workflow.steps), 8)
                    self.assertEqual(workflow.steps[1].text, _first_cycle_completion_instruction_text())
                    self.assertNotIn(_browser_e2e_instruction_text(), [step.text for step in workflow.steps])
                    self.assertNotIn(_pr_review_comments_instruction_text(), [step.text for step in workflow.steps])

    def test_resolve_plan_agent_launch_config_forces_codex_for_omx_when_env_prefers_opencode(self) -> None:
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
                route=parse_route(["--plan", "feature-a", "--omx"], env={}),
            )

        self.assertEqual(launch_config.transport, "omx")
        self.assertEqual(launch_config.cli, "codex")
        self.assertEqual(launch_config.cli_command, "codex --dangerously-bypass-approvals-and-sandbox")

    def test_missing_launch_commands_includes_script_for_omx(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            launch_config = launch_support.resolve_plan_agent_launch_config(
                cast(Any, rt.config),
                rt.env,
                route=parse_route(["--plan", "feature-a", "--omx"], env={}),
            )

            with patch.object(rt, "_command_exists", side_effect=lambda command: command != "script"):
                missing = config._missing_launch_commands(rt, launch_config)

            self.assertEqual(missing, ["script"])

    def test_new_session_command_preserves_omx_workflow_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="feature-a.md")
            for token, workflow_name in (("--ultragoal", "ultragoal"), ("--ralph", "ralph"), ("--team", "team")):
                with self.subTest(token=token):
                    command = recovery._new_session_command_for_route(
                        rt,
                        route=parse_route(["--plan", "feature-a", "--omx", token, "--headless"], env={}),
                        launch_config=launch_support.PlanAgentLaunchConfig(
                            enabled=True,
                            transport="omx",
                            cli="codex",
                            cli_command="codex --dangerously-bypass-approvals-and-sandbox",
                            preset="implement_task",
                            codex_cycles=0,
                            codex_cycles_warning=None,
                            shell="zsh",
                            require_cmux_context=True,
                            cmux_workspace="",
                            direct_prompt_enabled=False,
                            ulw_loop_prefix=False,
                            ulw_suffix=False,
                            omx_workflow=cast(Any, workflow_name),
                        ),
                        created_worktrees=(worktree,),
                    )

                    self.assertIn(token, command)
                    self.assertLess(command.index(token), command.index("--new-session"))
