from __future__ import annotations

import importlib
from pathlib import Path
import unittest
from io import StringIO
from contextlib import redirect_stdout
from types import SimpleNamespace
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
dispatch_command = importlib.import_module("envctl_engine.runtime.engine_runtime_dispatch").dispatch_command


class EngineRuntimeDispatchTests(unittest.TestCase):
    def test_list_commands_dispatch_prints_supported_commands(self) -> None:
        runtime = SimpleNamespace()
        route = SimpleNamespace(command="list-commands", mode="main")

        buffer = StringIO()
        with redirect_stdout(buffer):
            code = dispatch_command(runtime, route)

        self.assertEqual(code, 0)
        output = buffer.getvalue()
        self.assertIn("help", output)
        self.assertIn("blast-worktree", output)

    def test_action_command_dispatch_routes_to_action_orchestrator(self) -> None:
        seen: list[str] = []
        runtime = SimpleNamespace(
            action_command_orchestrator=SimpleNamespace(execute=lambda route: seen.append(str(route.command)) or 7),
            _unsupported_command=lambda command: 1,
        )
        route = SimpleNamespace(command="test", mode="main")

        code = dispatch_command(runtime, route)

        self.assertEqual(code, 7)
        self.assertEqual(seen, ["test"])

    def test_state_command_dispatch_routes_to_state_orchestrator(self) -> None:
        seen: list[str] = []
        runtime = SimpleNamespace(
            state_action_orchestrator=SimpleNamespace(execute=lambda route: seen.append(str(route.command)) or 5),
            _unsupported_command=lambda command: 1,
        )
        route = SimpleNamespace(command="health", mode="main")

        code = dispatch_command(runtime, route)

        self.assertEqual(code, 5)
        self.assertEqual(seen, ["health"])

    def test_startup_command_dispatch_routes_to_startup_orchestrator(self) -> None:
        seen: list[str] = []
        runtime = SimpleNamespace(
            startup_orchestrator=SimpleNamespace(execute=lambda route: seen.append(str(route.command)) or 3),
            _unsupported_command=lambda command: 1,
        )
        route = SimpleNamespace(command="plan", mode="trees")

        code = dispatch_command(runtime, route)

        self.assertEqual(code, 3)
        self.assertEqual(seen, ["plan"])

    def test_utility_command_dispatch_routes_to_prompt_installer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = SimpleNamespace(command="install-prompts", mode="main", flags={"cli": "codex", "dry_run": True})

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = dispatch_command(runtime, route)

        self.assertEqual(code, 0)
        self.assertIn("codex: planned", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
