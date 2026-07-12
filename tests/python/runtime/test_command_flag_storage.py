from __future__ import annotations

import unittest

from envctl_engine.runtime.command_flag_storage import (
    boolean_flag_name,
    parse_projects,
    store_inline_pair_flag,
    store_pair_flag,
    store_value_flag,
)
from envctl_engine.runtime.command_models import RouteError


class CommandFlagStorageTests(unittest.TestCase):
    def test_parse_projects_splits_comma_separated_targets(self) -> None:
        self.assertEqual(parse_projects("main, feature-a, ,feature-b"), ["main", "feature-a", "feature-b"])

    def test_boolean_flag_name_maps_known_runtime_flags(self) -> None:
        self.assertEqual(boolean_flag_name("--headless"), "batch")
        self.assertEqual(boolean_flag_name("--cmux"), "cmux")
        self.assertEqual(boolean_flag_name("--ignore-service-deps"), "ignore_service_deps")

    def test_store_value_flag_extends_repeatable_values(self) -> None:
        flags: dict[str, object] = {"services": ["backend"]}

        store_value_flag(flags, "--service", "frontend,worker")
        store_value_flag(flags, "--set", "KEY=value")
        store_value_flag(flags, "--set", "OTHER=value")

        self.assertEqual(flags["services"], ["backend", "frontend", "worker"])
        self.assertEqual(flags["set_values"], ["KEY=value", "OTHER=value"])

    def test_store_value_flag_validates_mode_override(self) -> None:
        with self.assertRaisesRegex(RouteError, "--mode must be main or trees"):
            store_value_flag({}, "--mode", "invalid")

    def test_store_pair_flags_accumulate_setup_entries(self) -> None:
        flags: dict[str, object] = {}

        store_pair_flag(flags, "--setup-worktree", "feature-a", "2")
        store_inline_pair_flag(flags, "--setup-worktrees", "feature-b,3")

        self.assertEqual(flags["setup_worktree"], [{"feature": "feature-a", "iteration": "2"}])
        self.assertEqual(flags["setup_worktrees"], [{"feature": "feature-b", "count": "3"}])

    def test_store_inline_pair_flag_rejects_missing_values(self) -> None:
        with self.assertRaisesRegex(RouteError, "Missing value for --setup-worktree"):
            store_inline_pair_flag({}, "--setup-worktree", "feature-only")


if __name__ == "__main__":
    unittest.main()
