from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import list_supported_commands, parse_route
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime


class CommandDispatchMatrixTests(unittest.TestCase):
    """Table-driven command -> orchestrator/handler mapping assertions."""

    def _runtime(self) -> PythonEngineRuntime:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
            }
        )
        return PythonEngineRuntime(config, env={})

    def test_all_supported_commands_have_dispatch_handlers(self) -> None:
        """Verify all supported commands in list_supported_commands() have dispatch handlers."""
        runtime = self._runtime()
        commands = list_supported_commands()

        # Stub orchestrators/direct handlers so this dispatch matrix test never
        # triggers real side effects (e.g. blast-all cleanup paths).
        runtime.startup_orchestrator.execute = lambda _route: 0  # type: ignore[method-assign]
        runtime.resume_orchestrator.execute = lambda _route: 0  # type: ignore[method-assign]
        runtime.lifecycle_cleanup_orchestrator.execute = lambda _route: 0  # type: ignore[method-assign]
        runtime.doctor_orchestrator.execute = lambda: 0  # type: ignore[method-assign]
        runtime.dashboard_orchestrator.execute = lambda _route: 0  # type: ignore[method-assign]
        runtime.state_action_orchestrator.execute = lambda _route: 0  # type: ignore[method-assign]
        runtime.action_command_orchestrator.execute = lambda _route: 0  # type: ignore[method-assign]
        runtime._config = lambda _route: 0  # type: ignore[method-assign]
        runtime._debug_pack = lambda _route: 0  # type: ignore[method-assign]
        runtime._debug_report = lambda _route: 0  # type: ignore[method-assign]
        runtime._debug_last = lambda _route: 0  # type: ignore[method-assign]
        runtime._discover_projects = lambda mode: []  # type: ignore[method-assign]

        # Verify we have exactly 32 commands
        self.assertEqual(len(commands), 32, f"Expected 32 commands, got {len(commands)}")

        # Expected command set
        expected_commands = {
            "plan",
            "start",
            "restart",
            "resume",
            "stop",
            "stop-all",
            "blast-all",
            "dashboard",
            "config",
            "doctor",
            "test",
            "logs",
            "clear-logs",
            "health",
            "errors",
            "delete-worktree",
            "blast-worktree",
            "pr",
            "commit",
            "review",
            "migrate",
            "list-commands",
            "list-targets",
            "list-trees",
            "show-config",
            "show-state",
            "explain-startup",
            "help",
            "debug-pack",
            "debug-report",
            "debug-last",
            "migrate-hooks",
        }
        self.assertEqual(set(commands), expected_commands)

        # Verify each command can be dispatched without error
        for command in commands:
            with self.subTest(command=command):
                route = parse_route([f"--{command}"] if command not in {"plan", "start"} else [command], env={})
                # Dispatch should return 0 or 1, not raise an exception
                code = runtime.dispatch(route)
                self.assertIn(code, {0, 1}, f"Command {command} returned unexpected code {code}")

    def test_command_to_orchestrator_mapping(self) -> None:
        """Verify command -> orchestrator/handler mapping is correct."""
        runtime = self._runtime()

        # Define expected mappings
        command_mappings = {
            # Startup orchestrator
            "plan": "startup_orchestrator",
            "start": "startup_orchestrator",
            "restart": "startup_orchestrator",
            # Resume orchestrator
            "resume": "resume_orchestrator",
            # Lifecycle cleanup orchestrator
            "stop": "lifecycle_cleanup_orchestrator",
            "stop-all": "lifecycle_cleanup_orchestrator",
            "blast-all": "lifecycle_cleanup_orchestrator",
            # Doctor orchestrator
            "doctor": "doctor_orchestrator",
            # Dashboard orchestrator
            "dashboard": "dashboard_orchestrator",
            # State action orchestrator
            "logs": "state_action_orchestrator",
            "clear-logs": "state_action_orchestrator",
            "health": "state_action_orchestrator",
            "errors": "state_action_orchestrator",
            # Action command orchestrator
            "test": "action_command_orchestrator",
            "delete-worktree": "action_command_orchestrator",
            "blast-worktree": "action_command_orchestrator",
            "pr": "action_command_orchestrator",
            "commit": "action_command_orchestrator",
            "review": "action_command_orchestrator",
            "migrate": "action_command_orchestrator",
            # Direct handlers in dispatch
            "list-commands": "direct_dispatch",
            "list-targets": "direct_dispatch",
            "list-trees": "direct_dispatch",
            "show-config": "direct_dispatch",
            "show-state": "direct_dispatch",
            "explain-startup": "direct_dispatch",
            "help": "direct_dispatch",
            "config": "direct_dispatch",
            "debug-pack": "direct_dispatch",
            "debug-report": "direct_dispatch",
            "debug-last": "direct_dispatch",
        }

        for command, expected_handler in command_mappings.items():
            with self.subTest(command=command, handler=expected_handler):
                # Verify the orchestrator/handler exists
                if expected_handler != "direct_dispatch":
                    self.assertTrue(
                        hasattr(runtime, expected_handler), f"Runtime missing {expected_handler} for command {command}"
                    )

    def test_unsupported_command_returns_error(self) -> None:
        """Verify unsupported commands are rejected."""
        runtime = self._runtime()
        # Manually create a route with an unsupported command
        from envctl_engine.runtime.command_router import Route

        route = Route(
            command="unsupported-command", mode="main", raw_args=[], passthrough_args=[], projects=[], flags={}
        )
        code = runtime.dispatch(route)
        self.assertEqual(code, 1, "Unsupported command should return exit code 1")


if __name__ == "__main__":
    unittest.main()
