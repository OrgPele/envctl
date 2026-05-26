from __future__ import annotations

import unittest

from envctl_engine.runtime.command_models import RouteError
from envctl_engine.runtime.command_special_flags import (
    apply_default_headless_policy,
    apply_default_runtime_scope_policy,
    handle_env_assignment,
    handle_special_flag,
    validate_dependency_scope_flags,
    validate_plan_agent_cli_flags,
    validate_plan_agent_workflow_flags,
)


class CommandSpecialFlagsTests(unittest.TestCase):
    def test_special_runtime_scope_flags_reject_conflicts(self) -> None:
        flags: dict[str, object] = {}

        handle_special_flag(flags, "--backend")

        self.assertEqual(flags["runtime_scope"], "backend")
        with self.assertRaisesRegex(RouteError, "Use only one runtime scope flag"):
            handle_special_flag(flags, "--frontend")

    def test_special_dependency_scope_flags_reject_conflicts(self) -> None:
        flags: dict[str, object] = {}

        handle_special_flag(flags, "--shared-deps")

        self.assertEqual(flags["dependency_scope"], "shared")
        with self.assertRaisesRegex(RouteError, "Use only one dependency scope flag"):
            handle_special_flag(flags, "--isolated-deps")

    def test_env_assignments_parse_known_boolean_and_value_flags(self) -> None:
        flags: dict[str, object] = {}

        handle_env_assignment(flags, "ENVCTL_ACTION_TEST_PARALLEL=false")
        handle_env_assignment(flags, "SERVICE_PREP_PARALLEL=true")
        handle_env_assignment(flags, "FRONTEND_TEST_RUNNER=vitest")
        handle_env_assignment(flags, "PARALLEL_TREES_MAX=4")

        self.assertFalse(flags["test_parallel"])
        self.assertTrue(flags["service_prep_parallel"])
        self.assertEqual(flags["frontend_test_runner"], "vitest")
        self.assertEqual(flags["parallel_trees_max"], "4")

    def test_default_runtime_scope_policy_uses_entire_system_only_when_unscoped(self) -> None:
        flags: dict[str, object] = {}

        apply_default_runtime_scope_policy("start", flags=flags, projects=[])

        self.assertEqual(flags["runtime_scope"], "entire-system")

        scoped: dict[str, object] = {"services": ["backend"]}
        apply_default_runtime_scope_policy("start", flags=scoped, projects=[])
        self.assertNotIn("runtime_scope", scoped)

    def test_dependency_scope_validation_rejects_main_isolated_and_no_deps_shared(self) -> None:
        with self.assertRaisesRegex(RouteError, "Main always uses shared dependencies"):
            validate_dependency_scope_flags("main", flags={"dependency_scope": "isolated"}, sets_up_worktrees=False)

        with self.assertRaisesRegex(RouteError, "--shared-deps requires managed dependencies"):
            validate_dependency_scope_flags(
                "trees",
                flags={"dependency_scope": "shared", "launch_dependencies": False},
                sets_up_worktrees=False,
            )

    def test_default_headless_policy_marks_action_commands(self) -> None:
        flags: dict[str, object] = {}

        apply_default_headless_policy("test", flags)

        self.assertTrue(flags["batch"])
        self.assertTrue(flags["default_headless"])

    def test_plan_agent_cli_and_workflow_validation(self) -> None:
        with self.assertRaisesRegex(RouteError, "Use only one of --codex or --opencode"):
            validate_plan_agent_cli_flags({"codex": True, "opencode": True})

        with self.assertRaisesRegex(RouteError, "--ultragoal, --ralph, and --team are only supported with --omx"):
            validate_plan_agent_workflow_flags({"ultragoal": True})

        validate_plan_agent_cli_flags({"opencode": True, "tmux": True})
        validate_plan_agent_workflow_flags({"ultragoal": True, "omx": True})


if __name__ == "__main__":
    unittest.main()
