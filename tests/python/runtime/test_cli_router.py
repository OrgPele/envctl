from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import RouteError, parse_route


class CliRouterTests(unittest.TestCase):
    def test_mode_aliases_map_to_trees(self) -> None:
        for token in ("--tree", "--trees", "trees=true"):
            route = parse_route([token], env={})
            self.assertEqual(route.mode, "trees")

    def test_default_mode_comes_from_envctl_default_mode(self) -> None:
        route = parse_route([], env={"ENVCTL_DEFAULT_MODE": "trees"})
        self.assertEqual(route.mode, "trees")

    def test_invalid_typo_alias_is_rejected(self) -> None:
        with self.assertRaises(RouteError):
            parse_route(["tees=true"], env={})

    def test_plan_flags_route_to_plan_command(self) -> None:
        for token in (
            "--plan",
            "plan",
            "parallel-plan",
            "--parallel-plan",
            "--plan-selection",
            "--planning-envs",
            "--plan-parallel",
            "--plan-sequential",
        ):
            route = parse_route([token], env={})
            self.assertEqual(route.command, "plan")
            self.assertEqual(route.mode, "trees")

    def test_resume_command_is_parsed(self) -> None:
        route = parse_route(["--resume"], env={})
        self.assertEqual(route.command, "resume")

    def test_non_interactive_aliases_enable_batch_flag(self) -> None:
        for token in ("--headless", "--batch", "--non-interactive", "--no-interactive", "-b"):
            route = parse_route(["--dashboard", token], env={})
            self.assertEqual(route.command, "dashboard")
            self.assertTrue(route.flags.get("batch"), msg=token)

    def test_tmux_and_opencode_flags_are_parsed(self) -> None:
        route = parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--tmux-new-session", "--headless"], env={})
        self.assertEqual(route.command, "plan")
        self.assertTrue(route.flags.get("tmux"))
        self.assertTrue(route.flags.get("opencode"))
        self.assertTrue(route.flags.get("tmux_new_session"))
        self.assertTrue(route.flags.get("batch"))

    def test_tmux_and_codex_flags_are_parsed(self) -> None:
        route = parse_route(["--plan", "feature-a", "--tmux", "--codex"], env={})
        self.assertEqual(route.command, "plan")
        self.assertTrue(route.flags.get("tmux"))
        self.assertTrue(route.flags.get("codex"))

    def test_omx_flag_is_parsed(self) -> None:
        route = parse_route(["--plan", "feature-a", "--omx", "--codex"], env={})
        self.assertEqual(route.command, "plan")
        self.assertTrue(route.flags.get("omx"))
        self.assertTrue(route.flags.get("codex"))

    def test_omx_ralph_and_team_flags_are_parsed(self) -> None:
        route = parse_route(["--plan", "feature-a", "--omx", "--ralph", "--team", "--codex"], env={})
        self.assertEqual(route.command, "plan")
        self.assertTrue(route.flags.get("omx"))
        self.assertTrue(route.flags.get("ralph"))
        self.assertTrue(route.flags.get("team"))
        self.assertTrue(route.flags.get("codex"))

    def test_list_trees_alias_routes_to_list_trees_command(self) -> None:
        route = parse_route(["--list-trees"], env={})
        self.assertEqual(route.command, "list-trees")

    def test_init_alias_routes_to_config_command(self) -> None:
        route = parse_route(["--init"], env={})
        self.assertEqual(route.command, "config")

    def test_explain_startup_takes_precedence_over_plan_tokens_regardless_of_order(self) -> None:
        for argv in (
            ["--explain-startup", "--plan", "feature-a", "--json"],
            ["--plan", "--explain-startup", "feature-a", "--json"],
        ):
            route = parse_route(argv, env={})
            self.assertEqual(route.command, "explain-startup")
            self.assertEqual(route.mode, "trees")
            self.assertEqual(route.passthrough_args, ["feature-a"])
            self.assertTrue(bool(route.flags.get("json")))


if __name__ == "__main__":
    unittest.main()
