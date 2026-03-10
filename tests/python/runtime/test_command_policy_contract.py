from __future__ import annotations

import importlib
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
_command_policy = importlib.import_module("envctl_engine.runtime.command_policy")
apply_command_policy = _command_policy.apply_command_policy
apply_mode_token = _command_policy.apply_mode_token
dispatch_family_for_command = _command_policy.dispatch_family_for_command


class CommandPolicyContractTests(unittest.TestCase):
    def test_action_commands_imply_skip_startup_and_load_state(self) -> None:
        for command in (
            "stop",
            "stop-all",
            "blast-all",
            "restart",
            "test",
            "logs",
            "clear-logs",
            "health",
            "errors",
            "blast-worktree",
            "pr",
            "commit",
            "review",
            "migrate",
        ):
            flags: dict[str, object] = {}
            forced_mode = apply_command_policy(flags, command=command)

            self.assertIsNone(forced_mode, msg=command)
            self.assertTrue(flags.get("skip_startup"), msg=command)
            self.assertTrue(flags.get("load_state"), msg=command)

    def test_debug_commands_skip_startup_without_loading_state(self) -> None:
        for command in ("debug-pack", "debug-report", "debug-last"):
            flags: dict[str, object] = {}
            forced_mode = apply_command_policy(flags, command=command)

            self.assertIsNone(forced_mode, msg=command)
            self.assertTrue(flags.get("skip_startup"), msg=command)
            self.assertNotIn("load_state", flags, msg=command)

    def test_plan_aliases_apply_token_specific_policy(self) -> None:
        flags: dict[str, object] = {}
        forced_mode = apply_command_policy(flags, command="plan", token="--sequential-plan")
        self.assertEqual(forced_mode, "trees")
        self.assertTrue(flags.get("sequential"))
        self.assertEqual(flags.get("parallel_trees"), False)

        flags = {}
        forced_mode = apply_command_policy(flags, command="plan", token="--parallel-plan")
        self.assertEqual(forced_mode, "trees")
        self.assertEqual(flags.get("parallel_trees"), True)

        flags = {}
        forced_mode = apply_command_policy(flags, command="plan", token="--planning-prs")
        self.assertEqual(forced_mode, "trees")
        self.assertTrue(flags.get("planning_prs"))

    def test_mode_tokens_apply_no_resume_for_forced_main_modes(self) -> None:
        flags: dict[str, object] = {}
        self.assertEqual(apply_mode_token("--main", flags=flags, current_mode="trees"), "main")
        self.assertTrue(flags.get("no_resume"))

        flags = {}
        self.assertEqual(apply_mode_token("--trees=false", flags=flags, current_mode="trees"), "main")
        self.assertTrue(flags.get("no_resume"))

        flags = {}
        _ = apply_mode_token("main=false", flags=flags, current_mode="main")
        self.assertEqual(_, "trees")
        self.assertNotIn("no_resume", flags)

    def test_dispatch_family_mapping_groups_commands_consistently(self) -> None:
        expected = {
            "list-commands": "direct_inspection",
            "install-prompts": "utility",
            "debug-pack": "debug",
            "stop": "lifecycle_cleanup",
            "resume": "resume",
            "doctor": "doctor",
            "dashboard": "dashboard",
            "config": "config",
            "migrate-hooks": "migrate_hooks",
            "health": "state_action",
            "test": "action",
            "plan": "startup",
            "start": "startup",
        }
        for command, family in expected.items():
            self.assertEqual(dispatch_family_for_command(command), family, msg=command)
        self.assertIsNone(dispatch_family_for_command("definitely-unknown"))


if __name__ == "__main__":
    unittest.main()
