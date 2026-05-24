# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchTransportOptionsTests(PlanAgentLaunchSupportTestCase):
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
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "CMUX": "false",
                        "CMUX_WORKSPACE_ID": "",
                        "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "",
                        "ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT": "",
                    }
                )

                with patch("envctl_engine.planning.plan_agent.config.shutil.which", return_value="/usr/local/bin/cmux"):
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
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "CMUX": "false",
                        "CMUX_WORKSPACE_ID": "",
                        "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "",
                        "ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT": "",
                    }
                )

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
                config = load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "CMUX": "false",
                        "CMUX_WORKSPACE_ID": "",
                        "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "",
                        "ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT": "",
                    }
                )

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
