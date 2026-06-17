from __future__ import annotations

import importlib
from pathlib import Path
import unittest
from io import StringIO
from contextlib import redirect_stdout
from types import SimpleNamespace
import tempfile
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
dispatch_module = importlib.import_module("envctl_engine.runtime.engine_runtime_dispatch")
utility_module = importlib.import_module("envctl_engine.runtime.utility_command_support")
dispatch = dispatch_module.dispatch
dispatch_command = dispatch_module.dispatch_command


class EngineRuntimeDispatchTests(unittest.TestCase):
    def test_dispatch_entry_configures_probe_debug_recorder_and_route_events(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        calls: list[str] = []
        route = SimpleNamespace(command="start", mode="main")
        runtime = SimpleNamespace(
            process_probe=None,
            _build_process_probe_backend=lambda: calls.append("probe_backend") or "backend",
            _effective_start_mode=lambda value: calls.append(f"effective:{value.command}") or "trees",
            _configure_debug_recorder=lambda value: calls.append(f"debug:{value.command}"),
            _emit=lambda event, **payload: events.append((event, payload)),
        )

        with (
            patch(
                "envctl_engine.runtime.engine_runtime_dispatch.ProcessProbe",
                side_effect=lambda backend: ("probe", backend),
            ),
            patch(
                "envctl_engine.runtime.engine_runtime_dispatch.dispatch_command",
                return_value=9,
            ) as command_dispatch,
        ):
            code = dispatch(runtime, route)

        self.assertEqual(code, 9)
        self.assertEqual(runtime.process_probe, ("probe", "backend"))
        self.assertEqual(calls, ["probe_backend", "effective:start", "debug:start"])
        self.assertEqual(
            events,
            [
                (
                    "engine.mode.selected",
                    {"mode": "main", "effective_mode": "trees", "command": "start"},
                ),
                (
                    "command.route.selected",
                    {"mode": "main", "effective_mode": "trees", "command": "start"},
                ),
            ],
        )
        command_dispatch.assert_called_once_with(runtime, route)

    def test_dispatch_entry_uses_route_mode_for_non_startup_commands(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        route = SimpleNamespace(command="health", mode="trees")
        runtime = SimpleNamespace(
            process_probe=None,
            _build_process_probe_backend=lambda: "backend",
            _effective_start_mode=lambda _route: (_ for _ in ()).throw(AssertionError("should not resolve")),
            _configure_debug_recorder=lambda _route: None,
            _emit=lambda event, **payload: events.append((event, payload)),
        )

        with (
            patch(
                "envctl_engine.runtime.engine_runtime_dispatch.ProcessProbe",
                side_effect=lambda backend: ("probe", backend),
            ),
            patch(
                "envctl_engine.runtime.engine_runtime_dispatch.dispatch_command",
                return_value=4,
            ),
        ):
            code = dispatch(runtime, route)

        self.assertEqual(code, 4)
        self.assertTrue(all(payload["effective_mode"] == "trees" for _event, payload in events))

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

    def test_utility_command_dispatch_routes_to_codex_tmux_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir(parents=True, exist_ok=True)
            runtime = SimpleNamespace(
                env={},
                config=SimpleNamespace(base_dir=repo),
                _command_exists=lambda command: command in {"tmux", "codex"},
                process_runner=SimpleNamespace(
                    run_probe=lambda *args, **kwargs: __import__("subprocess").CompletedProcess(
                        args=["tmux"],
                        returncode=1,
                        stdout="",
                        stderr="",
                    )
                ),
            )
            route = SimpleNamespace(command="codex-tmux", mode="main", flags={"dry_run": True}, passthrough_args=[])

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = dispatch_command(runtime, route)

        self.assertEqual(code, 0)
        self.assertIn("session_name:", buffer.getvalue())

    def test_utility_command_dispatch_routes_to_supabase_user_support(self) -> None:
        runtime = SimpleNamespace(config=SimpleNamespace(supabase_auth_users=()))
        route = SimpleNamespace(command="supabase-user", mode="main", flags={"json": True}, passthrough_args=["list"])

        with patch(
            "envctl_engine.runtime.utility_command_support.run_supabase_user_command",
            return_value=0,
        ) as command:
            code = dispatch_command(runtime, route)

        self.assertEqual(code, 0)
        command.assert_called_once_with(runtime, route)

    def test_utility_command_handlers_are_table_driven_and_complete(self) -> None:
        self.assertEqual(
            set(utility_module.utility_command_handlers()),
            {
                "install-prompts",
                "codex-tmux",
                "ensure-worktree",
                "supabase-user",
                "qa-user",
                "playwright",
                "pr-preview-controller",
            },
        )

    def test_utility_command_dispatch_reports_unknown_command(self) -> None:
        runtime = SimpleNamespace()
        route = SimpleNamespace(command="unknown-utility")

        with self.assertRaisesRegex(RuntimeError, "Unsupported utility command: unknown-utility"):
            utility_module.dispatch_utility_command(runtime, route)


if __name__ == "__main__":
    unittest.main()
