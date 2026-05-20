from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest


from envctl_engine.runtime.command_router import Route  # noqa: E402
from envctl_engine.runtime.engine_runtime_action_support import (  # noqa: E402
    action_env,
    action_extra_env,
    action_replacements,
    project_name_from_service,
    projects_for_services,
    resolve_action_targets,
    run_action_command,
    run_analyze_action,
    run_commit_action,
    run_delete_worktree_action,
    run_migrate_action,
    run_pr_action,
    run_project_action,
    run_test_action,
    selectors_from_passthrough,
)


class EngineRuntimeActionSupportTests(unittest.TestCase):
    def test_selectors_from_passthrough_ignores_flags_and_splits_csv_tokens(self) -> None:
        self.assertEqual(
            selectors_from_passthrough(["feature-a,Feature-B", "--flag", " main "]),
            {"feature-a", "feature-b", "main"},
        )

    def test_project_name_from_service_extracts_backend_and_frontend_suffixes(self) -> None:
        self.assertEqual(project_name_from_service("Feature A Backend"), "Feature A")
        self.assertEqual(project_name_from_service("Feature A Frontend"), "Feature A")
        self.assertEqual(project_name_from_service("Feature A Worker"), "")

    def test_runtime_action_helpers_delegate_to_action_command_orchestrator(self) -> None:
        calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

        class ActionCommandOrchestrator:
            def execute(self, *args: object, **kwargs: object) -> int:
                calls.append(("execute", args, kwargs))
                return 11

            def resolve_targets(self, *args: object, **kwargs: object) -> tuple[list[object], str | None]:
                calls.append(("resolve_targets", args, kwargs))
                return [SimpleNamespace(name="Main")], None

            def projects_for_services(self, *args: object, **kwargs: object) -> list[str]:
                calls.append(("projects_for_services", args, kwargs))
                return ["Main"]

            def run_test_action(self, *args: object, **kwargs: object) -> int:
                calls.append(("run_test_action", args, kwargs))
                return 12

            def run_pr_action(self, *args: object, **kwargs: object) -> int:
                calls.append(("run_pr_action", args, kwargs))
                return 13

            def run_commit_action(self, *args: object, **kwargs: object) -> int:
                calls.append(("run_commit_action", args, kwargs))
                return 14

            def run_review_action(self, *args: object, **kwargs: object) -> int:
                calls.append(("run_review_action", args, kwargs))
                return 15

            def run_migrate_action(self, *args: object, **kwargs: object) -> int:
                calls.append(("run_migrate_action", args, kwargs))
                return 16

            def run_project_action(self, *args: object, **kwargs: object) -> int:
                calls.append(("run_project_action", args, kwargs))
                return 17

            def run_delete_worktree_action(self, *args: object, **kwargs: object) -> int:
                calls.append(("run_delete_worktree_action", args, kwargs))
                return 18

            def action_replacements(self, *args: object, **kwargs: object) -> dict[str, str]:
                calls.append(("action_replacements", args, kwargs))
                return {"PROJECT": "Main"}

            def action_env(self, *args: object, **kwargs: object) -> dict[str, str]:
                calls.append(("action_env", args, kwargs))
                return {"ENVCTL_ACTION": "test"}

        runtime = SimpleNamespace(action_command_orchestrator=ActionCommandOrchestrator())
        route = Route(command="test", mode="main", raw_args=[], passthrough_args=[], projects=[], flags={})
        targets = [SimpleNamespace(name="Main")]

        self.assertEqual(run_action_command(runtime, route), 11)
        self.assertEqual(resolve_action_targets(runtime, route, trees_only=True)[0][0].name, "Main")
        self.assertEqual(projects_for_services(runtime, targets), ["Main"])
        self.assertEqual(run_test_action(runtime, route, targets), 12)
        self.assertEqual(run_pr_action(runtime, route, targets), 13)
        self.assertEqual(run_commit_action(runtime, route, targets), 14)
        self.assertEqual(run_analyze_action(runtime, route, targets), 15)
        self.assertEqual(run_migrate_action(runtime, route, targets), 16)
        self.assertEqual(
            run_project_action(
                runtime,
                route,
                targets,
                command_name="review",
                env_key="ENVCTL_REVIEW_COMMAND",
                default_command=["pytest"],
                default_cwd=Path("/repo"),
                default_append_project_path=True,
                extra_env={"A": "1"},
            ),
            17,
        )
        self.assertEqual(run_delete_worktree_action(runtime, route), 18)
        self.assertEqual(action_replacements(runtime, targets, target=targets[0]), {"PROJECT": "Main"})
        self.assertEqual(
            action_env(runtime, "test", targets, target=targets[0], extra={"B": "2"}),
            {"ENVCTL_ACTION": "test"},
        )
        self.assertEqual(action_extra_env(route), {})

        call_names = [name for name, _args, _kwargs in calls]
        self.assertEqual(
            call_names,
            [
                "execute",
                "resolve_targets",
                "projects_for_services",
                "run_test_action",
                "run_pr_action",
                "run_commit_action",
                "run_review_action",
                "run_migrate_action",
                "run_project_action",
                "run_delete_worktree_action",
                "action_replacements",
                "action_env",
            ],
        )


if __name__ == "__main__":
    unittest.main()
