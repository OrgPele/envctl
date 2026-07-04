from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from envctl_engine.actions import action_test_plan_support
from envctl_engine.actions import action_test_policy_support
from envctl_engine.actions import action_test_status_support
from envctl_engine.actions import action_test_command_support
from envctl_engine.actions.action_test_plan_support import OrchestratorTestPlanDependencies
from envctl_engine.actions.action_test_plan_support import RuntimeSplitCommandAdapter
from envctl_engine.actions.action_test_plan_support import TestExecutionPolicy
from envctl_engine.actions.action_test_plan_support import TestExecutionPlanner
from envctl_engine.actions.action_test_plan_support import TestStatusRenderer
from envctl_engine.actions.action_test_plan_support import build_test_execution_specs_for_route
from envctl_engine.actions.action_test_plan_support import run_test_plan_action_for_targets
from envctl_engine.actions.action_test_plan_support import is_legacy_tree_test_script, select_test_services
from envctl_engine.actions.action_test_support import TestExecutionSpec as ExecutionSpec
from envctl_engine.actions.action_test_support import TestTargetContext as TargetContext
from envctl_engine.actions.actions_test import TestCommandSpec as CommandSpec
from envctl_engine.runtime.command_router import parse_route


class ActionTestPlanSupportTests(unittest.TestCase):
    def test_orchestrator_test_plan_wiring_uses_named_dependency_adapters(self) -> None:
        source = Path(action_test_plan_support.__file__).read_text(encoding="utf-8")
        status_source = Path(action_test_status_support.__file__).read_text(encoding="utf-8")
        policy_source = Path(action_test_policy_support.__file__).read_text(encoding="utf-8")
        command_source = Path(action_test_command_support.__file__).read_text(encoding="utf-8")

        self.assertIn("class OrchestratorTestPlanDependencies", source)
        self.assertEqual(
            {name for name in TestExecutionPlanner.__dataclass_fields__ if name != "__test__"},
            {"request", "configuration", "dependencies"},
        )
        self.assertTrue(hasattr(action_test_plan_support, "TestExecutionPlanRequest"))
        self.assertTrue(hasattr(action_test_plan_support, "TestExecutionPlanConfiguration"))
        self.assertTrue(hasattr(action_test_plan_support, "TestExecutionPlanDependencies"))
        self.assertIn("class RuntimeSplitCommandAdapter", source)
        self.assertIn("from envctl_engine.actions.action_test_status_support import", source)
        self.assertIn("from envctl_engine.actions.action_test_policy_support import", source)
        self.assertIn("from envctl_engine.actions.action_test_command_support import", source)
        self.assertNotIn("class TestStatusRenderer", source)
        self.assertNotIn("class TestExecutionPolicy", source)
        self.assertIn("class TestStatusRenderer", status_source)
        self.assertIn("class TestExecutionPolicy", policy_source)
        self.assertIn("def is_legacy_tree_test_script", command_source)
        self.assertNotIn("split_command=lambda", source)
        self.assertTrue(callable(OrchestratorTestPlanDependencies.failed_specs))
        self.assertTrue(callable(RuntimeSplitCommandAdapter.__call__))
        self.assertTrue(callable(TestStatusRenderer.execution_status))
        self.assertTrue(callable(TestExecutionPolicy.parallel_enabled))

    def test_run_test_plan_action_for_targets_builds_contexts_and_stops_on_failure(self) -> None:
        orchestrator = SimpleNamespace(runtime=SimpleNamespace(config=SimpleNamespace(base_dir=Path("/repo"))))
        route = parse_route(["test-focused", "--json"], env={})
        targets: list[object] = [
            SimpleNamespace(name="api", root=Path("/repo/trees/api/1")),
            SimpleNamespace(name="web", root=Path("/repo/trees/web/1")),
        ]
        calls: list[tuple[str, Path, bool, bool]] = []

        def fake_run(context, *, json_output: bool = False, dry_run: bool = False):  # noqa: ANN001, ANN202
            calls.append((str(context.project_name), Path(context.project_root), json_output, dry_run))
            return 3 if context.project_name == "api" else 0

        with patch("envctl_engine.actions.action_test_plan_support.run_test_plan_action", side_effect=fake_run):
            code = run_test_plan_action_for_targets(orchestrator, route, targets)

        self.assertEqual(code, 3)
        self.assertEqual(calls, [("api", Path("/repo/trees/api/1"), True, False)])

    def test_test_focused_ship_on_pass_rejects_blank_message_before_execution(self) -> None:
        orchestrator = SimpleNamespace(runtime=SimpleNamespace(config=SimpleNamespace(base_dir=Path("/repo"))))
        route = parse_route(["test-focused", "--ship-on-pass="], env={})
        targets = [SimpleNamespace(name="api", root=Path("/repo/trees/api/1"))]

        with (
            patch(
                "envctl_engine.actions.action_test_plan_support.run_test_plan_action",
                side_effect=AssertionError("tests should not run"),
            ),
            patch("envctl_engine.actions.action_test_ship_on_pass_support.run_ship_action") as ship,
        ):
            code = run_test_plan_action_for_targets(orchestrator, route, targets)

        self.assertEqual(code, 1)
        ship.assert_not_called()

    def test_test_focused_ship_on_pass_rejects_dry_run_before_execution(self) -> None:
        orchestrator = SimpleNamespace(runtime=SimpleNamespace(config=SimpleNamespace(base_dir=Path("/repo"))))
        route = parse_route(["test-focused", "--dry-run", "--ship-on-pass", "Ship focused fix"], env={})
        targets = [SimpleNamespace(name="api", root=Path("/repo/trees/api/1"))]

        with (
            patch(
                "envctl_engine.actions.action_test_plan_support.run_test_plan_action",
                side_effect=AssertionError("tests should not run"),
            ),
            patch("envctl_engine.actions.action_test_ship_on_pass_support.run_ship_action") as ship,
        ):
            code = run_test_plan_action_for_targets(orchestrator, route, targets)

        self.assertEqual(code, 1)
        ship.assert_not_called()

    def test_test_focused_ship_on_pass_rejects_json_before_execution(self) -> None:
        orchestrator = SimpleNamespace(runtime=SimpleNamespace(config=SimpleNamespace(base_dir=Path("/repo"))))
        route = parse_route(["test-focused", "--json", "--ship-on-pass", "Ship focused fix"], env={})
        targets = [SimpleNamespace(name="api", root=Path("/repo/trees/api/1"))]

        with (
            patch(
                "envctl_engine.actions.action_test_plan_support.run_test_plan_action",
                side_effect=AssertionError("tests should not run"),
            ),
            patch("envctl_engine.actions.action_test_ship_on_pass_support.run_ship_action") as ship,
        ):
            code = run_test_plan_action_for_targets(orchestrator, route, targets)

        self.assertEqual(code, 1)
        ship.assert_not_called()

    def test_test_focused_ship_on_pass_skips_ship_on_test_failure(self) -> None:
        orchestrator = SimpleNamespace(runtime=SimpleNamespace(config=SimpleNamespace(base_dir=Path("/repo"))))
        route = parse_route(["test-focused", "--ship-on-pass", "Ship focused fix"], env={})
        targets = [SimpleNamespace(name="api", root=Path("/repo/trees/api/1"))]

        with (
            patch("envctl_engine.actions.action_test_plan_support.run_test_plan_action", return_value=3),
            patch("envctl_engine.actions.action_test_ship_on_pass_support.run_ship_action") as ship,
        ):
            code = run_test_plan_action_for_targets(orchestrator, route, targets)

        self.assertEqual(code, 3)
        ship.assert_not_called()

    def test_test_focused_ship_on_pass_ships_after_success_and_propagates_failure(self) -> None:
        runtime = SimpleNamespace(config=SimpleNamespace(base_dir=Path("/repo")), env={"BASE": "1"})
        orchestrator = SimpleNamespace(runtime=runtime)
        route = parse_route(["test-focused", "--ship-on-pass", "Ship focused fix"], env={})
        targets = [SimpleNamespace(name="api", root=Path("/repo/trees/api/1"))]
        contexts = []

        def fake_ship(context):  # noqa: ANN001, ANN202
            contexts.append(context)
            return 7

        with (
            patch("envctl_engine.actions.action_test_plan_support.run_test_plan_action", return_value=0),
            patch("envctl_engine.actions.action_test_ship_on_pass_support.run_ship_action", side_effect=fake_ship),
        ):
            code = run_test_plan_action_for_targets(orchestrator, route, targets)

        self.assertEqual(code, 7)
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0].project_name, "api")
        self.assertEqual(contexts[0].env["ENVCTL_COMMIT_MESSAGE"], "Ship focused fix")

    def test_test_service_selection_uses_flags_and_additional_service_names(self) -> None:
        backend_route = parse_route(["test", "--service", "backend"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        frontend_route = parse_route(["test", "--service", "frontend"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        service_route = parse_route(["test", "--service", "voice-runtime"], env={"ENVCTL_DEFAULT_MODE": "trees"})

        self.assertEqual(select_test_services(backend_route, backend_flag=None, frontend_flag=None), (True, False))
        self.assertEqual(select_test_services(frontend_route, backend_flag=None, frontend_flag=None), (False, True))
        self.assertEqual(select_test_services(service_route, backend_flag=None, frontend_flag=None), (True, True))

    def test_legacy_tree_test_script_detection_matches_old_shell_wrapper(self) -> None:
        self.assertTrue(is_legacy_tree_test_script(["bash", "/repo/scripts/test-all-trees.sh"]))
        self.assertFalse(is_legacy_tree_test_script(["bash", "/repo/scripts/test-one-tree.sh"]))

    def test_failed_flag_delegates_to_failed_spec_builder(self) -> None:
        route = parse_route(["test", "--failed"], env={"ENVCTL_DEFAULT_MODE": "main"})
        expected = [
            ExecutionSpec(
                index=1,
                spec=CommandSpec(source="failed", command=["python", "-m", "pytest"], cwd=Path("/repo")),
                args=[],
                resolved_source="failed",
                project_name="Main",
                project_root=Path("/repo"),
            )
        ]

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
        expected = [
            ExecutionSpec(
                index=1,
                spec=CommandSpec(source="service", command=["python", "-m", "pytest"], cwd=Path("/repo")),
                args=[],
                resolved_source="service",
                project_name="voice-runtime",
                project_root=Path("/repo"),
            )
        ]

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
        context = TargetContext(project_name="feature-a-1", project_root=Path(target.root), target_obj=target)

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
        self.assertEqual(specs[0].spec.command[-1], "src/App.test.tsx")

    def test_frontend_test_path_env_overrides_configured_defaults(self) -> None:
        route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        target = SimpleNamespace(name="feature-a-1", root="/repo/trees/feature-a/1")
        context = TargetContext(project_name="feature-a-1", project_root=Path(target.root), target_obj=target)

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
                "ENVCTL_FRONTEND_TEST_PATH": "src/env.test.tsx",
            },
            config=SimpleNamespace(
                raw={"ENVCTL_FRONTEND_TEST_PATH": "src/raw.test.tsx"},
                base_dir=Path("/repo"),
                frontend_test_path="src/config.test.tsx",
            ),
            action_replacements_builder=lambda _targets, target: {"project": target.name},
            split_command=lambda raw, replacements: raw.split(),
            failed_spec_builder=lambda **_kwargs: [],
            additional_service_spec_builder=lambda **_kwargs: [],
            is_legacy_tree_test_script=lambda _command: False,
        )

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].spec.command, ["npm", "test", "--", "src/env.test.tsx"])

    def test_test_execution_planner_reuses_route_dependencies_without_argument_sprawl(self) -> None:
        route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        target = SimpleNamespace(name="feature-a-1", root="/repo/trees/feature-a/1")
        context = TargetContext(project_name="feature-a-1", project_root=Path(target.root), target_obj=target)
        planner = TestExecutionPlanner(
            request=action_test_plan_support.TestExecutionPlanRequest(
                route=route,
                targets=[target],
                target_contexts=[context],
                include_backend=True,
                include_frontend=False,
                run_all=False,
                untested=True,
            ),
            configuration=action_test_plan_support.TestExecutionPlanConfiguration(
                env={"ENVCTL_BACKEND_TEST_CMD": "pytest {project}"},
                config=SimpleNamespace(raw={}, base_dir=Path("/repo"), frontend_test_path=""),
            ),
            dependencies=action_test_plan_support.TestExecutionPlanDependencies(
                action_replacements_builder=lambda _targets, target: {"project": target.name},
                split_command=lambda raw, replacements: [
                    token.replace("{project}", replacements["project"]) for token in raw.split()
                ],
                failed_spec_builder=lambda **_kwargs: [],
                additional_service_spec_builder=lambda **_kwargs: [],
                is_legacy_tree_test_script=lambda _command: False,
            ),
        )

        specs = planner.build()

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].spec.command, ["pytest", "feature-a-1"])
        self.assertEqual(specs[0].project_name, "feature-a-1")


if __name__ == "__main__":
    unittest.main()
