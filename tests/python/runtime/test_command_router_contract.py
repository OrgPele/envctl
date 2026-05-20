from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime import command_router
from envctl_engine.runtime.command_router import RouteError, parse_route


class CommandRouterContractTests(unittest.TestCase):
    def test_command_alias_matrix(self) -> None:
        matrix = {
            "--plan": "plan",
            "plan": "plan",
            "--resume": "resume",
            "resume": "resume",
            "--doctor": "doctor",
            "d": "doctor",
            "--dashboard": "dashboard",
            "dash": "dashboard",
            "--stop-all": "stop-all",
            "stopall": "stop-all",
            "--blast-all": "blast-all",
            "blastall": "blast-all",
            "--blast-worktree": "blast-worktree",
            "blastworktree": "blast-worktree",
            "self-destruct-worktree": "self-destruct-worktree",
            "--self-destruct-worktree": "self-destruct-worktree",
            "--logs": "logs",
            "l": "logs",
            "--clear-logs": "clear-logs",
            "t": "test",
            "p": "pr",
            "c": "commit",
            "a": "review",
            "v": "review",
            "analyze": "review",
            "review": "review",
            "m": "migrate",
            "migration": "migrate",
            "migrations": "migrate",
            "debug-pack": "debug-pack",
            "--debug-ui-pack": "debug-pack",
            "--debug-report": "debug-report",
            "debug-report": "debug-report",
            "--debug-last": "debug-last",
            "debug-last": "debug-last",
        }
        for token, expected in matrix.items():
            route = parse_route([token], env={})
            self.assertEqual(route.command, expected, msg=token)

    def test_mode_toggle_matrix(self) -> None:
        trees = parse_route(["--trees"], env={})
        self.assertEqual(trees.mode, "trees")
        main = parse_route(["--main"], env={})
        self.assertEqual(main.mode, "main")

    def test_env_assignment_matrix(self) -> None:
        route = parse_route(["FRONTEND_TEST_RUNNER=vitest"], env={})
        self.assertEqual(route.flags.get("frontend_test_runner"), "vitest")
        route = parse_route(["ENVCTL_ACTION_TEST_PARALLEL_MAX=3"], env={})
        self.assertEqual(route.flags.get("test_parallel_max"), "3")

    def test_duplicate_registry_sources_remain_deduped(self) -> None:
        boolean_source = getattr(command_router, "_BOOLEAN_FLAG_TOKENS")
        alias_source = getattr(command_router, "_COMMAND_ALIAS_PAIRS")
        self.assertEqual(len(boolean_source), len(set(boolean_source)))
        alias_keys = [key for key, _value in alias_source]
        self.assertEqual(len(alias_keys), len(set(alias_keys)))

    def test_unknown_flag_raises_actionable_error(self) -> None:
        with self.assertRaises(RouteError):
            parse_route(["--not-a-real-flag"], env={})

    def test_debug_capture_and_auto_pack_flags_are_parsed(self) -> None:
        route = parse_route(
            [
                "--debug-pack",
                "--debug-capture",
                "deep",
                "--debug-auto-pack",
                "anomaly",
            ],
            env={},
        )
        self.assertEqual(route.flags.get("debug_capture"), "deep")
        self.assertEqual(route.flags.get("debug_auto_pack"), "anomaly")


if __name__ == "__main__":
    unittest.main()
