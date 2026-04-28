from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime_env import requirement_enabled_for_mode
from envctl_engine.startup.startup_orchestrator import StartupOrchestrator


class StartupOrchestratorProfileTests(unittest.TestCase):
    def test_restart_service_types_respect_default_service_set(self) -> None:
        route = parse_route(["restart", "--service", "Main Frontend"], env={"ENVCTL_DEFAULT_MODE": "main"})
        route.flags["_restart_request"] = True

        selected = StartupOrchestrator._restart_service_types_for_project(
            route=route,
            project_name="Main",
            default_service_types={"backend"},
        )

        self.assertEqual(selected, set())

    def test_runtime_scope_flags_select_startup_service_types(self) -> None:
        backend_route = parse_route(["--backend"], env={})
        self.assertEqual(
            StartupOrchestrator._restart_service_types_for_project(
                route=backend_route,
                project_name="Main",
                default_service_types={"backend", "frontend"},
            ),
            {"backend"},
        )

        frontend_route = parse_route(["--frontend"], env={})
        self.assertEqual(
            StartupOrchestrator._restart_service_types_for_project(
                route=frontend_route,
                project_name="Main",
                default_service_types={"backend", "frontend"},
            ),
            {"frontend"},
        )

        dependencies_route = parse_route(["--dependencies"], env={})
        self.assertEqual(
            StartupOrchestrator._restart_service_types_for_project(
                route=dependencies_route,
                project_name="Main",
                default_service_types={"backend", "frontend"},
            ),
            set(),
        )

        fullstack_route = parse_route(["--fullstack"], env={})
        self.assertEqual(
            StartupOrchestrator._restart_service_types_for_project(
                route=fullstack_route,
                project_name="Main",
                default_service_types={"backend", "frontend"},
            ),
            {"backend", "frontend"},
        )

    def test_startup_skip_flags_remove_individual_worktree_launch_parts(self) -> None:
        route = parse_route(["--tree", "--fullstack", "--no-backend"], env={})
        self.assertEqual(
            StartupOrchestrator._restart_service_types_for_project(
                route=route,
                project_name="feature-a-1",
                default_service_types={"backend", "frontend"},
            ),
            {"frontend"},
        )

        route = parse_route(["--tree", "--fullstack", "--no-frontend"], env={})
        self.assertEqual(
            StartupOrchestrator._restart_service_types_for_project(
                route=route,
                project_name="feature-a-1",
                default_service_types={"backend", "frontend"},
            ),
            {"backend"},
        )

        route = parse_route(["--tree", "--fullstack", "--no-infra"], env={})
        self.assertEqual(
            StartupOrchestrator._restart_service_types_for_project(
                route=route,
                project_name="feature-a-1",
                default_service_types={"backend", "frontend"},
            ),
            set(),
        )

    def test_no_deps_disables_startup_requirements_for_worktree_runs(self) -> None:
        class Config:
            def startup_enabled_for_mode(self, mode: str) -> bool:
                return True

            def requirement_enabled_for_mode(self, mode: str, requirement_name: str) -> bool:
                return True

        runtime = SimpleNamespace(config=Config())
        route = parse_route(["--tree", "--no-deps"], env={})

        self.assertFalse(requirement_enabled_for_mode(runtime, "trees", "redis", route=route))

    def test_runtime_scope_flags_control_restart_requirements(self) -> None:
        self.assertFalse(StartupOrchestrator._restart_include_requirements(parse_route(["restart", "--backend"], env={})))
        self.assertFalse(StartupOrchestrator._restart_include_requirements(parse_route(["restart", "--fullstack"], env={})))
        self.assertTrue(StartupOrchestrator._restart_include_requirements(parse_route(["restart", "--dependencies"], env={})))
        self.assertTrue(StartupOrchestrator._restart_include_requirements(parse_route(["restart", "--entire-system"], env={})))

    def test_non_restart_defaults_to_configured_service_types(self) -> None:
        selected = StartupOrchestrator._restart_service_types_for_project(
            route=None,
            project_name="Main",
            default_service_types={"frontend"},
        )

        self.assertEqual(selected, {"frontend"})


if __name__ == "__main__":
    unittest.main()
