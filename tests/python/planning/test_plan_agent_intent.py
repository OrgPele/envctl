from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from envctl_engine.config import load_config
from envctl_engine.planning import plan_agent_launch_support as launch_support
from envctl_engine.planning.plan_agent import intent
from envctl_engine.runtime.command_router import parse_route


class PlanAgentIntentTests(unittest.TestCase):
    def test_launch_intent_option_matrix_covers_transport_flags(self) -> None:
        cases = (
            (["--plan", "feature-a"], {}, "cmux", "codex", False, "cmux_context"),
            (["--plan", "feature-a", "--cmux"], {}, "cmux", "codex", True, "cmux_context"),
            (["--plan", "feature-a", "--tmux"], {}, "tmux", "codex", True, "tmux_cli"),
            (["--plan", "feature-a", "--omx"], {}, "omx", "codex", True, "omx_session"),
            (["--plan", "feature-a", "--opencode"], {}, "tmux", "opencode", True, "tmux_cli"),
            (["--plan", "feature-a", "--cmux", "--opencode"], {}, "cmux", "opencode", True, "cmux_context"),
            (
                ["--plan", "feature-a"],
                {"ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT": "superset"},
                "superset",
                "codex",
                False,
                "superset_workspace",
            ),
        )
        for argv, env, expected_transport, expected_cli, expected_route_launch, expected_readiness in cases:
            with self.subTest(argv=argv, env=env):
                launch_intent = intent.resolve_plan_agent_launch_intent(
                    env_map=env,
                    config_raw={},
                    route=parse_route(argv, env={}),
                )

                self.assertEqual(launch_intent.transport, expected_transport)
                self.assertEqual(launch_intent.cli, expected_cli)
                self.assertEqual(launch_intent.route_launch_requested, expected_route_launch)
                self.assertEqual(launch_intent.readiness_expectation, expected_readiness)

    def test_launch_config_uses_shared_transport_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config_obj = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT": "invalid",
                }
            )

            route = parse_route(["--plan", "feature-a"], env={})
            launch_intent = intent.resolve_plan_agent_launch_intent(
                env_map={},
                config_raw=config_obj.raw,
                route=route,
            )
            launch_config = launch_support.resolve_plan_agent_launch_config(config_obj, {}, route=route)

        self.assertEqual(launch_intent.transport, launch_config.transport)
        self.assertEqual(launch_intent.cli, launch_config.cli)
        self.assertEqual(launch_intent.surface_transport_warning, "invalid_surface_transport")
        self.assertEqual(launch_config.surface_transport_warning, launch_intent.surface_transport_warning)


if __name__ == "__main__":
    unittest.main()
