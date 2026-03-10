from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import parse_route
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

    def test_non_restart_defaults_to_configured_service_types(self) -> None:
        selected = StartupOrchestrator._restart_service_types_for_project(
            route=None,
            project_name="Main",
            default_service_types={"frontend"},
        )

        self.assertEqual(selected, {"frontend"})


if __name__ == "__main__":
    unittest.main()
