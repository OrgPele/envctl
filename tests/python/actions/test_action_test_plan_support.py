from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.actions.action_test_plan_support import build_test_execution_specs_for_route
from envctl_engine.actions.action_test_support import TestTargetContext
from envctl_engine.runtime.command_router import parse_route


class ActionTestPlanSupportTests(unittest.TestCase):
    def test_failed_flag_delegates_to_failed_spec_builder(self) -> None:
        route = parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"})
        expected = [SimpleNamespace(index=1)]

        specs = build_test_execution_specs_for_route(
            route=route,
            targets=[],
            target_contexts=[],
            include_backend=True,
            include_frontend=True,
            run_all=False,
            untested=False,
            env={},
            config=SimpleNamespace(raw={}, base_dir=Path("/repo")),
            action_replacements_builder=lambda _targets, target: {},
            split_command=lambda raw, replacements: raw.split(),
            failed_spec_builder=lambda **_kwargs: expected,
            additional_service_spec_builder=lambda **_kwargs: [],
            is_legacy_tree_test_script=lambda _command: False,
        )

        self.assertIs(specs, expected)

    def test_additional_service_specs_win_before_default_test_detection(self) -> None:
        route = parse_route(["test", "--service", "voice-runtime"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        expected = [SimpleNamespace(index=1)]

        specs = build_test_execution_specs_for_route(
            route=route,
            targets=[],
            target_contexts=[],
            include_backend=True,
            include_frontend=True,
            run_all=False,
            untested=False,
            env={"ENVCTL_ACTION_TEST_CMD": "pytest"},
            config=SimpleNamespace(raw={}, base_dir=Path("/repo")),
            action_replacements_builder=lambda _targets, target: {},
            split_command=lambda raw, replacements: raw.split(),
            failed_spec_builder=lambda **_kwargs: [],
            additional_service_spec_builder=lambda **_kwargs: expected,
            is_legacy_tree_test_script=lambda _command: False,
        )

        self.assertIs(specs, expected)

    def test_configured_commands_and_frontend_path_are_read_from_env_then_config(self) -> None:
        route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        target = SimpleNamespace(name="feature-a-1", root="/repo/trees/feature-a/1")
        context = TestTargetContext(project_name="feature-a-1", project_root=Path(target.root), target_obj=target)

        specs = build_test_execution_specs_for_route(
            route=route,
            targets=[target],
            target_contexts=[context],
            include_backend=False,
            include_frontend=True,
            run_all=True,
            untested=False,
            env={
                "ENVCTL_ACTION_TEST_CMD": "npm test",
                "ENVCTL_BACKEND_TEST_CMD": "pytest",
                "ENVCTL_FRONTEND_TEST_PATH": "src/App.test.tsx",
            },
            config=SimpleNamespace(
                raw={"ENVCTL_FRONTEND_TEST_CMD": "npm run test:unit"},
                base_dir=Path("/repo"),
                frontend_test_path="",
            ),
            action_replacements_builder=lambda _targets, target: {"project": target.name},
            split_command=lambda raw, replacements: raw.split(),
            failed_spec_builder=lambda **_kwargs: [],
            additional_service_spec_builder=lambda **_kwargs: [],
            is_legacy_tree_test_script=lambda _command: False,
        )

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].spec.command[:2], ["npm", "test"])
        self.assertEqual(specs[0].project_name, "feature-a-1")
        self.assertEqual(specs[0].spec.cwd, Path("/repo/trees/feature-a/1"))


if __name__ == "__main__":
    unittest.main()
