from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from envctl_engine.actions.action_test_plan_support import TestExecutionPlanner
from envctl_engine.actions.action_test_plan_support import build_test_execution_specs_for_route
from envctl_engine.actions.action_test_plan_support import command_start_status
from envctl_engine.actions.action_test_plan_support import parallel_test_worker_count, parallel_tests_enabled
from envctl_engine.actions.action_test_plan_support import render_test_execution_status
from envctl_engine.actions.action_test_plan_support import render_test_scope_status
from envctl_engine.actions.action_test_plan_support import run_test_plan_action_for_targets
from envctl_engine.actions.action_test_plan_support import suite_spinner_policy_enabled
from envctl_engine.actions.action_test_plan_support import is_legacy_tree_test_script, select_test_services
from envctl_engine.actions.action_test_support import TestExecutionSpec as ExecutionSpec
from envctl_engine.actions.action_test_support import TestTargetContext as TargetContext
from envctl_engine.actions.actions_test import TestCommandSpec as CommandSpec
from envctl_engine.runtime.command_router import parse_route


class ActionTestPlanSupportTests(unittest.TestCase):
    def test_status_rendering_matches_action_command_surface(self) -> None:
        targets = [SimpleNamespace(name="api"), SimpleNamespace(name="web")]

        self.assertEqual(command_start_status("test", targets), "Running test for 2 targets...")
        self.assertEqual(
            render_test_scope_status(["api"], run_all=False, untested=False, failed=True),
            "Rerunning failed tests for api...",
        )
        self.assertEqual(
            render_test_execution_status(["python", "-m", "pytest"], args=[], source="default", cwd=Path("/repo")),
            "Running pytest suite at tests...",
        )
        self.assertEqual(
            render_test_execution_status(
                ["bash", "/repo/scripts/test-all-trees.sh"],
                args=["projects=api,web"],
                source="default",
                cwd=Path("/repo"),
            ),
            "Running tree test matrix for 2 selected project(s)...",
        )

    def test_run_test_plan_action_for_targets_builds_contexts_and_stops_on_failure(self) -> None:
        orchestrator = SimpleNamespace(runtime=SimpleNamespace(config=SimpleNamespace(base_dir=Path("/repo"))))
        route = parse_route(["test-focused", "--json"], env={})
        targets = [
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

    def test_test_parallel_policy_uses_flags_env_config_and_legacy_tree_safety(self) -> None:
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
        forced_off = parse_route(["test", "--no-test-parallel"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        self.assertFalse(parallel_tests_enabled(forced_off, specs=specs, env={}, config_raw={}))
        self.assertFalse(parallel_tests_enabled(route, specs=specs[:1], env={}, config_raw={}))
        self.assertFalse(parallel_tests_enabled(route, specs=specs, env={"ENVCTL_ACTION_TEST_PARALLEL": "false"}, config_raw={}))
        self.assertEqual(
            parallel_test_worker_count(route, specs=specs, env={"ENVCTL_ACTION_TEST_PARALLEL_MAX": "9"}, config_raw={}),
            2,
        )

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
        self.assertFalse(parallel_tests_enabled(route, specs=legacy_specs, env={}, config_raw={}))

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

    def test_test_execution_planner_reuses_route_dependencies_without_argument_sprawl(self) -> None:
        route = parse_route(["test", "--project", "feature-a-1"], env={"ENVCTL_DEFAULT_MODE": "trees"})
        target = SimpleNamespace(name="feature-a-1", root="/repo/trees/feature-a/1")
        context = TargetContext(project_name="feature-a-1", project_root=Path(target.root), target_obj=target)
        planner = TestExecutionPlanner(
            route=route,
            targets=[target],
            target_contexts=[context],
            include_backend=True,
            include_frontend=False,
            run_all=False,
            untested=True,
            env={"ENVCTL_BACKEND_TEST_CMD": "pytest {project}"},
            config=SimpleNamespace(raw={}, base_dir=Path("/repo"), frontend_test_path=""),
            action_replacements_builder=lambda _targets, target: {"project": target.name},
            split_command=lambda raw, replacements: [
                token.replace("{project}", replacements["project"]) for token in raw.split()
            ],
            failed_spec_builder=lambda **_kwargs: [],
            additional_service_spec_builder=lambda **_kwargs: [],
            is_legacy_tree_test_script=lambda _command: False,
        )

        specs = planner.build()

        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].spec.command, ["pytest", "feature-a-1"])
        self.assertEqual(specs[0].project_name, "feature-a-1")


if __name__ == "__main__":
    unittest.main()
