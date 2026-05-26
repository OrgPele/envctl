# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *

from envctl_engine.planning.plan_agent.launch_policy import PlanAgentLaunchPolicy


class PlanAgentLaunchPolicyTests(PlanAgentLaunchSupportTestCase):
    def test_prereq_policy_uses_available_default_transport_and_selected_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CLI": "opencode",
                }
            )

            policy = PlanAgentLaunchPolicy(
                config=config,
                env={},
                route=parse_route(["--plan", "feature-a"], env={}),
                command_available=lambda command: "/usr/bin/tmux" if command == "tmux" else None,
            )

            launch_config = policy.resolve_launch_config()
            self.assertEqual(launch_config.transport, "cmux")
            self.assertEqual(launch_config.cli, "opencode")
            self.assertEqual(policy.prereq_commands(), ("tmux", "opencode"))

    def test_prereq_policy_preserves_explicit_cmux_transport_even_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CLI": "opencode",
                }
            )

            policy = PlanAgentLaunchPolicy(
                config=config,
                env={},
                route=parse_route(["--plan", "feature-a", "--cmux"], env={}),
                command_available=lambda _command: None,
            )

            launch_config = policy.resolve_launch_config()
            self.assertEqual(launch_config.transport, "cmux")
            self.assertEqual(policy.prereq_commands(), ("cmux", "opencode"))

    def test_policy_rejects_ulw_for_non_opencode_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                }
            )

            policy = PlanAgentLaunchPolicy(
                config=config,
                env={},
                route=parse_route(["--plan", "feature-a", "--tmux", "--codex", "--ulw"], env={}),
            )

            self.assertTrue(policy.route_requests_ulw())
            self.assertFalse(policy.ulw_route_supported(policy.resolve_launch_config()))
