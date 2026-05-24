from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime_action_support import (
    action_env,
    action_extra_env,
    action_replacements,
    project_name_from_service,
    projects_for_services,
    resolve_action_targets,
    run_action_command,
    run_delete_worktree_action,
    run_migrate_action,
    run_project_action,
    run_test_action,
    selectors_from_passthrough,
)


class EngineRuntimeActionSupportTests(unittest.TestCase):
    def test_selectors_from_passthrough_ignores_flags_and_splits_csv_tokens(self) -> None:
        selectors = selectors_from_passthrough(["feature-a, feature-b", "--project", "Main", "-q", ""])

        self.assertEqual(selectors, {"feature-a", "feature-b", "main"})

    def test_project_name_from_service_strips_known_suffixes_only(self) -> None:
        self.assertEqual(project_name_from_service("Main Backend"), "Main")
        self.assertEqual(project_name_from_service("Feature Frontend"), "Feature")
        self.assertEqual(project_name_from_service("Main Worker"), "")

    def test_action_entrypoints_delegate_to_action_command_orchestrator(self) -> None:
        route = parse_route(["test"], env={})
        target = SimpleNamespace(name="Main")
        calls: list[tuple[str, object]] = []
        orchestrator = SimpleNamespace(
            execute=lambda value: calls.append(("execute", value)) or 3,
            resolve_targets=lambda value, *, trees_only: calls.append(("resolve", (value, trees_only))) or ([target], None),
            projects_for_services=lambda values: calls.append(("projects", values)) or ["Main"],
            run_test_action=lambda value, values: calls.append(("test", (value, values))) or 4,
            run_migrate_action=lambda value, values: calls.append(("migrate", (value, values))) or 5,
            run_delete_worktree_action=lambda value: calls.append(("delete", value)) or 6,
            action_replacements=lambda values, *, target: calls.append(("replacements", (values, target))) or {"project": "Main"},
            action_env=lambda name, values, *, target, extra=None: calls.append(("env", (name, values, target, extra)))
            or {"ENVCTL_ACTION": name},
        )
        runtime = SimpleNamespace(action_command_orchestrator=orchestrator)

        self.assertEqual(run_action_command(runtime, route), 3)
        self.assertEqual(resolve_action_targets(runtime, route, trees_only=True), ([target], None))
        self.assertEqual(projects_for_services(runtime, [target]), ["Main"])
        self.assertEqual(run_test_action(runtime, route, [target]), 4)
        self.assertEqual(run_migrate_action(runtime, route, [target]), 5)
        self.assertEqual(run_delete_worktree_action(runtime, route), 6)
        self.assertEqual(action_replacements(runtime, [target], target=target), {"project": "Main"})
        self.assertEqual(action_env(runtime, "test", [target], target=target, extra={"A": "1"}), {"ENVCTL_ACTION": "test"})

    def test_run_project_action_delegates_with_full_command_contract(self) -> None:
        route = parse_route(["pr"], env={})
        target = SimpleNamespace(name="Main")
        seen: dict[str, object] = {}

        def run_project(value, targets, **kwargs):  # noqa: ANN001, ANN202
            seen["route"] = value
            seen["targets"] = targets
            seen.update(kwargs)
            return 9

        runtime = SimpleNamespace(action_command_orchestrator=SimpleNamespace(run_project_action=run_project))

        code = run_project_action(
            runtime,
            route,
            [target],
            command_name="pr",
            env_key="ENVCTL_ACTION_PR_CMD",
            default_command=["gh", "pr", "view"],
            default_cwd=Path("/repo"),
            default_append_project_path=False,
            extra_env={"CI": "1"},
        )

        self.assertEqual(code, 9)
        self.assertIs(seen["route"], route)
        self.assertEqual(seen["targets"], [target])
        self.assertEqual(seen["command_name"], "pr")
        self.assertEqual(seen["env_key"], "ENVCTL_ACTION_PR_CMD")
        self.assertEqual(seen["default_command"], ["gh", "pr", "view"])
        self.assertEqual(seen["default_cwd"], Path("/repo"))
        self.assertEqual(seen["default_append_project_path"], False)
        self.assertEqual(seen["extra_env"], {"CI": "1"})

    def test_action_extra_env_uses_action_orchestrator_static_contract(self) -> None:
        route = parse_route(["pr", "--pr-base", "main"], env={})

        env = action_extra_env(route)

        self.assertEqual(env["ENVCTL_PR_BASE"], "main")


if __name__ == "__main__":
    unittest.main()
