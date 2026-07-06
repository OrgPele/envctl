from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from envctl_engine.actions.action_test_policy_support import (
    parallel_test_worker_count,
    parallel_tests_enabled,
    suite_spinner_policy_enabled,
)
from envctl_engine.actions.action_test_support import TestExecutionSpec as ExecutionSpec
from envctl_engine.actions.actions_test import TestCommandSpec as CommandSpec
from envctl_engine.runtime.command_router import parse_route


class ActionTestPolicySupportTests(unittest.TestCase):
    def test_parallel_policy_uses_flags_env_config_and_legacy_tree_safety(self) -> None:
        route = parse_route(["test"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        specs = [
            ExecutionSpec(
                index=1,
                spec=CommandSpec(source="backend_pytest", command=["python", "-m", "pytest"], cwd=Path("/repo")),
                args=[],
                resolved_source="default",
                project_name="Main",
                project_root=Path("/repo"),
            ),
            ExecutionSpec(
                index=2,
                spec=CommandSpec(source="frontend_package", command=["npm", "run", "test"], cwd=Path("/repo")),
                args=[],
                resolved_source="default",
                project_name="Main",
                project_root=Path("/repo"),
            ),
        ]

        self.assertTrue(parallel_tests_enabled(route, specs=specs, env={}, config_raw={}))
        forced_on = parse_route(["test", "--parallel"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        self.assertTrue(parallel_tests_enabled(forced_on, specs=specs, env={}, config_raw={}))
        forced_off = parse_route(["test", "--sequential"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        self.assertFalse(parallel_tests_enabled(forced_off, specs=specs, env={}, config_raw={}))
        self.assertFalse(parallel_tests_enabled(route, specs=specs[:1], env={}, config_raw={}))
        self.assertTrue(parallel_tests_enabled(route, specs=specs, env={"ENVCTL_ACTION_TEST_PARALLEL": "true"}, config_raw={}))
        self.assertFalse(
            parallel_tests_enabled(route, specs=specs, env={"ENVCTL_ACTION_TEST_PARALLEL": "false"}, config_raw={})
        )
        self.assertFalse(parallel_tests_enabled(forced_off, specs=specs, env={"ENVCTL_ACTION_TEST_PARALLEL": "true"}, config_raw={}))
        self.assertTrue(parallel_tests_enabled(forced_on, specs=specs, env={"ENVCTL_ACTION_TEST_PARALLEL": "false"}, config_raw={}))
        self.assertEqual(
            parallel_test_worker_count(route, specs=specs, env={"ENVCTL_ACTION_TEST_PARALLEL_MAX": "9"}, config_raw={}),
            2,
        )
        self.assertFalse(parallel_tests_enabled(forced_on, specs=specs[:1], env={}, config_raw={}))
        specs.append(
            ExecutionSpec(
                index=3,
                spec=CommandSpec(source="other", command=["npm", "run", "test"], cwd=Path("/repo")),
                args=[],
                resolved_source="default",
                project_name="Main",
                project_root=Path("/repo"),
            )
        )
        with patch("envctl_engine.actions.action_test_policy_support.os.cpu_count", return_value=8):
            self.assertEqual(parallel_test_worker_count(route, specs=specs, env={}, config_raw={}), 3)
        with patch("envctl_engine.actions.action_test_policy_support.os.cpu_count", return_value=2):
            self.assertEqual(parallel_test_worker_count(route, specs=specs, env={}, config_raw={}), 1)

        legacy_specs = [
            ExecutionSpec(
                index=1,
                spec=CommandSpec(
                    source="configured",
                    command=["bash", "/repo/scripts/test-all-trees.sh"],
                    cwd=Path("/repo"),
                ),
                args=[],
                resolved_source="configured",
                project_name="Main",
                project_root=Path("/repo"),
            ),
            specs[1],
        ]
        self.assertFalse(parallel_tests_enabled(forced_on, specs=legacy_specs, env={}, config_raw={}))

    def test_parallel_worker_count_honors_explicit_caps_three_through_six(self) -> None:
        specs = [
            ExecutionSpec(
                index=index,
                spec=CommandSpec(source=f"suite_{index}", command=["npm", "run", "test"], cwd=Path("/repo")),
                args=[],
                resolved_source="default",
                project_name="Main",
                project_root=Path("/repo"),
            )
            for index in range(1, 7)
        ]

        for cap in (3, 4, 5, 6):
            with self.subTest(cap=cap):
                route = parse_route(
                    ["test", "--parallel", "--test-parallel-max", str(cap)],
                    env={"ENVCTL_DEFAULT_MODE": "trees"},
                )
                self.assertEqual(parallel_test_worker_count(route, specs=specs, env={}, config_raw={}), cap)

    def test_default_parallel_worker_count_is_cpu_aware_and_capped(self) -> None:
        specs = [
            ExecutionSpec(
                index=index,
                spec=CommandSpec(source=f"suite_{index}", command=["npm", "run", "test"], cwd=Path("/repo")),
                args=[],
                resolved_source="default",
                project_name="Main",
                project_root=Path("/repo"),
            )
            for index in range(1, 7)
        ]
        route = parse_route(["test"], env={"ENVCTL_DEFAULT_MODE": "trees"})

        for cpu_count, expected in ((1, 1), (2, 1), (3, 2), (4, 2), (6, 3), (8, 4), (16, 4)):
            with self.subTest(cpu_count=cpu_count):
                with patch("envctl_engine.actions.action_test_policy_support.os.cpu_count", return_value=cpu_count):
                    self.assertEqual(parallel_test_worker_count(route, specs=specs, env={}, config_raw={}), expected)

    def test_spinner_policy_respects_env_and_spinner_reasons(self) -> None:
        self.assertEqual(suite_spinner_policy_enabled(SimpleNamespace(reason="enabled"), env={}), (True, "enabled"))
        self.assertEqual(
            suite_spinner_policy_enabled(SimpleNamespace(reason="spinner_backend_missing"), env={}),
            (False, "spinner_backend_missing"),
        )
        self.assertEqual(
            suite_spinner_policy_enabled(SimpleNamespace(reason="non_tty"), env={}),
            (True, "enabled"),
        )
        self.assertEqual(
            suite_spinner_policy_enabled(SimpleNamespace(reason="enabled"), env={"ENVCTL_UI_SPINNER_MODE": "off"}),
            (False, "spinner_mode_off"),
        )


if __name__ == "__main__":
    unittest.main()
